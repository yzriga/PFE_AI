"""
PubMed Connector Service

Uses Biopython's Entrez module to search and fetch metadata from PubMed (MEDLINE).
"""

import logging
from datetime import datetime
from typing import List, Dict, Optional

from Bio import Entrez
from django.conf import settings

from rag.models import PaperSource, Document, Session
from rag.services.job_queue import enqueue_job
from rag.services.resilience import call_with_resilience, CircuitOpenError
from rag.utils import normalize_filename

logger = logging.getLogger(__name__)

# Entrez requires an email
Entrez.email = "your-email@example.com"


class PubmedService:
    """Service for interacting with PubMed API."""

    def __init__(self):
        # Built-in Entrez retry controls.
        Entrez.max_tries = max(2, int(getattr(settings, "EXTERNAL_API_RETRIES", 3)))
        Entrez.sleep_between_tries = float(
            getattr(settings, "EXTERNAL_API_RETRY_BACKOFF_SECONDS", 1.0)
        )

    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search PubMed for papers matching the query.
        """
        logger.info(f"Searching PubMed: query='{query}', max_results={max_results}")

        def _search():
            # Step 1: Search IDs
            handle = Entrez.esearch(db="pubmed", term=query, retmax=max_results)
            record = Entrez.read(handle)
            handle.close()

            id_list = record["IdList"]
            if not id_list:
                return []

            # Step 2: Fetch Summary
            handle = Entrez.esummary(db="pubmed", id=",".join(id_list))
            summaries = Entrez.read(handle)
            handle.close()

            results = []
            for summary in summaries:
                results.append(self._extract_metadata(summary))

            return results

        try:
            return call_with_resilience(
                provider="pubmed",
                operation="search",
                func=_search,
                retry_exceptions=(Exception,),
            )
        except CircuitOpenError:
            raise
        except Exception as e:
            logger.error(f"PubMed search failed: {e}")
            raise

    def fetch_metadata(self, pubmed_id: str) -> Dict:
        """Fetch full details for a single paper."""
        def _fetch():
            handle = Entrez.esummary(db="pubmed", id=pubmed_id)
            records = Entrez.read(handle)
            handle.close()
            
            if not records:
                raise ValueError(f"PubMed ID {pubmed_id} not found")
            return self._extract_metadata(records[0])

        try:
            return call_with_resilience(
                provider="pubmed",
                operation="fetch_metadata",
                func=_fetch,
                retry_exceptions=(Exception,),
            )
        except Exception as e:
            logger.error(f"Failed to fetch PubMed metadata: {e}")
            raise

    def import_paper(self, pubmed_id: str, session_name: str) -> Dict:
        """Import a PubMed paper by finding its PDF (via PMC)."""
        try:
            metadata = self.fetch_metadata(pubmed_id)
            session = Session.objects.get(name=session_name)
            
            # 1. Try to find the PDF URL (PubMed doesn't give direct PDFs usually) 
            # We'll use the LinkOut or PMC if available
            safe_filename = normalize_filename(f"pubmed_{pubmed_id}.pdf")
            document, created = Document.objects.get_or_create(
                filename=safe_filename, 
                session=session,
                defaults={
                    'title': metadata['title'],
                    'abstract': metadata['abstract'],
                    'status': 'QUEUED'
                }
            )
            
            if not created:
                document.status = 'QUEUED'
                document.title = metadata['title']
                document.abstract = metadata['abstract']
                document.error_message = None
                document.processing_started_at = None
                document.processing_completed_at = None
                document.save(update_fields=["status", "title", "abstract", "error_message", "processing_started_at", "processing_completed_at"])
            
            paper_source, _ = PaperSource.objects.get_or_create(
                source_type='pubmed',
                external_id=pubmed_id,
                defaults={
                    'title': metadata['title'],
                    'authors': ", ".join(metadata['authors']),
                    'abstract': metadata['abstract'],
                    'entry_url': metadata['entry_url'],
                    'document': document
                }
            )
            job, _ = enqueue_job(
                "PUBMED_IMPORT",
                document=document,
                paper_source=paper_source,
                session=session,
                payload={"metadata": metadata},
            )

            return {
                "success": True,
                "message": "Import queued (summary-only mode)",
                "document_id": document.id,
                "paper_source_id": paper_source.id,
                "job_id": job.id,
                "status": document.status,
            }

        except Exception as e:
            logger.error(f"Import failed: {e}")
            raise

    def _extract_metadata(self, summary: Dict) -> Dict:
        """Helper to convert PubMed summary to unified dict."""
        # PubMed summary fields vary, we extract safely
        pmid = summary.get("Id", "")
        title = summary.get("Title", "No Title")
        
        # Authors list
        authors_raw = summary.get("Authors", [])
        authors = authors_raw if isinstance(authors_raw, list) else [authors_raw]
        
        return {
            "external_id": pmid,
            "title": title,
            "authors": authors,
            "abstract": summary.get("FullJournalName", ""), # PubMed Summary doesn't have the full abstract, requires efetch
            "published_date": summary.get("PubDate", ""),
            "entry_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "source_type": "pubmed"
        }
