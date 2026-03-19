import logging
import os
import socket
from datetime import timedelta
from pathlib import Path

import arxiv
import requests
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from rag.models import Document, IngestionJob, PaperSource
from rag.services.ingestion import IngestionService
from rag.services.import_utils import looks_like_pdf_url
from rag.utils import normalize_filename

logger = logging.getLogger(__name__)


class IngestionJobRunner:
    def __init__(self):
        self.ingestion_service = IngestionService()
        self.worker_id = f"{socket.gethostname()}:{os.getpid()}"

    def claim_next_job(self):
        now = timezone.now()
        with transaction.atomic():
            job = (
                IngestionJob.objects.select_for_update()
                .filter(status="QUEUED", available_at__lte=now)
                .order_by("created_at")
                .first()
            )
            if job is None:
                return None

            updated = (
                IngestionJob.objects.filter(id=job.id, status="QUEUED")
                .update(
                    status="RUNNING",
                    started_at=now,
                    completed_at=None,
                    last_error="",
                    worker_id=self.worker_id,
                    attempts=F("attempts") + 1,
                )
            )
            if updated != 1:
                return None

        return IngestionJob.objects.get(id=job.id)

    def run_job(self, job: IngestionJob):
        payload = job.payload or {}

        if job.job_type == "DOCUMENT_INGEST":
            self._run_document_ingestion(job.document_id)
            return
        if job.job_type == "ARXIV_IMPORT":
            self._run_arxiv_import(
                document_id=job.document_id,
                paper_source_id=job.paper_source_id,
                arxiv_id=payload["arxiv_id"],
                storage_path=payload["storage_path"],
            )
            return
        if job.job_type == "PUBMED_IMPORT":
            self._run_pubmed_import(
                document_id=job.document_id,
                paper_source_id=job.paper_source_id,
                metadata=payload["metadata"],
            )
            return
        if job.job_type == "SEMANTIC_SCHOLAR_IMPORT":
            self._run_semantic_scholar_import(
                document_id=job.document_id,
                paper_source_id=job.paper_source_id,
                metadata=payload["metadata"],
                pdf_url=payload.get("pdf_url"),
                storage_path=payload.get("storage_path"),
            )
            return
        if job.job_type == "REMOTE_PDF_IMPORT":
            self._run_remote_pdf_import(
                document_id=job.document_id,
                paper_source_id=job.paper_source_id,
                metadata=payload["metadata"],
                pdf_url=payload.get("pdf_url"),
                storage_path=payload.get("storage_path"),
            )
            return

        raise ValueError(f"Unsupported job type: {job.job_type}")

    def mark_succeeded(self, job: IngestionJob):
        IngestionJob.objects.filter(id=job.id).update(
            status="SUCCEEDED",
            completed_at=timezone.now(),
            last_error="",
        )

    def mark_failed(self, job: IngestionJob, exc: Exception):
        job.refresh_from_db(fields=["attempts", "max_attempts"])
        now = timezone.now()
        final_failure = job.attempts >= job.max_attempts
        update_fields = {
            "last_error": str(exc),
            "worker_id": self.worker_id,
        }
        if not final_failure:
            backoff_seconds = min(60, 2 ** max(job.attempts - 1, 0))
            update_fields.update(
                {
                    "status": "QUEUED",
                    "available_at": now + timedelta(seconds=backoff_seconds),
                    "started_at": None,
                    "completed_at": None,
                }
            )
        else:
            update_fields.update(
                {
                    "status": "FAILED",
                    "completed_at": now,
                }
            )
        IngestionJob.objects.filter(id=job.id).update(**update_fields)
        if job.document_id:
            document_update = {
                "error_message": str(exc),
            }
            if final_failure:
                document_update["status"] = "FAILED"
            else:
                document_update["status"] = "QUEUED"
            Document.objects.filter(id=job.document_id).update(**document_update)

    def process_next_job(self):
        job = self.claim_next_job()
        if job is None:
            return None

        try:
            logger.info("Running ingestion job %s (%s)", job.id, job.job_type)
            self.run_job(job)
            self.mark_succeeded(job)
        except Exception as exc:
            logger.exception("Ingestion job %s failed", job.id)
            self.mark_failed(job, exc)
        return IngestionJob.objects.get(id=job.id)

    def _require_success(self, result: dict | None):
        if isinstance(result, dict) and result.get("status") == "error":
            raise RuntimeError(result.get("message") or "Ingestion failed")
        return result

    def _convert_document_to_summary_only(
        self,
        *,
        document_id: int,
        source_type: str,
        external_id: str | None = None,
        title: str | None = None,
    ) -> Document:
        document = Document.objects.get(id=document_id)
        identifier = (external_id or title or document.filename or "paper")[:48]
        summary_filename = normalize_filename(f"{source_type}_{identifier}_abstract.txt")
        document.filename = summary_filename
        document.storage_path = None
        document.save(update_fields=["filename", "storage_path"])
        return document

    def _run_document_ingestion(self, document_id: int):
        document = Document.objects.get(id=document_id)
        storage_path = document.resolved_storage_path

        if storage_path and default_storage.exists(storage_path):
            self._require_success(self.ingestion_service.ingest_document(
                document.id,
                default_storage.path(storage_path),
            ))
            paper_source = getattr(document, "paper_source", None)
            if paper_source and not paper_source.imported:
                paper_source.imported = True
                paper_source.save(update_fields=["imported"])
            return

        paper_source = getattr(document, "paper_source", None)
        if paper_source and (paper_source.abstract or document.abstract):
            self._require_success(self.ingestion_service.ingest_metadata_only(
                document_id=document.id,
                title=(paper_source.title or document.title or document.filename),
                abstract=(paper_source.abstract or document.abstract or ""),
                authors=(paper_source.authors or ""),
            ))
            if not paper_source.imported:
                paper_source.imported = True
                paper_source.save(update_fields=["imported"])
            return

        raise FileNotFoundError("No local PDF found and no metadata fallback available")

    def _run_pubmed_import(self, document_id: int, paper_source_id: int, metadata: dict):
        self._require_success(self.ingestion_service.ingest_metadata_only(
            document_id,
            metadata["title"],
            metadata["abstract"],
            ", ".join(metadata["authors"]),
        ))
        PaperSource.objects.filter(id=paper_source_id).update(imported=True)

    def _run_semantic_scholar_import(
        self,
        *,
        document_id: int,
        paper_source_id: int,
        metadata: dict,
        pdf_url: str | None,
        storage_path: str | None,
    ):
        if pdf_url and storage_path:
            try:
                self._download_url_to_storage(pdf_url, storage_path)
                self._require_success(self.ingestion_service.ingest_document(
                    document_id,
                    default_storage.path(storage_path),
                ))
                PaperSource.objects.filter(id=paper_source_id).update(imported=True)
                return
            except Exception as exc:
                logger.warning(
                    "Semantic Scholar PDF import failed for document %s; falling back to metadata: %s",
                    document_id,
                    exc,
                )
                source = PaperSource.objects.filter(id=paper_source_id).first()
                self._convert_document_to_summary_only(
                    document_id=document_id,
                    source_type="semanticscholar",
                    external_id=(source.external_id if source else None),
                    title=metadata.get("title"),
                )

        self._require_success(self.ingestion_service.ingest_metadata_only(
            document_id,
            metadata["title"],
            metadata["abstract"],
            ", ".join(metadata["authors"]),
        ))
        PaperSource.objects.filter(id=paper_source_id).update(imported=True)

    def _run_remote_pdf_import(
        self,
        *,
        document_id: int,
        paper_source_id: int,
        metadata: dict,
        pdf_url: str | None,
        storage_path: str | None,
    ):
        if pdf_url and storage_path:
            try:
                self._download_url_to_storage(pdf_url, storage_path)
                self._require_success(self.ingestion_service.ingest_document(
                    document_id,
                    default_storage.path(storage_path),
                ))
                PaperSource.objects.filter(id=paper_source_id).update(imported=True)
                return
            except Exception as exc:
                logger.warning(
                    "Remote PDF import failed for document %s; falling back to metadata: %s",
                    document_id,
                    exc,
                )
                source = PaperSource.objects.filter(id=paper_source_id).first()
                self._convert_document_to_summary_only(
                    document_id=document_id,
                    source_type=(source.source_type if source else "remote"),
                    external_id=(source.external_id if source else None),
                    title=metadata.get("title"),
                )

        self._require_success(self.ingestion_service.ingest_metadata_only(
            document_id,
            metadata.get("title") or "Untitled paper",
            metadata.get("abstract") or "",
            ", ".join(metadata.get("authors") or []),
        ))
        PaperSource.objects.filter(id=paper_source_id).update(imported=True)

    def _run_arxiv_import(
        self,
        *,
        document_id: int,
        paper_source_id: int,
        arxiv_id: str,
        storage_path: str,
    ):
        document = Document.objects.get(id=document_id)
        absolute_path = Path(default_storage.path(storage_path))
        absolute_path.parent.mkdir(parents=True, exist_ok=True)

        client = arxiv.Client(page_size=1, delay_seconds=3.0, num_retries=5)
        paper = next(client.results(arxiv.Search(id_list=[arxiv_id])))
        paper.download_pdf(dirpath=str(absolute_path.parent), filename=absolute_path.name)

        self.ingestion_service.ingest_document(document.id, str(absolute_path))
        PaperSource.objects.filter(id=paper_source_id).update(imported=True)

    def _download_url_to_storage(self, url: str, storage_path: str):
        if not looks_like_pdf_url(url):
            raise ValueError("Remote URL does not look like a direct PDF")
        absolute_path = Path(default_storage.path(storage_path))
        absolute_path.parent.mkdir(parents=True, exist_ok=True)

        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        content_type = (response.headers.get("Content-Type") or "").lower()
        content_disposition = (response.headers.get("Content-Disposition") or "").lower()
        if "pdf" not in content_type and ".pdf" not in content_disposition:
            first_chunk = next(response.iter_content(chunk_size=1024), b"")
            if not first_chunk.startswith(b"%PDF-"):
                raise ValueError("Remote response is not a PDF")
            chunks = [first_chunk]
        else:
            chunks = []
        with open(absolute_path, "wb") as file_handle:
            for chunk in chunks:
                if chunk:
                    file_handle.write(chunk)
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    file_handle.write(chunk)
