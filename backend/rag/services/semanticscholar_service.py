import logging
import requests
from datetime import datetime
from typing import List, Dict

from rag.services.job_queue import enqueue_job
from rag.services.resilience import (
    call_with_resilience,
    CircuitOpenError,
    TransientExternalError,
)

logger = logging.getLogger(__name__)

class SemanticScholarService:
    """Service for interacting with Semantic Scholar API."""

    BASE_URL = "https://api.semanticscholar.org/graph/v1"

    @staticmethod
    def _safe_text(value, default: str = "") -> str:
        """Normalize provider strings because Semantic Scholar often returns explicit nulls."""
        if value is None:
            return default
        return str(value).strip()

    def _safe_request(self, url: str, params: Dict) -> Dict:
        """Semantic Scholar request with retry and circuit breaker."""

        def _request() -> Dict:
            response = requests.get(url, params=params, timeout=20)
            if response.status_code == 429:
                raise TransientExternalError("Semantic Scholar rate limited (429)")
            response.raise_for_status()
            return response.json()

        try:
            return call_with_resilience(
                provider="semanticscholar",
                operation="request",
                func=_request,
                retry_exceptions=(
                    requests.exceptions.RequestException,
                    TransientExternalError,
                ),
            )
        except CircuitOpenError:
            raise


    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search Semantic Scholar.
        """
        logger.info(f"Searching Semantic Scholar: query='{query}'")

        try:
            url = f"{self.BASE_URL}/paper/search"
            params = {
                "query": query,
                "limit": max_results,
                "fields": "title,authors,abstract,url,year,externalIds,openAccessPdf"
            }
            
            data = self._safe_request(url, params)
            results = []
            for paper in data.get("data", []):
                results.append(self._extract_metadata(paper))

            return results

        except Exception as e:
            logger.error(f"Semantic Scholar search failed: {e}")
            raise

    def fetch_metadata(self, paper_id: str) -> Dict:
        """Fetch metadata for a specific paper."""
        url = f"{self.BASE_URL}/paper/{paper_id}"
        params = {"fields": "title,authors,abstract,url,year,externalIds,openAccessPdf"}
        data = self._safe_request(url, params)
        return self._extract_metadata(data)

    def fetch_paper_graph(self, paper_id: str, limit: int = 6) -> Dict:
        url = f"{self.BASE_URL}/paper/{paper_id}"
        params = {
            "fields": (
                "paperId,title,authors,abstract,url,year,externalIds,openAccessPdf,"
                "references.paperId,references.title,references.authors,references.year,references.url,references.abstract,"
                "citations.paperId,citations.title,citations.authors,citations.year,citations.url,citations.abstract"
            )
        }
        data = self._safe_request(url, params)
        paper = self._extract_metadata(data)
        references = self._extract_graph_items(data.get("references", []), relationship="reference")[:limit]
        citations = self._extract_graph_items(data.get("citations", []), relationship="citation")[:limit]
        related = self._derive_related_papers(paper_id, paper.get("title", ""), limit=limit)
        return {
            "paper": {
                "id": paper.get("external_id"),
                "title": paper.get("title"),
                "authors": paper.get("authors", []),
                "year": paper.get("published_date"),
                "url": paper.get("entry_url"),
                "abstract": paper.get("abstract"),
                "provider": paper.get("source_type", "semanticscholar"),
            },
            "references": references,
            "citations": citations,
            "related": related,
            "graph_source": "semanticscholar",
        }

    def import_paper(self, paper_id: str, session_name: str, source_type: str = 'doi') -> Dict:
        """Import from Semantic Scholar with PDF fallback to Abstract."""
        from rag.models import Session, Document, PaperSource
        from rag.utils import normalize_filename

        try:
            metadata = self.fetch_metadata(paper_id)
            session = Session.objects.get(name=session_name)
            
            pdf_url = metadata.get('pdf_url')
            safe_filename = normalize_filename(f"scholar_{paper_id[:8]}.pdf" if pdf_url else f"scholar_{paper_id[:8]}_abstract.txt")
            
            document, created = Document.objects.get_or_create(
                filename=safe_filename, 
                session=session,
                defaults={
                    'storage_path': f"pdfs/{safe_filename}" if pdf_url else None,
                    'status': 'QUEUED',
                    'title': metadata['title'],
                    'abstract': metadata['abstract'],
                }
            )
            
            if not created:
                if pdf_url:
                    document.storage_path = f"pdfs/{safe_filename}"
                document.status = 'QUEUED'
                document.title = metadata['title']
                document.abstract = metadata['abstract']
                document.error_message = None
                document.processing_started_at = None
                document.processing_completed_at = None
                update_fields = ["status", "title", "abstract", "error_message", "processing_started_at", "processing_completed_at"]
                if pdf_url:
                    update_fields.append("storage_path")
                document.save(update_fields=update_fields)
            
            published_date = None
            year_text = self._safe_text(metadata.get("published_date"))
            if year_text and year_text.isdigit():
                published_date = datetime(int(year_text), 1, 1).date()

            paper_source, paper_source_created = PaperSource.objects.get_or_create(
                source_type=source_type,
                external_id=paper_id,
                defaults={
                    'title': metadata['title'],
                    'authors': ", ".join(metadata['authors']),
                    'abstract': metadata['abstract'],
                    'published_date': published_date,
                    'pdf_url': pdf_url or "",
                    'entry_url': metadata.get("entry_url", ""),
                    'document': document
                }
            )
            if not paper_source_created:
                paper_source.title = metadata["title"]
                paper_source.authors = ", ".join(metadata["authors"])
                paper_source.abstract = metadata["abstract"]
                paper_source.published_date = published_date
                paper_source.pdf_url = pdf_url or ""
                paper_source.entry_url = metadata.get("entry_url", "")
                paper_source.document = document
                paper_source.save()
            job, _ = enqueue_job(
                "SEMANTIC_SCHOLAR_IMPORT",
                document=document,
                paper_source=paper_source,
                session=session,
                payload={
                    "metadata": metadata,
                    "pdf_url": pdf_url,
                    "source_type": source_type,
                    "storage_path": document.storage_path,
                },
            )
            return {
                "success": True,
                "message": "Import queued (summary fallback enabled)",
                "document_id": document.id,
                "paper_source_id": paper_source.id,
                "job_id": job.id,
                "status": document.status,
            }

        except Exception as e:
            logger.error(f"Scholar import failed: {e}")
            raise

    def _extract_metadata(self, paper: Dict) -> Dict:
        """Unified dictionary structure."""
        authors = [
            self._safe_text(a.get("name"))
            for a in paper.get("authors", [])
            if self._safe_text(a.get("name"))
        ]
        pdf_info = paper.get("openAccessPdf")
        pdf_url = pdf_info.get("url") if pdf_info else None
        
        return {
            "external_id": self._safe_text(paper.get("paperId")),
            "title": self._safe_text(paper.get("title"), "No Title"),
            "authors": authors,
            "abstract": self._safe_text(paper.get("abstract"), "No abstract available."),
            "published_date": self._safe_text(paper.get("year"), ""),
            "entry_url": self._safe_text(paper.get("url")),
            "pdf_url": pdf_url,
            "source_type": "semanticscholar"
        }

    def _extract_graph_items(self, entries: List[Dict], relationship: str) -> List[Dict]:
        items = []
        for entry in entries or []:
            node = (
                entry.get("citedPaper")
                or entry.get("citingPaper")
                or entry.get("referencedPaper")
                or entry
            )
            metadata = self._extract_metadata(node)
            if not metadata.get("external_id") or not metadata.get("title"):
                continue
            items.append(
                {
                    "id": metadata.get("external_id"),
                    "title": metadata.get("title"),
                    "authors": metadata.get("authors", []),
                    "year": metadata.get("published_date"),
                    "url": metadata.get("entry_url"),
                    "abstract": metadata.get("abstract"),
                    "provider": metadata.get("source_type", "semanticscholar"),
                    "relationship": relationship,
                }
            )
        return items

    def _derive_related_papers(self, paper_id: str, title: str, limit: int = 6) -> List[Dict]:
        if not title:
            return []
        related = []
        for item in self.search(title, max_results=limit + 3):
            if item.get("external_id") == paper_id:
                continue
            related.append(
                {
                    "id": item.get("external_id"),
                    "title": item.get("title"),
                    "authors": item.get("authors", []),
                    "year": item.get("published_date"),
                    "url": item.get("entry_url"),
                    "abstract": item.get("abstract"),
                    "provider": item.get("source_type", "semanticscholar"),
                    "relationship": "related_search",
                }
            )
            if len(related) >= limit:
                break
        return related

