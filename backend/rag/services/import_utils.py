import logging
from datetime import date, datetime
from typing import Dict, Optional
from urllib.parse import parse_qs, urlparse

from rag.models import Document, PaperSource, Session
from rag.services.job_queue import enqueue_job
from rag.utils import normalize_filename

logger = logging.getLogger(__name__)


def coerce_published_date(value) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y/%m", "%Y"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt == "%Y":
                return date(parsed.year, 1, 1)
            if fmt in ("%Y-%m", "%Y/%m"):
                return date(parsed.year, parsed.month, 1)
            return parsed.date()
        except ValueError:
            continue
    return None


def looks_like_pdf_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    path = (parsed.path or "").lower()
    if path.endswith(".pdf"):
        return True
    query = parse_qs(parsed.query or "")
    for values in query.values():
        for value in values:
            if str(value).lower().endswith(".pdf"):
                return True
    return False


def queue_remote_import(
    *,
    session_name: str,
    source_type: str,
    external_id: str,
    metadata: Dict,
    pdf_url: str = "",
    filename_prefix: Optional[str] = None,
) -> Dict:
    session = Session.objects.get(name=session_name)
    suffix = ".pdf" if looks_like_pdf_url(pdf_url) else "_abstract.txt"
    prefix = filename_prefix or source_type
    short_id = (external_id or metadata.get("doi") or metadata.get("title") or "paper")[:48]
    safe_filename = normalize_filename(f"{prefix}_{short_id}{suffix}")

    document, created = Document.objects.get_or_create(
        filename=safe_filename,
        session=session,
        defaults={
            "storage_path": f"pdfs/{safe_filename}" if suffix == ".pdf" else None,
            "status": "QUEUED",
            "title": metadata.get("title") or "Untitled paper",
            "abstract": metadata.get("abstract") or "",
        },
    )

    if not created:
        document.status = "QUEUED"
        document.title = metadata.get("title") or document.title
        document.abstract = metadata.get("abstract") or document.abstract
        document.error_message = None
        document.processing_started_at = None
        document.processing_completed_at = None
        document.filename = safe_filename
        document.storage_path = f"pdfs/{safe_filename}" if suffix == ".pdf" else None
        update_fields = [
            "filename",
            "status",
            "title",
            "abstract",
            "error_message",
            "processing_started_at",
            "processing_completed_at",
            "storage_path",
        ]
        document.save(update_fields=update_fields)

    paper_source, _ = PaperSource.objects.get_or_create(
        source_type=source_type,
        external_id=external_id,
        defaults={
            "title": metadata.get("title") or "Untitled paper",
            "authors": ", ".join(metadata.get("authors") or []),
            "abstract": metadata.get("abstract") or "",
            "published_date": coerce_published_date(metadata.get("published_date")),
            "pdf_url": pdf_url or metadata.get("pdf_url") or "",
            "entry_url": metadata.get("entry_url") or "",
            "document": document,
        },
    )
    paper_source.title = metadata.get("title") or paper_source.title
    paper_source.authors = ", ".join(metadata.get("authors") or []) or paper_source.authors
    paper_source.abstract = metadata.get("abstract") or paper_source.abstract
    paper_source.published_date = coerce_published_date(metadata.get("published_date"))
    paper_source.pdf_url = pdf_url or metadata.get("pdf_url") or paper_source.pdf_url
    paper_source.entry_url = metadata.get("entry_url") or paper_source.entry_url
    paper_source.document = document
    paper_source.save()

    job, _ = enqueue_job(
        "REMOTE_PDF_IMPORT",
        document=document,
        paper_source=paper_source,
        session=session,
        payload={
            "metadata": metadata,
            "pdf_url": pdf_url,
            "storage_path": document.storage_path,
            "source_type": source_type,
        },
    )
    return {
        "success": True,
        "message": "Import queued",
        "document_id": document.id,
        "paper_source_id": paper_source.id,
        "job_id": job.id,
        "status": document.status,
    }
