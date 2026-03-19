import logging
from typing import Dict, List

import requests

from rag.services.import_utils import looks_like_pdf_url
from rag.services.import_utils import queue_remote_import
from rag.services.core_service import CoreService
from rag.services.doi_locator_service import DoiLocatorService
from rag.services.resilience import call_with_resilience, TransientExternalError

logger = logging.getLogger(__name__)


class EuropePmcService:
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"

    def __init__(self):
        self.core_service = CoreService()
        self.doi_locator = DoiLocatorService()

    def _safe_request(self, url: str, params: Dict) -> Dict:
        def _request():
            response = requests.get(url, params=params, timeout=25)
            if response.status_code == 429:
                raise TransientExternalError("Europe PMC rate limited (429)")
            response.raise_for_status()
            return response.json()

        return call_with_resilience(
            provider="europepmc",
            operation="request",
            func=_request,
            retry_exceptions=(requests.exceptions.RequestException, TransientExternalError),
        )

    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        data = self._safe_request(
            f"{self.BASE_URL}/search",
            {"query": query, "format": "json", "pageSize": max_results},
        )
        return [self._extract_metadata(item) for item in ((data.get("resultList") or {}).get("result") or [])]

    def fetch_metadata(self, paper_id: str) -> Dict:
        data = self._safe_request(
            f"{self.BASE_URL}/search",
            {"query": f'EXT_ID:{paper_id}', "format": "json", "pageSize": 1},
        )
        results = ((data.get("resultList") or {}).get("result") or [])
        if not results:
            raise ValueError(f"Europe PMC paper '{paper_id}' not found")
        return self._extract_metadata(results[0])

    def import_paper(self, paper_id: str, session_name: str) -> Dict:
        metadata = self.fetch_metadata(paper_id)
        pdf_url = self._resolve_fulltext_url(metadata)
        return queue_remote_import(
            session_name=session_name,
            source_type="europepmc",
            external_id=metadata["external_id"],
            metadata=metadata,
            pdf_url=pdf_url,
            filename_prefix="europepmc",
        )

    def _resolve_fulltext_url(self, metadata: Dict) -> str:
        doi = metadata.get("doi") or ""
        title = metadata.get("title") or ""
        core_hit = self.core_service.lookup_best_fulltext(doi=doi, title=title)
        if core_hit.get("pdf_url"):
            return core_hit["pdf_url"]
        doi_hit = self.doi_locator.locate_pdf(doi)
        if doi_hit.get("pdf_url"):
            metadata["entry_url"] = doi_hit.get("entry_url") or metadata.get("entry_url", "")
            return doi_hit["pdf_url"]
        return metadata.get("pdf_url") or ""

    def _extract_metadata(self, item: Dict) -> Dict:
        doi = item.get("doi") or ""
        pdf_url = item.get("pdfUrl") or item.get("fullTextUrl") or ""
        if not looks_like_pdf_url(pdf_url):
            pdf_url = ""
        authors = [author.strip() for author in (item.get("authorString") or "").split(",") if author.strip()]
        return {
            "external_id": str(item.get("id") or item.get("source") or ""),
            "title": item.get("title") or "No Title",
            "authors": authors,
            "abstract": item.get("abstractText") or "",
            "published_date": str(item.get("pubYear") or ""),
            "entry_url": item.get("fullTextUrl") or item.get("journalUrl") or "",
            "pdf_url": pdf_url,
            "doi": doi,
            "source_type": "europepmc",
        }
