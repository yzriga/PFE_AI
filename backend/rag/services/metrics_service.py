"""
MetricsService - Logging and monitoring for RAG queries

Responsibilities:
- Log every query execution with performance metrics
- Track retrieved chunks with relevance scores
- Capture errors for debugging
- Provide aggregated metrics for dashboard

Usage:
    service = MetricsService()
    
    # During query execution:
    log_entry = service.log_query(
        session=session,
        question_text="What is...",
        mode="qa",
        sources=["paper1.pdf"],
        latency_ms=523,
        retrieved_chunks=[...],
        error=None
    )
    
    # For dashboard:
    summary = service.get_summary(since_days=7)
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from django.db.models import Avg, Count, Q
from django.utils import timezone

from rag.models import RunLog, Session, Question

logger = logging.getLogger(__name__)


class MetricsService:
    """Service for logging RAG queries and generating performance metrics."""
    
    def log_query(
        self,
        session: Session,
        question_text: str,
        mode: str,
        sources: List[str],
        latency_ms: int,
        retrieved_chunks: List[dict],
        question: Optional[Question] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        error: Optional[Exception] = None
    ) -> RunLog:
        """
        Log a RAG query execution.
        
        Args:
            session: Session in which query was executed
            question_text: The question asked
            mode: RAG mode (qa, compare, lit_review)
            sources: List of document filenames used (empty = all)
            latency_ms: End-to-end latency in milliseconds
            retrieved_chunks: List of chunks with metadata
            question: Question model instance (if created)
            prompt_tokens: Number of tokens in prompt (if tracked)
            completion_tokens: Number of tokens in completion (if tracked)
            error: Exception if query failed
        
        Returns:
            Created RunLog instance
        
        Example retrieved_chunks format:
            [
                {
                    "doc": "paper1.pdf",
                    "page": 5,
                    "chunk_id": "chunk_42",
                    "score": 0.87,
                    "text_preview": "First 100 chars..."
                },
                ...
            ]
        """
        error_type = None
        error_message = None
        
        if error:
            error_type = type(error).__name__
            error_message = str(error)
            logger.error(
                f"Query failed: {error_type} - {error_message}",
                exc_info=error
            )
        
        log_entry = RunLog.objects.create(
            session=session,
            question=question,
            question_text=question_text,
            mode=mode,
            sources=sources,
            latency_ms=latency_ms,
            retrieved_chunks=retrieved_chunks,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            error_type=error_type,
            error_message=error_message
        )
        
        logger.info(
            f"Logged query [{mode}] in session '{session.name}': "
            f"{latency_ms}ms, {len(retrieved_chunks)} chunks"
        )
        
        return log_entry
    
    def get_summary(self, since_days: int = 7) -> dict:
        """
        Get aggregated metrics for dashboard.
        
        Args:
            since_days: Number of days to look back (default: 7)
        
        Returns:
            Dict with metrics:
            {
                "period": {"start": "...", "end": "...", "days": 7},
                "queries": {
                    "total": 150,
                    "by_mode": {"qa": 100, "compare": 30, "lit_review": 20},
                    "latency_p50": 523,
                    "latency_p95": 1240,
                    "latency_avg": 612
                },
                "errors": {
                    "count": 5,
                    "rate": 0.033,  # 3.3%
                    "top_errors": [
                        {"type": "ChromaConnectionError", "count": 3},
                        {"type": "TimeoutError", "count": 2}
                    ]
                },
                "retrieval": {
                    "avg_chunks_per_query": 5.2,
                    "avg_score": 0.78
                },
                "sessions": {
                    "active_count": 12
                }
            }
        """
        since = timezone.now() - timedelta(days=since_days)
        logs = RunLog.objects.filter(created_at__gte=since)
        
        # Total queries
        total_queries = logs.count()
        
        if total_queries == 0:
            return self._empty_summary(since_days)
        
        # Queries by mode
        mode_counts = logs.values('mode').annotate(count=Count('id'))
        by_mode = {item['mode']: item['count'] for item in mode_counts}
        
        # Latency statistics
        latencies = list(logs.values_list('latency_ms', flat=True))
        latencies.sort()
        
        latency_avg = sum(latencies) // len(latencies)
        latency_p50 = self._percentile(latencies, 50)
        latency_p95 = self._percentile(latencies, 95)
        
        # Error tracking
        error_logs = logs.exclude(error_type__isnull=True)
        error_count = error_logs.count()
        error_rate = error_count / total_queries if total_queries > 0 else 0
        
        top_errors = (
            error_logs.values('error_type')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )
        top_errors_list = [
            {"type": item['error_type'], "count": item['count']}
            for item in top_errors
        ]
        
        # Retrieval statistics
        total_chunks = sum(len(log.retrieved_chunks) for log in logs)
        avg_chunks = total_chunks / total_queries if total_queries > 0 else 0
        
        # Calculate average relevance score
        all_scores = []
        for log in logs:
            for chunk in log.retrieved_chunks:
                if 'score' in chunk:
                    all_scores.append(chunk['score'])
        
        avg_score = sum(all_scores) / len(all_scores) if all_scores else 0
        
        # Active sessions
        active_sessions = logs.values('session').distinct().count()
        
        return {
            "period": {
                "start": since.isoformat(),
                "end": timezone.now().isoformat(),
                "days": since_days
            },
            "queries": {
                "total": total_queries,
                "by_mode": by_mode,
                "latency_avg": latency_avg,
                "latency_p50": latency_p50,
                "latency_p95": latency_p95
            },
            "errors": {
                "count": error_count,
                "rate": round(error_rate, 3),
                "top_errors": top_errors_list
            },
            "retrieval": {
                "avg_chunks_per_query": round(avg_chunks, 1),
                "avg_score": round(avg_score, 3)
            },
            "sessions": {
                "active_count": active_sessions
            }
        }
    
    def _percentile(self, sorted_values: List[int], percentile: int) -> int:
        """Calculate percentile from sorted list."""
        if not sorted_values:
            return 0
        
        index = (len(sorted_values) - 1) * percentile / 100
        floor = int(index)
        ceil = floor + 1
        
        if ceil >= len(sorted_values):
            return sorted_values[-1]
        
        # Linear interpolation
        fraction = index - floor
        return int(sorted_values[floor] + fraction * (sorted_values[ceil] - sorted_values[floor]))
    
    def _empty_summary(self, since_days: int) -> dict:
        """Return empty summary when no data available."""
        since = timezone.now() - timedelta(days=since_days)
        
        return {
            "period": {
                "start": since.isoformat(),
                "end": timezone.now().isoformat(),
                "days": since_days
            },
            "queries": {
                "total": 0,
                "by_mode": {},
                "latency_avg": 0,
                "latency_p50": 0,
                "latency_p95": 0
            },
            "errors": {
                "count": 0,
                "rate": 0,
                "top_errors": []
            },
            "retrieval": {
                "avg_chunks_per_query": 0,
                "avg_score": 0
            },
            "sessions": {
                "active_count": 0
            }
        }
    
    def get_session_history(self, session: Session, limit: int = 50) -> List[Dict]:
        """
        Get recent query history for a specific session.
        
        Args:
            session: Session to get history for
            limit: Maximum number of logs to return
        
        Returns:
            List of log entries with key fields
        """
        logs = RunLog.objects.filter(session=session).order_by('-created_at')[:limit]
        
        return [
            {
                "id": log.id,
                "question": log.question_text,
                "mode": log.mode,
                "latency_ms": log.latency_ms,
                "chunks_count": len(log.retrieved_chunks),
                "error": log.error_type,
                "created_at": log.created_at.isoformat()
            }
            for log in logs
        ]
