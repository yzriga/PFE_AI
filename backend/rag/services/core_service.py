import logging
from typing import Dict, List

import requests
from django.conf import settings

from rag.services.resilience import call_with_resilience, TransientExternalError

logger = logging.getLogger(__name__)


class CoreService:
    BASE_URL = "https://api.core.ac.uk/v3"

    def _safe_request(self, path: str, params: Dict) -> Dict:
        api_key = getattr(settings, "CORE_API_KEY", "")
        if not api_key:
            return {}

        def _request():
            response = requests.get(
                f"{self.BASE_URL}{path}",
                params=params,
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=25,
            )
            if response.status_code == 429:
                raise TransientExternalError("CORE rate limited (429)")
            response.raise_for_status()
            return response.json()

        return call_with_resilience(
            provider="core",
            operation="request",
            func=_request,
            retry_exceptions=(requests.exceptions.RequestException, TransientExternalError),
        )

    def search(self, query: str, max_results: int = 5) -> List[Dict]:
        data = self._safe_request("/search/works", {"q": query, "limit": max_results})
        return [self._extract_metadata(item) for item in data.get("results", [])]

    def lookup_best_fulltext(self, *, doi: str = "", title: str = "") -> Dict:
        if doi:
            results = self.search(f'doi:"{doi}"', max_results=3)
            for item in results:
                if item.get("pdf_url"):
                    return item
        if title:
            results = self.search(title, max_results=3)
            for item in results:
                if item.get("pdf_url"):
                    return item
        return {}

    def _extract_metadata(self, item: Dict) -> Dict:
        authors = item.get("authors") or []
        author_names = []
        for author in authors:
            if isinstance(author, dict):
                name = author.get("name") or author.get("displayName")
                if name:
                    author_names.append(name)
            elif author:
                author_names.append(str(author))
        identifiers = item.get("identifiers") or {}
        doi = identifiers.get("doi") or item.get("doi") or ""
        download_url = item.get("downloadUrl") or item.get("fullTextLink") or item.get("pdfUrl") or ""
        return {
            "external_id": str(item.get("id") or doi or ""),
            "title": item.get("title") or "No Title",
            "authors": author_names,
            "abstract": item.get("abstract") or item.get("description") or "",
            "published_date": item.get("publishedDate") or item.get("year") or "",
            "entry_url": item.get("sourceFulltextUrls", [None])[0] or item.get("url") or "",
            "pdf_url": download_url,
            "doi": doi,
            "source_type": "core",
        }
