import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
from django.utils import timezone

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Session, Document, Question, Answer, RunLog, PaperSource, IngestionJob
from .utils import (
    get_default_session,
    get_or_create_session,
    normalize_filename,
    sanitize_json_value,
    sanitize_text,
)
from .query import ask_with_citations, retrieve_paper_overview

from .services.job_queue import enqueue_job
from .services.metrics import MetricsService
from .services.synthesis import SynthesisService
from .services.retrieval import RetrievalService
from .services.discovery import DiscoveryService

from .router import is_title_question, is_about_paper_question, is_page_count_question


def _documents_using_storage_path(storage_path: str, exclude_document_id: int | None = None):
    if not storage_path:
        return Document.objects.none()

    queryset = Document.objects.filter(storage_path=storage_path)
    if exclude_document_id is not None:
        queryset = queryset.exclude(id=exclude_document_id)
    return queryset


def _build_metadata_overview_answer(document: Document) -> dict:
    title = (document.title or document.filename or "Untitled paper").strip()
    abstract = (document.abstract or "").strip()
    source = getattr(document, "paper_source", None)
    authors = getattr(source, "authors", "") if source else ""
    published = getattr(source, "published_date", None) if source else None
    entry_url = getattr(source, "entry_url", "") if source else ""
    source_type = getattr(source, "source_type", "") if source else ""
    abstract_missing = not abstract or abstract.lower() == "no abstract available."

    lines = [f"{title}"]
    if authors:
        lines.append(f"Authors: {authors}")
    if published:
        lines.append(f"Published: {published}")
    if source_type:
        lines.append(f"Source: {source_type}")
    if abstract and not abstract_missing:
        lines.append("")
        lines.append(f"Abstract summary: {abstract}")
    else:
        lines.append("")
        lines.append(
            "I only have bibliographic metadata for this source, not a usable abstract or full text."
        )
        lines.append(
            "That means I cannot reliably answer what the paper is about beyond its title and citation details."
        )
    if entry_url:
        lines.append("")
        lines.append(f"Source page: {entry_url}")

    lines.append("")
    lines.append("This answer is based on source metadata because the full PDF was not available.")

    return {
        "answer": "\n".join(lines),
        "citations": [],
        "is_refusal": False,
        "is_insufficient_evidence": False,
        "retrieved_chunks_count": 1 if abstract else 0,
        "confidence_score": 0.55 if abstract else 0.35,
        "retrieval_ms": 0,
        "generation_ms": 0,
    }


@api_view(["GET"])
def document_status(request, document_id):
    """
    Get detailed status of a document ingestion.
    """
    try:
        document = Document.objects.get(id=document_id)

        processing_time = None
        if document.processing_started_at and document.processing_completed_at:
            processing_time = (
                document.processing_completed_at - document.processing_started_at
            ).total_seconds()

        return Response({
            "document_id": document.id,
            "filename": document.filename,
            "session": document.session.name,
            "status": document.status,
            "uploaded_at": document.uploaded_at,
            "processing_started_at": document.processing_started_at,
            "processing_completed_at": document.processing_completed_at,
            "processing_time_seconds": processing_time,
            "error_message": document.error_message,
            "metadata": {
                "title": document.title,
                "abstract": document.abstract,
                "page_count": document.page_count
            }
        }, status=status.HTTP_200_OK)

    except Document.DoesNotExist:
        return Response(
            {"error": "Document not found"},
            status=status.HTTP_404_NOT_FOUND
        )


@api_view(["GET"])
def document_page_text(request, document_id):
    """
    Return extracted text for a specific document page.
    Falls back to metadata-only content for virtual/non-PDF imports.
    Query param:
      - page (1-indexed)
    """
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return Response(
            {"error": "Document not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        page = int(request.GET.get("page", "1"))
    except ValueError:
        return Response(
            {"error": "Invalid page parameter"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if page < 1:
        return Response(
            {"error": "Page must be >= 1"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    file_path = document.resolved_storage_path
    looks_like_pdf = document.filename.lower().endswith(".pdf")

    if looks_like_pdf and default_storage.exists(file_path):
        try:
            from pypdf import PdfReader

            reader = PdfReader(default_storage.path(file_path))

            if page > len(reader.pages):
                return Response(
                    {"error": "Page out of range"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            text = (reader.pages[page - 1].extract_text() or "").strip()
            return Response(
                {
                    "document_id": document.id,
                    "filename": document.filename,
                    "page": page,
                    "page_count": len(reader.pages),
                    "text": text,
                    "content_type": "pdf",
                },
                status=status.HTTP_200_OK,
            )
        except Exception as exc:
            logger.warning(
                f"PDF text extraction failed for document {document.id} ({document.filename}): {exc}"
            )

    if page > 1:
        return Response(
            {"error": "Page out of range"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    paper_source = getattr(document, "paper_source", None)
    title = (paper_source.title if paper_source else None) or document.title or document.filename
    authors = (paper_source.authors if paper_source else None) or ""
    abstract = (paper_source.abstract if paper_source else None) or document.abstract or ""
    entry_url = (paper_source.entry_url if paper_source else None) or ""
    source_type = (paper_source.source_type if paper_source else None) or "manual"

    content_parts = [f"TITLE: {title}"]
    if authors:
        content_parts.append(f"AUTHORS: {authors}")
    if abstract:
        content_parts.append(f"\nABSTRACT:\n{abstract}")
    if entry_url:
        content_parts.append(f"\nSOURCE URL:\n{entry_url}")

    return Response(
        {
            "document_id": document.id,
            "filename": document.filename,
            "page": page,
            "page_count": document.page_count or 1,
            "text": "\n".join(content_parts).strip(),
            "content_type": "text",
            "source_type": source_type,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def retry_document_ingestion(request, document_id):
    """
    Retry ingestion for a document that failed or was interrupted.
    """
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return Response(
            {"error": "Document not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    if document.status == "PROCESSING":
        return Response(
            {"error": "Document is already processing"},
            status=status.HTTP_409_CONFLICT,
        )

    existing_job = IngestionJob.objects.filter(
        document=document,
        status__in=["QUEUED", "RUNNING"],
    ).first()
    if existing_job:
        return Response(
            {"error": "Document already has an active ingestion job"},
            status=status.HTTP_409_CONFLICT,
        )

    # Reset status before retry
    document.status = "QUEUED"
    document.error_message = None
    document.processing_started_at = None
    document.processing_completed_at = None
    document.save(
        update_fields=[
            "status",
            "error_message",
            "processing_started_at",
            "processing_completed_at",
        ]
    )
    job, _ = enqueue_job(
        "DOCUMENT_INGEST",
        document=document,
        session=document.session,
        payload={"document_id": document.id},
    )

    return Response(
        {
            "message": "Retry queued",
            "document_id": document.id,
            "job_id": job.id,
            "status": document.status,
        },
        status=status.HTTP_202_ACCEPTED,
    )

@api_view(["GET"])
def metrics_summary(request):
    """
    Get aggregated metrics for monitoring dashboard.
    """
    since_days = request.GET.get("since", "7")
    try:
        since_days = int(since_days)
    except ValueError:
        since_days = 7

    metrics_service = MetricsService()
    summary = metrics_service.get_summary(since_days=since_days)
    return Response(summary, status=status.HTTP_200_OK)

@api_view(["POST"])
def ask_question(request):
    question_text = request.data.get("question")
    session_name = request.data.get("session")
    sources = request.data.get("sources") or []
    mode = request.data.get("mode", "qa")  # New: mode support

    if not question_text:
        return Response(
            {"error": "Missing 'question'"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Normalize sources
    sources = [normalize_filename(s) for s in sources]

    if mode == "compare" and len(set(sources or [])) < 2:
        return Response(
            {
                "error": "Compare mode requires at least 2 distinct selected documents.",
                "message": "Select at least 2 papers, then run compare again.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    if mode == "lit_review" and len(set(sources or [])) < 2:
        return Response(
            {
                "error": "Literature review mode requires at least 2 distinct selected documents.",
                "message": "Use QA for single-paper questions, or select at least 2 papers for a cross-paper literature review.",
            },
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Resolve session
    session = get_or_create_session(session_name)

    question_obj = Question.objects.create(
        text=sanitize_text(question_text),
        session=session
    )

    start_time = time.time()
    metrics_service = MetricsService()
    synthesis_service = SynthesisService()
    retrieved_chunks = []
    grounding_info = {
        "is_refusal": False,
        "is_insufficient_evidence": False,
        "retrieved_chunks_count": 0,
        "confidence_score": None,
    }
    stage_timings = {
        "retrieval_ms": None,
        "generation_ms": None,
    }

    try:
        if mode == "compare":
            distinct_selected = set(sources or [])
            # ---- COMPARE MODE — balanced hybrid retrieval ----
            retrieval = RetrievalService(session.name)
            retrieval_start = time.perf_counter()

            # Force per-source retrieval to avoid source imbalance in comparison.
            scored_docs = []
            seen_chunk_ids = set()
            for src in distinct_selected:
                source_docs = retrieval.retrieve(
                    query=question_text,
                    sources=[src],
                    k=5,
                    use_hybrid=True,
                    use_multi_query=False,   # skip multi-query for speed
                    use_reranking=True,
                )
                for doc in source_docs:
                    if doc.chunk_id in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(doc.chunk_id)
                    scored_docs.append(doc)

            # Keep top chunks by score after balancing
            scored_docs.sort(key=lambda d: d.score, reverse=True)
            scored_docs = scored_docs[:14]
            stage_timings["retrieval_ms"] = int(
                (time.perf_counter() - retrieval_start) * 1000
            )

            distinct_retrieved_sources = {
                d.document.metadata.get("source") for d in scored_docs
            }
            distinct_retrieved_sources = {
                s for s in distinct_retrieved_sources if s
            }
            if len(distinct_retrieved_sources) < 2:
                result = {
                    "topic": question_text,
                    "claims": [],
                    "message": (
                        "I could not retrieve enough evidence from at least two "
                        "different selected documents to produce a reliable comparison."
                    ),
                    "num_papers": len(distinct_retrieved_sources),
                    "sources": list(distinct_retrieved_sources),
                }
                retrieved_chunks = [sd.to_citation_dict() for sd in scored_docs]
                result["citations"] = retrieved_chunks

                grounding_info["retrieved_chunks_count"] = len(scored_docs)
                if scored_docs:
                    grounding_info["confidence_score"] = round(
                        sum(d.score for d in scored_docs) / len(scored_docs), 4
                    )

                Answer.objects.create(
                    question=question_obj,
                    text=sanitize_text(result["message"]),
                    citations=sanitize_json_value(retrieved_chunks),
                    metadata=sanitize_json_value(result),
                )
            else:
                # Extract raw langchain docs for SynthesisService
                docs = [sd.document for sd in scored_docs]

                retrieved_chunks = [sd.to_citation_dict() for sd in scored_docs]
                grounding_info["retrieved_chunks_count"] = len(scored_docs)
                if scored_docs:
                    grounding_info["confidence_score"] = round(
                        sum(d.score for d in scored_docs) / len(scored_docs), 4
                    )

                generation_start = time.perf_counter()
                result = synthesis_service.compare_papers(question_text, docs, sources)
                stage_timings["generation_ms"] = int(
                    (time.perf_counter() - generation_start) * 1000
                )
                result["citations"] = retrieved_chunks

                Answer.objects.create(
                    question=question_obj,
                    text=f"Comparison on: {question_text}",
                    citations=sanitize_json_value(retrieved_chunks),
                    metadata=sanitize_json_value(result),
                )

        elif mode == "lit_review":
            # ---- LIT REVIEW MODE — balanced cross-paper retrieval ----
            retrieval = RetrievalService(session.name)
            retrieval_start = time.perf_counter()
            scored_docs = []
            seen_chunk_ids = set()
            for src in set(sources or []):
                source_docs = retrieval.retrieve(
                    query=question_text,
                    sources=[src],
                    k=6,
                    use_hybrid=True,
                    use_multi_query=False,
                    use_reranking=True,
                )
                for doc in source_docs:
                    if doc.chunk_id in seen_chunk_ids:
                        continue
                    seen_chunk_ids.add(doc.chunk_id)
                    scored_docs.append(doc)
            scored_docs.sort(key=lambda d: d.score, reverse=True)
            scored_docs = scored_docs[:18]
            stage_timings["retrieval_ms"] = int(
                (time.perf_counter() - retrieval_start) * 1000
            )

            docs = [sd.document for sd in scored_docs]

            retrieved_chunks = [sd.to_citation_dict() for sd in scored_docs]
            grounding_info["retrieved_chunks_count"] = len(scored_docs)
            if scored_docs:
                grounding_info["confidence_score"] = round(
                    sum(d.score for d in scored_docs) / len(scored_docs), 4
                )

            distinct_retrieved_sources = {
                d.metadata.get("source") for d in docs if d.metadata.get("source")
            }
            if len(distinct_retrieved_sources) < 2:
                result = {
                    "topic": question_text,
                    "title": f"Literature Review: {question_text}",
                    "content": (
                        "I could not retrieve enough evidence from at least two different "
                        "selected papers to produce a reliable literature review."
                    ),
                    "num_sources": len(distinct_retrieved_sources),
                    "review_status": "incompatible_sources",
                    "warning": (
                        "The selected papers do not support a reliable unified literature review for this topic. "
                        "The retrieved evidence came from too few distinct sources."
                    ),
                    "review_diagnostics": {
                        "review_status": "incompatible_sources",
                        "warning": (
                            "The selected papers do not support a reliable unified literature review for this topic. "
                            "The retrieved evidence came from too few distinct sources."
                        ),
                        "pairwise_overlap": 0.0,
                        "topic_relevance": {},
                        "fit_issues": [
                            "Usable retrieved evidence came from fewer than two selected papers."
                        ],
                        "next_step": (
                            "Refine the topic, verify that both papers contain relevant material, or switch to QA mode for paper-specific questions."
                        ),
                    },
                }
            else:
                generation_start = time.perf_counter()
                result = synthesis_service.generate_literature_review(
                    question_text, docs, sources
                )
                stage_timings["generation_ms"] = int(
                    (time.perf_counter() - generation_start) * 1000
                )
            result["citations"] = retrieved_chunks

            Answer.objects.create(
                question=question_obj,
                text=sanitize_text(result.get("content", "")),
                citations=sanitize_json_value(retrieved_chunks),
                metadata=sanitize_json_value({
                    "title": result.get("title"),
                    "mode": "lit_review",
                    "num_sources": result.get("num_sources"),
                    "review_status": result.get("review_status", "normal_review"),
                    "warning": result.get("warning", ""),
                    "review_diagnostics": result.get("review_diagnostics", {}),
                }),
            )

        else:
            # ---- QA MODE ----
            result = None

            # 1. SPECIALIZED AGENTS (Title, Page Count, Overview)
            if sources:
                try:
                    if is_title_question(question_text):
                        doc = Document.objects.get(
                            session=session, filename=sources[0]
                        )
                        result = {
                            "answer": doc.title or "Title not available.",
                            "citations": [],
                            "is_refusal": False,
                            "is_insufficient_evidence": False,
                            "retrieved_chunks_count": 0,
                            "confidence_score": 1.0,
                            "retrieval_ms": 0,
                            "generation_ms": 0,
                        }
                    elif is_page_count_question(question_text):
                        doc = Document.objects.get(
                            session=session, filename=sources[0]
                        )
                        result = {
                            "answer": (
                                f"The document '{doc.filename}' has "
                                f"{doc.page_count or 'unknown'} pages."
                            ),
                            "citations": [],
                            "is_refusal": False,
                            "is_insufficient_evidence": False,
                            "retrieved_chunks_count": 0,
                            "confidence_score": 1.0,
                            "retrieval_ms": 0,
                            "generation_ms": 0,
                        }
                    elif is_about_paper_question(question_text):
                        doc = Document.objects.select_related("paper_source").get(
                            session=session, filename=sources[0]
                        )
                        if doc.error_message and "Summary-only mode" in doc.error_message:
                            result = _build_metadata_overview_answer(doc)
                        else:
                            docs = retrieve_paper_overview(
                                question=question_text,
                                session_name=session.name,
                                source=sources[0],
                            )
                            result = ask_with_citations(
                                question=question_text,
                                session_name=session.name,
                                docs_override=docs,
                            )
                except Document.DoesNotExist:
                    logger.warning(
                        f"Specialized route failed: Document '{sources[0]}' "
                        f"not found in session '{session.name}'. "
                        f"Falling back to RAG."
                    )

            # 2. NO-CONTEXT DISCOVERY OR ABSTENTION
            if not result and not sources:
                discovery_service = DiscoveryService()
                if discovery_service.should_use_external_discovery(question_text):
                    result = discovery_service.answer_query_from_external_search(
                        question_text
                    )
                else:
                    result = discovery_service.build_abstention_response()

            # 3. DEFAULT RAG (Fallback or generic question)
            if not result:
                result = ask_with_citations(
                    question=question_text,
                    session_name=session.name,
                    sources=sources or None,
                )

            # Persist grounding info from the result
            grounding_info["is_refusal"] = result.get("is_refusal", False)
            grounding_info["is_insufficient_evidence"] = result.get(
                "is_insufficient_evidence", False
            )
            grounding_info["retrieved_chunks_count"] = result.get(
                "retrieved_chunks_count", 0
            )
            grounding_info["confidence_score"] = result.get(
                "confidence_score"
            )
            stage_timings["retrieval_ms"] = result.get("retrieval_ms")
            stage_timings["generation_ms"] = result.get("generation_ms")

            Answer.objects.create(
                question=question_obj,
                text=sanitize_text(result["answer"]),
                citations=sanitize_json_value(result["citations"]),
                metadata=sanitize_json_value({
                    "discovery_mode": result.get("discovery_mode"),
                    "source_basis": result.get("source_basis"),
                    "suggested_sources": result.get("suggested_sources", []),
                    "is_refusal": result.get("is_refusal", False),
                }),
            )

            retrieved_chunks = sanitize_json_value([
                {
                    "doc": c.get("source"),
                    "page": c.get("page"),
                    "chunk_id": c.get("chunk_id", ""),
                    "snippet": c.get("snippet", ""),
                    "score": c.get("score", 0.0),
                }
                for c in result.get("citations", [])
            ])

        # Log metrics (with grounding data)
        latency_ms = int((time.time() - start_time) * 1000)
        metrics_service.log_query(
            session=session,
            question=question_obj,
            question_text=question_text,
            mode=mode,
            sources=sources,
            latency_ms=latency_ms,
            retrieved_chunks=retrieved_chunks,
            is_refusal=grounding_info["is_refusal"],
            is_insufficient_evidence=grounding_info["is_insufficient_evidence"],
            retrieved_chunks_count=grounding_info["retrieved_chunks_count"],
            confidence_score=grounding_info["confidence_score"],
            retrieval_ms=stage_timings["retrieval_ms"],
            generation_ms=stage_timings["generation_ms"],
        )

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        metrics_service.log_query(
            session=session,
            question=question_obj,
            question_text=question_text,
            mode=mode,
            sources=sources,
            latency_ms=latency_ms,
            retrieved_chunks=retrieved_chunks,
            error=e,
            retrieval_ms=stage_timings["retrieval_ms"],
            generation_ms=stage_timings["generation_ms"],
        )
        return Response(
            {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )





@api_view(["POST"])
def upload_pdf(request):
    """
    Upload a PDF file and trigger async ingestion.
    """
    file = request.FILES.get("file")
    session_name = request.POST.get("session")

    if not file:
        return Response(
            {"error": "No file provided"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not file.name.lower().endswith(".pdf"):
        return Response(
            {"error": "Only PDF files are allowed"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Resolve session
    session = get_or_create_session(session_name)

    # Save file
    saved_path = default_storage.save(
        f"pdfs/{file.name}",
        ContentFile(file.read())
    )

    normalized = normalize_filename(file.name)

    # Register document in relational DB
    document, created = Document.objects.get_or_create(
        filename=normalized,
        session=session,
        defaults={"storage_path": saved_path, "status": "QUEUED"},
    )

    previous_storage_path = None if created else document.resolved_storage_path
    update_fields = []

    if document.storage_path != saved_path:
        document.storage_path = saved_path
        update_fields.append("storage_path")

    if created:
        document.status = "QUEUED"
        update_fields.append("status")

    # Reset status if re-uploading
    if not created:
        document.status = 'QUEUED'
        document.error_message = None
        document.processing_started_at = None
        document.processing_completed_at = None
        update_fields.extend([
            "status",
            "error_message",
            "processing_started_at",
            "processing_completed_at",
        ])

    if update_fields:
        document.save(update_fields=update_fields)

    if (
        previous_storage_path
        and previous_storage_path != saved_path
        and not _documents_using_storage_path(
            previous_storage_path,
            exclude_document_id=document.id,
        ).exists()
        and default_storage.exists(previous_storage_path)
    ):
        default_storage.delete(previous_storage_path)

    job, _ = enqueue_job(
        "DOCUMENT_INGEST",
        document=document,
        session=session,
        payload={"document_id": document.id},
    )

    return Response(
        {
            "message": "PDF upload queued for ingestion.",
            "document_id": document.id,
            "job_id": job.id,
            "filename": file.name,
            "stored_filename": document.filename,
            "file_url": document.file_url,
            "session": session.name,
            "status": document.status
        },
        status=status.HTTP_202_ACCEPTED
    )


@api_view(["GET"])
def list_pdfs(request):
    """
    List PDFs available in a session.
    """
    session_name = request.GET.get("session")

    session = get_or_create_session(session_name)

    pdfs = [
        {
            "id": document.id,
            "filename": document.filename,
            "storage_path": document.storage_path,
            "file_url": document.file_url,
            "uploaded_at": document.uploaded_at,
            "source_type": getattr(getattr(document, "paper_source", None), "source_type", "manual"),
            "paper_source_id": getattr(getattr(document, "paper_source", None), "id", None),
            "external_id": getattr(getattr(document, "paper_source", None), "external_id", ""),
            "entry_url": getattr(getattr(document, "paper_source", None), "entry_url", ""),
            "title": document.title,
            "abstract": document.abstract,
            "page_count": document.page_count,
            "status": document.status,
            "error_message": document.error_message,
        }
        for document in session.documents.select_related("paper_source").all()
    ]


    return Response(
        {
            "session": session.name,
            "pdfs": list(pdfs),
        },
        status=status.HTTP_200_OK
    )


@api_view(["POST"])
def create_session(request):
    name = request.data.get("name")
    pinned = bool(request.data.get("pinned", False))

    if not name:
        return Response(
            {"error": "Session name required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    session, created = Session.objects.get_or_create(
        name=name,
        defaults={"pinned": pinned},
    )
    if not created and pinned != session.pinned:
        session.pinned = pinned
        session.save(update_fields=["pinned"])

    return Response(
        {
            "session": session.name,
            "created": created,
            "pinned": session.pinned,
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )


@api_view(["GET"])
def list_sessions(request):
    sessions = Session.objects.all().order_by("-pinned", "-created_at", "name")
    data = [{"name": s.name, "pinned": s.pinned, "created_at": s.created_at} for s in sessions]
    return Response(data, status=status.HTTP_200_OK)


@api_view(["PATCH", "DELETE"])
def session_detail(request, session_name):
    try:
        session = Session.objects.get(name=session_name)
        if request.method == "PATCH":
            new_name = (request.data.get("name") or "").strip()
            pinned = request.data.get("pinned")

            if new_name and new_name != session.name:
                if Session.objects.exclude(id=session.id).filter(name=new_name).exists():
                    return Response({"error": "Session name already exists"}, status=status.HTTP_400_BAD_REQUEST)
                session.name = new_name

            if pinned is not None:
                session.pinned = bool(pinned)

            session.save()
            return Response(
                {
                    "session": session.name,
                    "pinned": session.pinned,
                },
                status=status.HTTP_200_OK,
            )

        # Chroma cleanup: get the path and delete the directory
        import shutil
        from .utils import get_session_path
        persist_dir = get_session_path(session_name)
        if Path(persist_dir).exists():
            shutil.rmtree(persist_dir)
            
        # Filesystem cleanup: potentially delete all PDFs unique to this session
        for doc in session.documents.all():
            other_uses = _documents_using_storage_path(
                doc.resolved_storage_path,
                exclude_document_id=doc.id,
            ).exists()
            if not other_uses:
                file_path = doc.resolved_storage_path
                if default_storage.exists(file_path):
                    default_storage.delete(file_path)
        
        session.delete()
        return Response({"message": "Session and all associated data deleted"}, status=status.HTTP_200_OK)
    except Session.DoesNotExist:
        return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
@api_view(["DELETE"])
def delete_pdf(request):
    """
    Remove a PDF from a session:
    1. Delete from relational DB
    2. Delete from Chroma vector store
    3. Cleanup physical file if no other session uses it
    """
    session_name = request.data.get("session")
    filename = request.data.get("filename")

    if not session_name or not filename:
        return Response(
            {"error": "Missing 'session' or 'filename'"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        session = Session.objects.get(name=session_name)
        document = Document.objects.get(session=session, filename=filename)
    except (Session.DoesNotExist, Document.DoesNotExist):
        return Response(
            {"error": "Document or Session not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    # 1. Delete from Chroma
    from langchain_chroma import Chroma
    from .services.ollama_client import create_embeddings
    from .utils import get_session_path

    persist_dir = get_session_path(session_name)
    embeddings = create_embeddings(model="nomic-embed-text")
    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    try:
        # Get IDs of documents to delete
        res = vectordb.get(where={"source": filename})
        if res["ids"]:
            vectordb.delete(ids=res["ids"])
    except Exception as e:
        print(f"Error deleting from Chroma: {e}")

    # 2. Delete from Filesystem
    file_path = document.resolved_storage_path
    other_uses = _documents_using_storage_path(
        document.resolved_storage_path,
        exclude_document_id=document.id,
    ).exists()
    if not other_uses:
        if default_storage.exists(file_path):
            default_storage.delete(file_path)

    # 3. Delete from Relational DB
    document.delete()

    return Response(
        {"message": f"Document '{filename}' deleted successfully"},
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
def get_history(request):
    session_name = request.GET.get("session")
    
    try:
        session = get_or_create_session(session_name)
        questions = session.questions.all().order_by("created_at")
        
        history = []
        for q in questions:
            history.append({
                "role": "user",
                "text": q.text,
            })
            # Try to get the answer
            try:
                a = q.answer
                item = {
                    "role": "assistant",
                    "text": a.text,
                    "citations": a.citations
                }
                # Include metadata (comparison, title, etc.)
                if a.metadata:
                    if "claims" in a.metadata:
                        item["comparison"] = a.metadata
                    if "title" in a.metadata:
                        item["title"] = a.metadata["title"]
                    if "suggested_sources" in a.metadata:
                        item["suggestedSources"] = a.metadata.get("suggested_sources", [])
                    if "discovery_mode" in a.metadata:
                        item["discoveryMode"] = a.metadata.get("discovery_mode")
                    if "source_basis" in a.metadata:
                        item["sourceBasis"] = a.metadata.get("source_basis")
                
                history.append(item)
            except Answer.DoesNotExist:
                pass
                
        return Response({"history": history}, status=status.HTTP_200_OK)
    except Session.DoesNotExist:
        return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)
