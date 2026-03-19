import logging

from django.db import transaction

from rag.models import IngestionJob

logger = logging.getLogger(__name__)


def enqueue_job(
    job_type: str,
    *,
    document=None,
    paper_source=None,
    session=None,
    payload=None,
    max_attempts: int = 3,
):
    payload = payload or {}
    session = session or getattr(document, "session", None)

    with transaction.atomic():
        existing = (
            IngestionJob.objects.select_for_update()
            .filter(
                job_type=job_type,
                document=document,
                status__in=["QUEUED", "RUNNING"],
            )
            .order_by("created_at")
            .first()
        )
        if existing:
            if payload and existing.payload != payload:
                existing.payload = payload
                existing.save(update_fields=["payload", "updated_at"])
            return existing, False

        job = IngestionJob.objects.create(
            job_type=job_type,
            document=document,
            paper_source=paper_source,
            session=session,
            payload=payload,
            max_attempts=max_attempts,
        )
        logger.info("Queued ingestion job %s (%s)", job.id, job.job_type)
        return job, True
