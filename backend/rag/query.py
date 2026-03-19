"""
RAG Query Module

Handles question-answering with:
  - Advanced hybrid retrieval (via RetrievalService)
  - Snippet-level citations (source, page, chunk_id, snippet, score)
  - Refusal / insufficient-evidence classification
"""

import logging
import time
from typing import List, Dict, Optional, Any

from langchain_chroma import Chroma
from django.conf import settings

from rag.utils import get_session_path
from rag.services.retrieval import RetrievalService, ScoredDocument
from rag.services.ollama_client import create_embeddings, create_llm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
#  Response Classification
# ---------------------------------------------------------------------------

REFUSAL_PHRASES = [
    "i cannot find",
    "no relevant sections",
    "i don't have enough information",
    "the provided context does not",
    "there is no information",
    "i cannot answer",
    "not mentioned in the",
    "no information available",
]

INSUFFICIENT_EVIDENCE_PHRASES = [
    "insufficient evidence",
    "limited information",
    "the context does not provide enough",
    "partially addressed",
    "not enough detail",
    "the documents do not fully",
]


def classify_response(answer_text: str) -> Dict[str, bool]:
    """Detect whether an answer is a refusal or flags insufficient evidence."""
    lower_text = answer_text.lower()
    return {
        "is_refusal": any(p in lower_text for p in REFUSAL_PHRASES),
        "is_insufficient_evidence": any(
            p in lower_text for p in INSUFFICIENT_EVIDENCE_PHRASES
        ),
    }


# ---------------------------------------------------------------------------
#  Citation helpers
# ---------------------------------------------------------------------------

def build_snippet_citations(
    scored_docs: List[ScoredDocument],
) -> List[Dict[str, Any]]:
    """Build de-duplicated, snippet-level citations from scored documents."""
    citations: List[Dict[str, Any]] = []
    seen: set = set()

    for doc in scored_docs:
        key = doc.chunk_id
        if key in seen:
            continue
        seen.add(key)
        citations.append(doc.to_citation_dict())

    return citations


# ---------------------------------------------------------------------------
#  Main QA function
# ---------------------------------------------------------------------------

def ask_with_citations(
    question: str,
    session_name: str,
    sources: Optional[List[str]] = None,
    docs_override=None,
    k: int = 8,
) -> Dict[str, Any]:
    """
    Answer a question with advanced hybrid retrieval and snippet-level
    citations.  Returns a dict with keys:
        answer, citations, is_refusal, is_insufficient_evidence,
        retrieved_chunks_count, confidence_score
    """

    retrieval_start = time.perf_counter()

    # ---- 1. Retrieve ----
    if docs_override is not None:
        # Specialised routes pass raw LangChain documents directly
        scored_docs = [ScoredDocument(d, score=1.0) for d in docs_override]
    else:
        retrieval = RetrievalService(session_name)
        effective_k = max(1, min(k, int(getattr(settings, "RAG_QA_TOP_K", k))))
        scored_docs = retrieval.retrieve(
            query=question,
            sources=sources,
            k=effective_k,
            use_hybrid=getattr(settings, "RAG_QA_USE_HYBRID", True),
            use_multi_query=getattr(settings, "RAG_QA_USE_MULTI_QUERY", False),
            use_reranking=getattr(settings, "RAG_QA_USE_RERANKING", True),
        )

    retrieval_ms = int((time.perf_counter() - retrieval_start) * 1000)

    if not scored_docs:
        answer_text = (
            "I cannot find any relevant sections in the selected "
            "documents to answer this question."
        )
        classification = classify_response(answer_text)
        return {
            "answer": answer_text,
            "citations": [],
            **classification,
            "retrieved_chunks_count": 0,
            "confidence_score": 0.0,
            "retrieval_ms": retrieval_ms,
            "generation_ms": 0,
        }

    # ---- 2. Build context ----
    context_parts = []
    for d in scored_docs:
        source = d.metadata.get("source", "unknown")
        page = d.metadata.get("page", "?")
        context_parts.append(
            f"--- SOURCE: {source}, PAGE: {page} ---\n{d.page_content}"
        )
    context = "\n\n".join(context_parts)

    # ---- 3. Generate answer ----
    generation_start = time.perf_counter()
    llm = create_llm(model=getattr(settings, "RAG_LLM_MODEL", "mistral"))

    prompt = f"""You are a precise scientific research assistant.

INSTRUCTIONS:
1. Answer the question using ONLY the provided context.
2. If the answer isn't explicitly in the context but can be reasonably inferred based ONLY on the evidence provided, do so and state it is an inference.
3. If you truly cannot find the answer, don't just say "I can't answer". Instead, briefly summarize what the documents DO say about the topic, then explain what specific information is missing.
4. Use a professional, academic tone.
5. If multiple documents are provided, compare their findings if relevant.

CONTEXT:
{context}

QUESTION:
{question}

ANSWER:
"""

    response = llm.invoke(prompt)
    generation_ms = int((time.perf_counter() - generation_start) * 1000)
    logger.info(
        "qa_timing_ms retrieval=%s generation=%s total=%s",
        retrieval_ms,
        generation_ms,
        retrieval_ms + generation_ms,
    )

    # Strip the thinking section
    if "ANSWER:" in response:
        final_answer = response.split("ANSWER:")[-1].strip()
    else:
        final_answer = response.strip()

    # ---- 4. Snippet-level citations ----
    citations = build_snippet_citations(scored_docs)

    # ---- 5. Classify the answer ----
    classification = classify_response(final_answer)

    avg_score = sum(d.score for d in scored_docs) / len(scored_docs)

    return {
        "answer": final_answer,
        "citations": citations,
        **classification,
        "retrieved_chunks_count": len(scored_docs),
        "confidence_score": round(avg_score, 4),
        "retrieval_ms": retrieval_ms,
        "generation_ms": generation_ms,
    }


# ---------------------------------------------------------------------------
#  Paper overview helper  (used by the specialised "about this paper" route)
# ---------------------------------------------------------------------------

def retrieve_paper_overview(
    question: str,
    session_name: str,
    source: str,
    k_body: int = 4,
):
    """
    Retrieve a structured overview of a paper:
      - Always include abstract chunks
      - Add top-k body chunks for reasoning
    """
    persist_dir = get_session_path(session_name)
    embeddings = create_embeddings(model="nomic-embed-text")

    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )

    # 1. Retrieve ABSTRACT chunks
    abstract_docs = vectordb.similarity_search(
        "abstract",
        k=5,
        filter={
            "$and": [
                {"source": {"$eq": source}},
                {"section": {"$eq": "abstract"}},
            ]
        },
    )

    # 2. Retrieve BODY chunks (semantic)
    body_docs = vectordb.similarity_search(
        question,
        k=k_body,
        filter={
            "$and": [
                {"source": {"$eq": source}},
                {"section": {"$eq": "body"}},
            ]
        },
    )

    return abstract_docs + body_docs
