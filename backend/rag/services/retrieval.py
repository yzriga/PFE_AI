"""
Advanced Retrieval Service

Provides:
  - Hybrid search (vector similarity + BM25 keyword)
  - Reciprocal Rank Fusion (RRF) for merging ranked lists
  - Multi-query expansion via LLM
  - Lightweight reranking (keyword overlap boosting)
  - Recursive retrieval (retrieve → assess → re-retrieve if uncertain)
"""

import logging
import hashlib
from typing import List, Dict, Tuple, Optional
from collections import defaultdict

from langchain_chroma import Chroma
from langchain_core.documents import Document as LangchainDocument
from rank_bm25 import BM25Okapi

from rag.utils import get_session_path
from rag.utils import sanitize_text
from rag.services.ollama_client import create_embeddings, create_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ScoredDocument — wrapper that carries score + chunk_id + snippet
# ---------------------------------------------------------------------------

class ScoredDocument:
    """A retrieved document with an associated retrieval score and unique ID."""

    def __init__(self, document, score: float = 0.0, chunk_id: str = ""):
        self.document = document
        self.score = score
        self.chunk_id = chunk_id or self._generate_id()

    # ---- helpers ----

    def _generate_id(self) -> str:
        content_hash = hashlib.md5(
            self.document.page_content[:200].encode()
        ).hexdigest()[:12]
        source = self.document.metadata.get("source", "unknown")
        page = self.document.metadata.get("page", 0)
        return f"{source}_p{page}_{content_hash}"

    @property
    def snippet(self) -> str:
        """First ~200 characters of the chunk content."""
        return sanitize_text(self.document.page_content[:200]).strip()

    @property
    def metadata(self) -> dict:
        return self.document.metadata

    @property
    def page_content(self) -> str:
        return sanitize_text(self.document.page_content)

    def to_citation_dict(self) -> dict:
        """Serialise into the snippet-level citation format returned by the API."""
        return {
            "source": self.metadata.get("source", "unknown"),
            "page": self.metadata.get("page", 0),
            "chunk_id": self.chunk_id,
            "snippet": self.snippet,
            "score": round(self.score, 4),
        }


# ---------------------------------------------------------------------------
# RetrievalService
# ---------------------------------------------------------------------------

class RetrievalService:
    """
    Advanced retrieval with hybrid search, multi-query, reranking,
    and recursive retrieval.
    """

    def __init__(
        self,
        session_name: str,
        embedding_model: str = "nomic-embed-text",
        llm_model: str = "mistral",
    ):
        self.session_name = session_name
        self.embeddings = create_embeddings(model=embedding_model)
        self.llm_model = llm_model
        self._llm = None
        self.persist_dir = get_session_path(session_name)
        self.vectordb = Chroma(
            persist_directory=self.persist_dir,
            embedding_function=self.embeddings,
        )
        self._bm25_corpus_cache: Dict[str, Tuple[List[str], List[dict]]] = {}

    def _get_llm(self):
        if self._llm is None:
            self._llm = create_llm(model=self.llm_model)
        return self._llm

    # ================================================================
    #  PUBLIC API
    # ================================================================

    def retrieve(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        k: int = 8,
        use_hybrid: bool = True,
        use_multi_query: bool = True,
        use_reranking: bool = True,
    ) -> List[ScoredDocument]:
        """
        Full retrieval pipeline:
          1. (Optional) Multi-query expansion
          2. Hybrid vector + BM25 retrieval  (or vector-only)
          3. Reciprocal Rank Fusion across query variants
          4. (Optional) Reranking via keyword-overlap boosting
        """
        # Step 1 — query variants
        if use_multi_query:
            query_variants = self._generate_query_variants(query)
            logger.info(
                f"Multi-query: generated {len(query_variants)} variants"
            )
        else:
            query_variants = [query]

        # Step 2 — retrieve per variant
        all_result_lists: List[List[ScoredDocument]] = []
        for variant in query_variants:
            if use_hybrid:
                results = self._hybrid_search(variant, sources, k=k)
            else:
                results = self._vector_search(variant, sources, k=k)
            all_result_lists.append(results)

        # Step 3 — fuse
        if len(all_result_lists) > 1:
            merged = self._reciprocal_rank_fusion(all_result_lists, k=k)
        else:
            merged = all_result_lists[0] if all_result_lists else []

        # Step 4 — rerank
        if use_reranking and merged:
            merged = self._rerank(query, merged, k=k)

        return merged[:k]

    def recursive_retrieve(
        self,
        query: str,
        sources: Optional[List[str]] = None,
        k: int = 8,
        max_rounds: int = 2,
    ) -> Tuple[List[ScoredDocument], bool]:
        """
        Recursive retrieval:
          retrieve → assess sufficiency → if uncertain, refine query → retrieve again.
        Returns (scored_documents, was_sufficient).
        """
        docs = self.retrieve(query, sources, k=k)

        if not docs:
            return docs, False

        for round_num in range(max_rounds - 1):
            is_sufficient = self._assess_sufficiency(query, docs)
            if is_sufficient:
                logger.info(
                    f"Recursive retrieval: sufficient at round {round_num + 1}"
                )
                return docs, True

            # Generate a more focused follow-up query
            refined_query = self._refine_query(query, docs)
            logger.info(
                f"Recursive retrieval round {round_num + 2}: "
                f"'{refined_query[:80]}...'"
            )

            additional = self.retrieve(refined_query, sources, k=k // 2)

            # Merge, deduplicate
            seen_ids = {d.chunk_id for d in docs}
            for d in additional:
                if d.chunk_id not in seen_ids:
                    docs.append(d)
                    seen_ids.add(d.chunk_id)

        return docs[: k + 4], self._assess_sufficiency(query, docs)

    # ================================================================
    #  PRIVATE — search primitives
    # ================================================================

    def _vector_search(
        self, query: str, sources: Optional[List[str]], k: int
    ) -> List[ScoredDocument]:
        """Standard vector similarity search (with per-source balancing)."""
        try:
            if sources and len(sources) > 1:
                all_docs = []
                per_source_k = max(2, k // len(sources))
                for src in sources:
                    results = (
                        self.vectordb.similarity_search_with_relevance_scores(
                            query, k=per_source_k, filter={"source": src}
                        )
                    )
                    all_docs.extend(results)
            elif sources:
                all_docs = (
                    self.vectordb.similarity_search_with_relevance_scores(
                        query, k=k, filter={"source": {"$in": sources}}
                    )
                )
            else:
                all_docs = (
                    self.vectordb.similarity_search_with_relevance_scores(
                        query, k=k
                    )
                )

            return [
                ScoredDocument(doc, score=float(score))
                for doc, score in all_docs
            ]
        except Exception as e:
            logger.warning(f"Vector search failed: {e}")
            return []

    def _bm25_search(
        self, query: str, sources: Optional[List[str]], k: int
    ) -> List[ScoredDocument]:
        """BM25 keyword search over the Chroma collection."""
        try:
            documents, metadatas = self._get_bm25_corpus(sources)

            if not documents:
                return []

            # BM25 scoring
            tokenized_docs = [doc.lower().split() for doc in documents]
            tokenized_query = query.lower().split()

            bm25 = BM25Okapi(tokenized_docs)
            scores = bm25.get_scores(tokenized_query)

            top_indices = sorted(
                range(len(scores)), key=lambda i: scores[i], reverse=True
            )[:k]

            results = []
            for idx in top_indices:
                if scores[idx] > 0:
                    doc = LangchainDocument(
                        page_content=documents[idx],
                        metadata=metadatas[idx] if idx < len(metadatas) else {},
                    )
                    results.append(ScoredDocument(doc, score=float(scores[idx])))

            return results
        except Exception as e:
            logger.warning(f"BM25 search failed: {e}")
            return []

    def _get_bm25_corpus(
        self, sources: Optional[List[str]]
    ) -> Tuple[List[str], List[dict]]:
        """Cache corpus fetches so hybrid+multi-query doesn't re-read Chroma repeatedly."""
        cache_key = ",".join(sorted(sources)) if sources else "__all__"
        cached = self._bm25_corpus_cache.get(cache_key)
        if cached is not None:
            return cached

        if sources:
            where = (
                {"source": {"$in": sources}}
                if len(sources) > 1
                else {"source": sources[0]}
            )
            collection_data = self.vectordb.get(where=where)
        else:
            collection_data = self.vectordb.get()

        documents = collection_data.get("documents") or []
        metadatas = collection_data.get("metadatas") or []
        self._bm25_corpus_cache[cache_key] = (documents, metadatas)
        return documents, metadatas

    def _hybrid_search(
        self, query: str, sources: Optional[List[str]], k: int
    ) -> List[ScoredDocument]:
        """Combine vector + BM25 with Reciprocal Rank Fusion."""
        vector_results = self._vector_search(query, sources, k=k)
        bm25_results = self._bm25_search(query, sources, k=k)

        if not bm25_results:
            return vector_results
        if not vector_results:
            return bm25_results

        return self._reciprocal_rank_fusion(
            [vector_results, bm25_results], k=k
        )

    # ================================================================
    #  PRIVATE — fusion & reranking
    # ================================================================

    def _reciprocal_rank_fusion(
        self,
        result_lists: List[List[ScoredDocument]],
        k_constant: int = 60,
        k: int = 10,
    ) -> List[ScoredDocument]:
        """Merge multiple ranked lists using RRF (reciprocal rank fusion)."""
        rrf_scores: Dict[str, float] = defaultdict(float)
        doc_map: Dict[str, ScoredDocument] = {}

        for result_list in result_lists:
            for rank, scored_doc in enumerate(result_list):
                doc_id = scored_doc.chunk_id
                rrf_scores[doc_id] += 1.0 / (k_constant + rank + 1)
                if doc_id not in doc_map:
                    doc_map[doc_id] = scored_doc

        sorted_ids = sorted(
            rrf_scores.keys(), key=lambda x: rrf_scores[x], reverse=True
        )

        results = []
        for doc_id in sorted_ids[:k]:
            doc = doc_map[doc_id]
            doc.score = rrf_scores[doc_id]
            results.append(doc)

        return results

    def _rerank(
        self, query: str, candidates: List[ScoredDocument], k: int
    ) -> List[ScoredDocument]:
        """
        Lightweight reranking using keyword-overlap boosting.
        Blends the existing retrieval score (70%) with a keyword-overlap
        ratio (30%) to push lexically-relevant passages higher.
        """
        query_terms = set(query.lower().split())

        for doc in candidates:
            content_terms = set(doc.page_content.lower().split())

            if query_terms:
                overlap = len(query_terms & content_terms) / len(query_terms)
            else:
                overlap = 0.0

            doc.score = doc.score * 0.7 + overlap * 0.3

        candidates.sort(key=lambda d: d.score, reverse=True)
        return candidates[:k]

    # ================================================================
    #  PRIVATE — multi-query & recursive helpers
    # ================================================================

    def _generate_query_variants(self, query: str, n: int = 3) -> List[str]:
        """Use the LLM to produce query reformulations."""
        try:
            prompt = (
                f"Generate {n} different versions of the following research "
                f"question.  Each version should approach the topic from a "
                f"slightly different angle to improve search coverage.\n"
                f"Return ONLY the questions, one per line, no numbering.\n\n"
                f"Original question: {query}\n\n"
                f"Reformulated questions:"
            )

            response = self._get_llm().invoke(prompt)
            variants = [
                line.strip().lstrip("0123456789.-) ")
                for line in response.strip().split("\n")
                if line.strip() and len(line.strip()) > 10
            ]

            # Always include the original query first
            return [query] + variants[:n]
        except Exception as e:
            logger.warning(f"Multi-query generation failed: {e}")
            return [query]

    def _assess_sufficiency(
        self, query: str, docs: List[ScoredDocument]
    ) -> bool:
        """Heuristic check: do the chunks likely cover the query?"""
        if not docs:
            return False

        avg_score = sum(d.score for d in docs) / len(docs)

        # Keyword coverage
        query_terms = set(query.lower().split())
        covered_terms = set()
        for doc in docs:
            content_lower = doc.page_content.lower()
            for term in query_terms:
                if term in content_lower:
                    covered_terms.add(term)

        coverage = len(covered_terms) / max(len(query_terms), 1)

        return avg_score > 0.01 and coverage > 0.5

    def _refine_query(
        self, original_query: str, docs: List[ScoredDocument]
    ) -> str:
        """Generate a refined follow-up query to fill gaps."""
        try:
            snippets = "\n".join([d.snippet for d in docs[:3]])
            prompt = (
                f"Based on the original question and the partial information "
                f"retrieved below, generate a more specific follow-up question "
                f"to find the missing information.\n\n"
                f"Original question: {original_query}\n\n"
                f"Information already found:\n{snippets}\n\n"
                f"Follow-up question (one line):"
            )
            response = self._get_llm().invoke(prompt)
            refined = response.strip().split("\n")[0].strip()
            return refined if len(refined) > 10 else original_query
        except Exception as e:
            logger.warning(f"Query refinement failed: {e}")
            return original_query
