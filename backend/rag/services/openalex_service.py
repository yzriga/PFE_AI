import logging
import re
from typing import Dict, List

import requests
from django.conf import settings

from rag.services.arxiv_service import ArxivService
from rag.services.import_utils import looks_like_pdf_url
from rag.services.import_utils import queue_remote_import
from rag.services.core_service import CoreService
from rag.services.doi_locator_service import DoiLocatorService
from rag.services.resilience import call_with_resilience, CircuitOpenError, TransientExternalError

logger = logging.getLogger(__name__)


class OpenAlexService:
    BASE_URL = "https://api.openalex.org"

    def __init__(self):
        self.core_service = CoreService()
        self.doi_locator = DoiLocatorService()
        self.arxiv = ArxivService()

    def _safe_request(self, path_or_url: str, params: Dict | None = None) -> Dict:
        url = path_or_url if path_or_url.startswith("http") else f"{self.BASE_URL}{path_or_url}"
        query = dict(params or {})
        mailto = getattr(settings, "OPENALEX_MAILTO", "")
        if mailto:
            query.setdefault("mailto", mailto)
        api_key = getattr(settings, "OPENALEX_API_KEY", "")
        if api_key:
            query.setdefault("api_key", api_key)

        def _request():
            response = requests.get(url, params=query, timeout=25)
            if response.status_code == 429:
                raise TransientExternalError("OpenAlex rate limited (429)")
            response.raise_for_status()
            return response.json()

        return call_with_resilience(
            provider="openalex",
            operation="request",
            func=_request,
            retry_exceptions=(requests.exceptions.RequestException, TransientExternalError),
        )

    def search(self, query: str, max_results: int = 10, *, prefer_content: bool = False) -> List[Dict]:
        params = {"search": query, "per-page": max_results}
        if prefer_content:
            params["filter"] = "has_content.pdf:true"
        data = self._safe_request("/works", params)
        return [self._extract_metadata(work) for work in data.get("results", [])]

    def fetch_metadata(self, work_id: str) -> Dict:
        data = self._safe_request(f"/works/{self._normalize_id(work_id)}")
        return self._extract_metadata(data)

    def resolve_best_match(
        self,
        *,
        title: str = "",
        arxiv_id: str = "",
        doi: str = "",
    ) -> Dict:
        candidate_queries = []
        if doi:
            candidate_queries.append(doi)
        if arxiv_id:
            candidate_queries.append(arxiv_id)
        if title:
            candidate_queries.append(title)

        best = {}
        best_score = -1.0
        for query in candidate_queries:
            if not query:
                continue
            for item in self.search(query, max_results=5, prefer_content=False):
                score = self._match_score(item, title=title, arxiv_id=arxiv_id, doi=doi)
                if score > best_score:
                    best_score = score
                    best = item
        return best if best_score >= 0.45 else {}

    def fetch_paper_graph(self, work_id: str, limit: int = 6) -> Dict:
        work = self._safe_request(f"/works/{self._normalize_id(work_id)}")
        paper = self._extract_metadata(work)
        references = [self.fetch_metadata(ref_id) for ref_id in (work.get("referenced_works") or [])[:limit]]
        citations = [
            self._extract_metadata(item)
            for item in self._safe_request(work.get("cited_by_api_url") or f"/works/{self._normalize_id(work_id)}/citations", {"per-page": limit}).get("results", [])[:limit]
        ] if (work.get("cited_by_api_url") or "") else []
        related = [self.fetch_metadata(rel_id) for rel_id in (work.get("related_works") or [])[:limit]]
        return {
            "paper": self._to_graph_item(paper, "seed"),
            "references": [self._to_graph_item(item, "reference") for item in references if item.get("external_id")],
            "citations": [self._to_graph_item(item, "citation") for item in citations if item.get("external_id")],
            "related": [self._to_graph_item(item, "related") for item in related if item.get("external_id")],
            "graph_source": "openalex",
        }

    def import_paper(self, work_id: str, session_name: str) -> Dict:
        metadata = self.fetch_metadata(work_id)
        pdf_url = self._resolve_fulltext_url(metadata)
        return queue_remote_import(
            session_name=session_name,
            source_type="openalex",
            external_id=metadata["external_id"],
            metadata=metadata,
            pdf_url=pdf_url,
            filename_prefix="openalex",
        )

    def _resolve_fulltext_url(self, metadata: Dict) -> str:
        content_url = self._content_download_url(metadata)
        if content_url:
            return content_url
        doi = metadata.get("doi") or ""
        title = metadata.get("title") or ""
        arxiv_id = metadata.get("arxiv_id") or ""
        if arxiv_id:
            try:
                arxiv_metadata = self.arxiv.fetch_metadata(arxiv_id)
                if arxiv_metadata.get("pdf_url"):
                    return arxiv_metadata["pdf_url"]
            except Exception as exc:
                logger.warning("arXiv resolution failed for %s: %s", arxiv_id, exc)
        core_hit = self.core_service.lookup_best_fulltext(doi=doi, title=title)
        if core_hit.get("pdf_url"):
            return core_hit["pdf_url"]
        doi_hit = self.doi_locator.locate_pdf(doi)
        if doi_hit.get("pdf_url"):
            metadata["entry_url"] = doi_hit.get("entry_url") or metadata.get("entry_url", "")
            return doi_hit["pdf_url"]
        return metadata.get("pdf_url") or ""

    def _content_download_url(self, metadata: Dict) -> str:
        content_url = metadata.get("content_url") or ""
        api_key = getattr(settings, "OPENALEX_API_KEY", "")
        if not content_url or not api_key or not metadata.get("has_content_pdf"):
            return ""
        return f"{content_url}.pdf?api_key={api_key}"

    def _normalize_id(self, work_id: str) -> str:
        work_id = (work_id or "").strip()
        return work_id.rsplit("/", 1)[-1]

    def _match_score(self, item: Dict, *, title: str = "", arxiv_id: str = "", doi: str = "") -> float:
        score = 0.0
        if doi and item.get("doi") and item.get("doi").lower() == doi.lower():
            score += 5.0
        if arxiv_id and item.get("arxiv_id") and item.get("arxiv_id").lower() == arxiv_id.lower():
            score += 5.0
        if title:
            query_tokens = set(re.findall(r"[a-z0-9]+", title.lower()))
            item_tokens = set(re.findall(r"[a-z0-9]+", (item.get("title") or "").lower()))
            if query_tokens:
                overlap = len(query_tokens & item_tokens) / max(1, len(query_tokens))
                score += overlap * 2.0
                if (item.get("title") or "").strip().lower() == title.strip().lower():
                    score += 2.0
        return score

    def _extract_metadata(self, work: Dict) -> Dict:
        authors = []
        for authorship in work.get("authorships", []) or []:
            author = authorship.get("author") or {}
            name = author.get("display_name")
            if name:
                authors.append(name)
        best_location = work.get("best_oa_location") or {}
        primary_location = work.get("primary_location") or {}
        pdf_url = (
            best_location.get("pdf_url")
            or (primary_location.get("pdf_url") if isinstance(primary_location, dict) else "")
            or ""
        )
        if not looks_like_pdf_url(pdf_url):
            pdf_url = ""
        doi = work.get("doi") or ""
        ids = work.get("ids") or {}
        arxiv_id = ids.get("arxiv") or ""
        if arxiv_id:
            arxiv_id = arxiv_id.rsplit("/", 1)[-1]
        return {
            "external_id": self._normalize_id(work.get("id", "")),
            "title": work.get("display_name") or "No Title",
            "authors": authors,
            "abstract": self._reconstruct_abstract(work.get("abstract_inverted_index") or {}),
            "published_date": str(work.get("publication_year") or ""),
            "entry_url": ((primary_location.get("landing_page_url") if isinstance(primary_location, dict) else "") or work.get("id") or ""),
            "pdf_url": pdf_url,
            "doi": doi.replace("https://doi.org/", "") if doi else "",
            "content_url": work.get("content_url") or "",
            "has_content_pdf": bool((work.get("has_content") or {}).get("pdf")),
            "arxiv_id": arxiv_id,
            "source_type": "openalex",
        }

    def _reconstruct_abstract(self, inverted_index: Dict) -> str:
        if not inverted_index:
            return ""
        max_pos = max((max(positions) for positions in inverted_index.values() if positions), default=-1)
        tokens = [""] * (max_pos + 1)
        for word, positions in inverted_index.items():
            for pos in positions:
                if 0 <= pos < len(tokens):
                    tokens[pos] = word
        return " ".join(token for token in tokens if token).strip()

    def _to_graph_item(self, item: Dict, relationship: str) -> Dict:
        provider = "arxiv" if item.get("arxiv_id") else item.get("source_type", "openalex")
        import_id = item.get("arxiv_id") or item.get("external_id")
        return {
            "id": import_id,
            "external_id": item.get("external_id"),
            "title": item.get("title"),
            "authors": item.get("authors", []),
            "year": item.get("published_date"),
            "url": item.get("entry_url"),
            "abstract": item.get("abstract"),
            "provider": provider,
            "relationship": relationship,
        }
