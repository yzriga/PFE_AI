import logging
from typing import Dict, Optional

import requests
from django.conf import settings

from rag.services.resilience import call_with_resilience, CircuitOpenError, TransientExternalError

logger = logging.getLogger(__name__)


class DoiLocatorService:
    CROSSREF_BASE = "https://api.crossref.org/works"
    UNPAYWALL_BASE = "https://api.unpaywall.org/v2"

    def _safe_request(self, provider: str, url: str, params: Optional[Dict] = None) -> Dict:
        def _request():
            response = requests.get(url, params=params or {}, timeout=20)
            if response.status_code == 429:
                raise TransientExternalError(f"{provider} rate limited (429)")
            response.raise_for_status()
            return response.json()

        return call_with_resilience(
            provider=provider,
            operation="request",
            func=_request,
            retry_exceptions=(requests.exceptions.RequestException, TransientExternalError),
        )

    def lookup_crossref(self, doi: str) -> Dict:
        doi = (doi or "").strip()
        if not doi:
            return {}
        try:
            data = self._safe_request("crossref", f"{self.CROSSREF_BASE}/{doi}")
        except CircuitOpenError:
            raise
        message = data.get("message", {})
        links = message.get("link", []) or []
        pdf_url = ""
        for link in links:
            if "pdf" in (link.get("content-type") or "").lower():
                pdf_url = link.get("URL") or ""
                break
        return {
            "doi": doi,
            "title": ((message.get("title") or [""]) or [""])[0],
            "pdf_url": pdf_url,
            "entry_url": message.get("URL") or "",
        }

    def lookup_unpaywall(self, doi: str) -> Dict:
        doi = (doi or "").strip()
        if not doi:
            return {}
        email = getattr(settings, "UNPAYWALL_EMAIL", "")
        if not email:
            return {}
        try:
            data = self._safe_request(
                "unpaywall",
                f"{self.UNPAYWALL_BASE}/{doi}",
                params={"email": email},
            )
        except CircuitOpenError:
            raise
        best = data.get("best_oa_location") or {}
        return {
            "doi": doi,
            "pdf_url": best.get("url_for_pdf") or "",
            "entry_url": best.get("url") or data.get("doi_url") or "",
        }

    def locate_pdf(self, doi: str) -> Dict:
        if not doi:
            return {}
        crossref = {}
        unpaywall = {}
        try:
            crossref = self.lookup_crossref(doi)
        except Exception as exc:
            logger.warning("Crossref lookup failed for DOI %s: %s", doi, exc)
        try:
            unpaywall = self.lookup_unpaywall(doi)
        except Exception as exc:
            logger.warning("Unpaywall lookup failed for DOI %s: %s", doi, exc)
        return {
            "pdf_url": unpaywall.get("pdf_url") or crossref.get("pdf_url") or "",
            "entry_url": unpaywall.get("entry_url") or crossref.get("entry_url") or "",
        }
