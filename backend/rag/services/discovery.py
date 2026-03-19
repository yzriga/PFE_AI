import logging
import re
from typing import Dict, List

from django.core.cache import cache

from rag.router import is_specific_research_question
from rag.services.arxiv_service import ArxivService
from rag.services.openalex_service import OpenAlexService
from rag.services.europepmc_service import EuropePmcService
from rag.services.resilience import CircuitOpenError, TransientExternalError
from rag.services.synthesis import SynthesisService

logger = logging.getLogger(__name__)

DISCOVERY_CACHE_TTL_SECONDS = 60 * 60 * 6
DISCOVERY_PROVIDER_ORDER = ("openalex", "europepmc", "arxiv")
DISCOVERY_STOPWORDS = {
    "a", "an", "and", "architecture", "are", "about", "do", "does", "explain",
    "for", "how", "in", "is", "of", "on", "recent", "say", "the", "to", "used",
    "what", "work", "works",
}


class DiscoveryService:
    """Handles no-context scholarly discovery and answer generation."""

    def __init__(self):
        self.openalex = OpenAlexService()
        self.europepmc = EuropePmcService()
        self.arxiv = ArxivService()
        self.synthesis_service = None

    def should_use_external_discovery(self, question: str) -> bool:
        return is_specific_research_question(question)

    def build_abstention_response(self) -> Dict:
        return {
            "answer": (
                "I do not have selected local sources for this question, and the query is too broad "
                "to run a reliable paper discovery search. Select papers or ask about a specific "
                "research topic, method, disease, dataset, or model."
            ),
            "citations": [],
            "is_refusal": True,
            "is_insufficient_evidence": True,
            "retrieved_chunks_count": 0,
            "confidence_score": 0.0,
            "discovery_mode": "abstain_no_context",
            "source_basis": None,
            "suggested_sources": [],
        }

    def build_provider_unavailable_response(self) -> Dict:
        return {
            "answer": (
                "I tried external paper discovery, but the paper providers are temporarily unavailable "
                "or rate-limited. I cannot bypass those provider limits permanently from the app side, "
                "but I can retry later or answer once local sources are selected."
            ),
            "citations": [],
            "is_refusal": True,
            "is_insufficient_evidence": True,
            "retrieved_chunks_count": 0,
            "confidence_score": 0.0,
            "discovery_mode": "external_search_unavailable",
            "source_basis": None,
            "suggested_sources": [],
        }

    def _search_provider(self, provider: str, query: str, max_results: int) -> List[Dict]:
        normalized = query.strip().lower()
        cache_key = f"discovery:{provider}:{normalized}:{max_results}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        if provider == "openalex":
            results = self.openalex.search(query, max_results=max_results, prefer_content=True)
            if not results:
                results = self.openalex.search(query, max_results=max_results, prefer_content=False)
        elif provider == "europepmc":
            results = self.europepmc.search(query, max_results=max_results)
        elif provider == "arxiv":
            results = self.arxiv.search(query, max_results=max_results)
        else:
            raise ValueError(f"Unsupported discovery provider: {provider}")

        cache.set(cache_key, results, timeout=DISCOVERY_CACHE_TTL_SECONDS)
        return results

    def _normalize_query(self, question: str) -> str:
        q = re.sub(r"[^a-z0-9\s-]", " ", (question or "").lower())
        q = q.replace("retrieval-augmented generation", "retrieval augmented generation")
        q = q.replace("clinical decision support", "clinical decision support system")
        tokens = [token for token in q.split() if token and token not in DISCOVERY_STOPWORDS]
        if not tokens:
            return question.strip()
        deduped = []
        seen = set()
        for token in tokens:
            if token in seen:
                continue
            seen.add(token)
            deduped.append(token)
        return " ".join(deduped[:10])

    def _query_variants(self, question: str) -> List[str]:
        normalized = self._normalize_query(question)
        variants = [question.strip()]
        if normalized and normalized not in variants:
            variants.append(normalized)
        return variants

    def _provider_order(self, question: str) -> List[str]:
        q = (question or "").lower()
        ai_topic = any(
            token in q
            for token in [
                "llm", "llms", "transformer", "transformers", "retrieval",
                "rag", "language model", "language models", "prompt", "prompting",
                "nlp", "agent", "agents", "attention",
            ]
        )
        biomedical = any(
            token in q
            for token in [
                "clinical", "biomedical", "medicine", "medical", "patient", "disease",
                "therapy", "diagnosis", "drug", "cancer", "cardiology", "genomics",
            ]
        )
        if ai_topic:
            return ["arxiv", "openalex", "europepmc"]
        return ["europepmc", "openalex"] if biomedical else list(DISCOVERY_PROVIDER_ORDER)

    def _result_id(self, item: Dict) -> str:
        return item.get("external_id") or item.get("arxiv_id") or ""

    def _result_to_suggestion(self, item: Dict) -> Dict:
        provider = item.get("source_type") or (
            "arxiv" if item.get("arxiv_id") else "openalex"
        )
        return {
            "id": self._result_id(item),
            "title": item.get("title"),
            "authors": item.get("authors", []),
            "abstract": item.get("abstract"),
            "url": item.get("entry_url"),
            "date": item.get("published_date"),
            "provider": provider,
        }

    def _tokenize(self, text: str) -> List[str]:
        return re.findall(r"[a-z0-9-]+", (text or "").lower())

    def _rank_suggestions(self, question: str, suggestions: List[Dict]) -> List[Dict]:
        query_tokens = {
            token
            for token in self._tokenize(self._normalize_query(question))
            if token and token not in DISCOVERY_STOPWORDS
        }
        scored = []
        for item in suggestions:
            haystack_tokens = set(
                self._tokenize(f"{item.get('title', '')} {item.get('abstract', '')}")
            )
            overlap = len(query_tokens & haystack_tokens)
            title_overlap = len(query_tokens & set(self._tokenize(item.get("title", ""))))
            year_text = str(item.get("date") or "")
            year_bonus = 0.0
            year_match = re.search(r"(19|20)\d{2}", year_text)
            if year_match:
                year = int(year_match.group(0))
                year_bonus = max(0.0, min(0.4, (year - 2018) * 0.03))
            scored.append(((title_overlap * 3) + overlap + year_bonus, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for score, item in scored if score > 0][:5]

    def _collect_suggestions(self, question: str, max_results: int) -> tuple[List[Dict], List[str]]:
        provider_errors = []
        candidates = []
        seen = set()
        for provider in self._provider_order(question):
            for variant in self._query_variants(question):
                try:
                    for item in self._search_provider(provider, variant, max_results):
                        suggestion = self._result_to_suggestion(item)
                        suggestion_id = suggestion.get("id")
                        if not suggestion_id or suggestion_id in seen or not suggestion.get("title"):
                            continue
                        seen.add(suggestion_id)
                        candidates.append(suggestion)
                    break
                except (TransientExternalError, CircuitOpenError) as exc:
                    logger.warning("Discovery provider %s unavailable for '%s': %s", provider, variant, exc)
                    provider_errors.append(provider)
                    break
                except Exception as exc:
                    logger.warning("Discovery provider %s failed for '%s': %s", provider, variant, exc)
                    provider_errors.append(provider)
                    break
        ranked = self._rank_suggestions(question, candidates)
        return ranked[:max_results], provider_errors

    def discover_candidates(self, question: str, max_results: int = 5) -> List[Dict]:
        suggestions, _ = self._collect_suggestions(question, max_results=max_results)
        return suggestions

    def _generate_answer(self, question: str, suggested_sources: List[Dict]) -> str:
        evidence_blocks = []
        for index, item in enumerate(suggested_sources, start=1):
            authors = ", ".join(item.get("authors") or []) or "Unknown authors"
            abstract = (item.get("abstract") or "No abstract available.").strip()
            evidence_blocks.append(
                f"[{index}] {item['title']}\n"
                f"Authors: {authors}\n"
                f"Year: {item.get('date') or 'Unknown'}\n"
                f"Abstract: {abstract}"
            )

        prompt = f"""You are answering a user's scientific question using only discovered paper metadata.

Question:
{question}

Evidence:
{chr(10).join(evidence_blocks)}

Rules:
- Use only the evidence above.
- If the question is broad but topic-oriented, give a useful high-level explanation first, then tie it back to the papers.
- Be explicit that the answer is based on discovered abstracts/metadata, not full-text PDFs.
- Cite supporting papers inline by title.
- If the evidence is mixed or thin, say so directly.
- Keep the answer concise and academic.
"""
        if self.synthesis_service is None:
            self.synthesis_service = SynthesisService()
        return self.synthesis_service._invoke_text(prompt)

    def answer_query_from_external_search(
        self,
        question: str,
        *,
        max_results: int = 5,
    ) -> Dict:
        suggested_sources, provider_errors = self._collect_suggestions(
            question,
            max_results=max_results,
        )

        if not suggested_sources:
            if len(set(provider_errors)) >= len(DISCOVERY_PROVIDER_ORDER):
                return self.build_provider_unavailable_response()
            fallback = self.build_abstention_response()
            fallback["answer"] = (
                "I searched for papers on this topic, but I could not find enough usable scholarly "
                "results to answer confidently. Try a more specific research question."
            )
            fallback["discovery_mode"] = "external_search_no_results"
            return fallback

        answer = self._generate_answer(question, suggested_sources)
        discovery_mode = "external_search_answer"
        if provider_errors:
            discovery_mode = "external_search_answer_with_fallback"

        return {
            "answer": answer,
            "citations": [],
            "is_refusal": False,
            "is_insufficient_evidence": False,
            "retrieved_chunks_count": len(suggested_sources),
            "confidence_score": round(min(0.85, 0.45 + (0.08 * len(suggested_sources))), 3),
            "discovery_mode": discovery_mode,
            "source_basis": "abstracts_and_metadata",
            "suggested_sources": suggested_sources,
        }
