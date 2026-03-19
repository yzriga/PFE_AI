"""
Metrics Service

Logs and aggregates performance and quality metrics for RAG queries,
including grounding / refusal tracking.
"""
from typing import List, Dict, Any, Optional
from django.utils import timezone
from django.db.models import Avg, Count, F
from django.db.models.functions import TruncDate
from datetime import timedelta

from rag.models import RunLog, Session, Question
from rag.utils import sanitize_json_value, sanitize_text


class MetricsService:
    """Service for logging and retrieving system metrics."""

    def log_query(
        self,
        session: Session,
        question_text: str,
        mode: str,
        latency_ms: int,
        retrieved_chunks: List[Dict],
        question: Optional[Question] = None,
        sources: Optional[List[str]] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        error: Optional[Exception] = None,
        # ---- new grounding fields ----
        is_refusal: bool = False,
        is_insufficient_evidence: bool = False,
        retrieved_chunks_count: int = 0,
        confidence_score: Optional[float] = None,
        retrieval_ms: Optional[int] = None,
        generation_ms: Optional[int] = None,
    ) -> RunLog:
        """
        Log a single query execution, including grounding metrics.
        """
        error_type = type(error).__name__ if error else None
        error_message = str(error) if error else None

        log = RunLog.objects.create(
            session=session,
            question=question,
            question_text=sanitize_text(question_text),
            mode=mode,
            sources=sanitize_json_value(sources or []),
            latency_ms=latency_ms,
            retrieved_chunks=sanitize_json_value(retrieved_chunks),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            error_type=error_type,
            error_message=sanitize_text(error_message) if error_message else None,
            # grounding
            is_refusal=is_refusal,
            is_insufficient_evidence=is_insufficient_evidence,
            retrieved_chunks_count=retrieved_chunks_count,
            confidence_score=confidence_score,
            retrieval_ms=retrieval_ms,
            generation_ms=generation_ms,
        )
        return log

    def get_summary(self, since_days: int = 7) -> Dict[str, Any]:
        """
        Aggregate metrics over a period of time.
        Now includes a 'grounding' section with refusal tracking.
        """
        start_date = timezone.now() - timedelta(days=since_days)
        logs = RunLog.objects.filter(created_at__gte=start_date)

        total_queries = logs.count()

        # Base summary structure
        summary = {
            "period": {
                "start": start_date,
                "end": timezone.now(),
                "days": since_days,
            },
            "queries": {
                "total": total_queries,
                "by_mode": {},
                "latency_avg_ms": 0,
                "retrieval_avg_ms": 0,
                "generation_avg_ms": 0,
                "orchestration_avg_ms": 0,
            },
            "errors": {
                "count": 0,
                "rate": 0.0,
                "top_errors": [],
            },
            "sessions": {
                "active_count": Session.objects.filter(
                    run_logs__created_at__gte=start_date
                )
                .distinct()
                .count()
            },
            "grounding": {
                "refusal_count": 0,
                "refusal_rate": 0.0,
                "insufficient_evidence_count": 0,
                "insufficient_evidence_rate": 0.0,
                "avg_retrieved_chunks": 0.0,
                "avg_confidence_score": 0.0,
            },
        }

        if total_queries == 0:
            return summary

        # ---- Query stats ----
        by_mode = logs.values("mode").annotate(count=Count("id"))
        latency_avg = logs.aggregate(avg=Avg("latency_ms"))["avg"]
        retrieval_avg = logs.aggregate(avg=Avg("retrieval_ms"))["avg"]
        generation_avg = logs.aggregate(avg=Avg("generation_ms"))["avg"]

        summary["queries"]["by_mode"] = {
            item["mode"]: item["count"] for item in by_mode
        }
        summary["queries"]["latency_avg_ms"] = int(latency_avg or 0)
        summary["queries"]["retrieval_avg_ms"] = int(retrieval_avg or 0)
        summary["queries"]["generation_avg_ms"] = int(generation_avg or 0)

        breakdown_logs = logs.filter(
            retrieval_ms__isnull=False,
            generation_ms__isnull=False,
        ).values_list("latency_ms", "retrieval_ms", "generation_ms")
        if breakdown_logs:
            orchestration_values = [
                max(0, total - retrieval - generation)
                for total, retrieval, generation in breakdown_logs
            ]
            summary["queries"]["orchestration_avg_ms"] = int(
                sum(orchestration_values) / len(orchestration_values)
            )

        # ---- Error stats ----
        errors = logs.exclude(error_type__isnull=True)
        error_count = errors.count()
        top_errors = (
            errors.values("error_type")
            .annotate(count=Count("id"))
            .order_by("-count")[:5]
        )

        summary["errors"]["count"] = error_count
        summary["errors"]["rate"] = round(error_count / total_queries, 3)
        summary["errors"]["top_errors"] = list(top_errors)

        # ---- Grounding / refusal stats ----
        refusal_count = logs.filter(is_refusal=True).count()
        insufficient_count = logs.filter(is_insufficient_evidence=True).count()
        avg_chunks = logs.aggregate(avg=Avg("retrieved_chunks_count"))["avg"]
        avg_confidence = logs.aggregate(avg=Avg("confidence_score"))["avg"]

        summary["grounding"] = {
            "refusal_count": refusal_count,
            "refusal_rate": round(refusal_count / total_queries, 3),
            "insufficient_evidence_count": insufficient_count,
            "insufficient_evidence_rate": round(
                insufficient_count / total_queries, 3
            ),
            "avg_retrieved_chunks": round(avg_chunks or 0, 1),
            "avg_confidence_score": round(avg_confidence or 0, 4),
        }

        return summary
