"""
arXiv Connector Service

Provides functionality to:
- Search papers on arXiv
- Fetch metadata for specific papers
- Download PDFs
- Import papers into the system with proper metadata tracking
"""

import logging
from typing import List, Dict, Optional

import arxiv

from rag.models import PaperSource, Document, Session
from rag.services.job_queue import enqueue_job
from rag.services.resilience import call_with_resilience, CircuitOpenError
from rag.utils import normalize_filename

logger = logging.getLogger(__name__)


class ArxivService:
    """Service for interacting with arXiv API and importing papers."""

    def __init__(self):
        # Configure client with conservative rate limits to avoid 429
        self.client = arxiv.Client(
            page_size=10,
            delay_seconds=3.0,
            num_retries=5
        )
    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search arXiv for papers matching the query.
        """
        logger.info(f"Searching arXiv: query='{query}', max_results={max_results}")

        def _search():
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending
            )

            results = []
            for paper in self.client.results(search):
                results.append(self._extract_metadata(paper))

            logger.info(f"Found {len(results)} papers on arXiv")
            return results

        try:
            return call_with_resilience(
                provider="arxiv",
                operation="search",
                func=_search,
                retry_exceptions=(Exception,),
            )
        except CircuitOpenError:
            raise
        except Exception as e:
            logger.error(f"arXiv search failed: {e}")
            raise

    def fetch_metadata(self, arxiv_id: str) -> Dict:
        """
        Fetch metadata for a specific arXiv paper.
        """
        logger.info(f"Fetching metadata for arXiv:{arxiv_id}")

        def _fetch():
            search = arxiv.Search(id_list=[arxiv_id])
            paper = next(self.client.results(search))

            metadata = self._extract_metadata(paper)
            logger.info(f"Retrieved metadata for '{metadata['title'][:50]}...'")
            return metadata

        try:
            return call_with_resilience(
                provider="arxiv",
                operation="fetch_metadata",
                func=_fetch,
                retry_exceptions=(Exception,),
            )
        except StopIteration:
            logger.error(f"arXiv paper not found: {arxiv_id}")
            raise ValueError(f"Paper with arXiv ID '{arxiv_id}' not found")
        except Exception as e:
            logger.error(f"Failed to fetch arXiv metadata: {e}")
            raise

    def import_paper(
        self,
        arxiv_id: str,
        session_name: str,
        download_pdf: bool = True
    ) -> Dict:
        """
        Import an arXiv paper into the system.
        """
        try:
            # 1. Fetch metadata
            metadata = self.fetch_metadata(arxiv_id)
            
            # Resolve session
            session = Session.objects.get(name=session_name)
            
            # 2. Check if already exists in this session
            safe_filename = normalize_filename(f"{arxiv_id.replace('/', '_')}.pdf")
            document, created = Document.objects.get_or_create(
                filename=safe_filename,
                session=session,
                defaults={"storage_path": f"pdfs/{safe_filename}", "status": "QUEUED"},
            )
            if document.storage_path != f"pdfs/{safe_filename}":
                document.storage_path = f"pdfs/{safe_filename}"
            document.status = "QUEUED"
            document.error_message = None
            document.processing_started_at = None
            document.processing_completed_at = None
            document.save(
                update_fields=[
                    "storage_path",
                    "status",
                    "error_message",
                    "processing_started_at",
                    "processing_completed_at",
                ]
            )
            
            # 3. Create/Update PaperSource
            paper_source, ps_created = PaperSource.objects.get_or_create(
                source_type='arxiv',
                external_id=arxiv_id,
                defaults={
                    'title': metadata['title'],
                    'authors': ", ".join(metadata['authors']),
                    'abstract': metadata['abstract'],
                    'published_date': datetime.strptime(metadata['published_date'], "%Y-%m-%d").date() if metadata['published_date'] else None,
                    'pdf_url': metadata['pdf_url'],
                    'entry_url': metadata['entry_url'],
                    'document': document
                }
            )
            
            if not ps_created:
                paper_source.document = document
                paper_source.save()

            job = None
            if download_pdf:
                job, _ = enqueue_job(
                    "ARXIV_IMPORT",
                    document=document,
                    paper_source=paper_source,
                    session=session,
                    payload={
                        "arxiv_id": arxiv_id,
                        "storage_path": document.storage_path,
                    },
                )

            return {
                "success": True,
                "paper_source_id": paper_source.id,
                "document_id": document.id,
                "arxiv_id": arxiv_id,
                "title": metadata['title'],
                "status": document.status,
                "job_id": job.id if job else None,
                "message": "Paper import queued" if job else "Paper import metadata saved"
            }

        except Exception as e:
            logger.error(f"Import failed for {arxiv_id}: {e}")
            raise

    def _extract_metadata(self, paper: arxiv.Result) -> Dict:
        """Helper to convert arXiv Result into a dict."""
        arxiv_id = paper.get_short_id()
        return {
            "arxiv_id": arxiv_id,
            "external_id": arxiv_id,
            "title": paper.title,
            "authors": [a.name for a in paper.authors],
            "abstract": paper.summary,
            "published_date": paper.published.strftime("%Y-%m-%d"),
            "pdf_url": paper.pdf_url,
            "entry_url": paper.entry_id,  # entry_id is the canonical URL in the library
            "categories": paper.categories,
            "primary_category": paper.primary_category,
            "source_type": "arxiv",
        }

from datetime import datetime
