from langchain_chroma import Chroma
from langchain_ollama import OllamaLLM, OllamaEmbeddings

from rag.utils import get_session_path
from rag.services.highlight_service import HighlightService

from collections import Counter


def ask_with_citations(
    question: str,
    session_name: str,
    sources=None,
    docs_override=None,
    k: int = 5,
    include_highlights: bool = True,
):
    persist_dir = get_session_path(session_name)
    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    # 1. Retrieve user highlights first (priority context)
    highlight_docs = []
    if include_highlights:
        try:
            highlight_service = HighlightService()
            highlight_docs = highlight_service.retrieve_highlights(
                session_name=session_name,
                query=question,
                k=2  # Retrieve top 2 relevant highlights
            )
        except Exception as e:
            # Gracefully degrade if highlight retrieval fails
            pass

    # USE OVERRIDE IF PROVIDED
    if docs_override is not None:
        docs = docs_override

    else:
        # 2. Retrieve documents (STRICT filtering if sources provided)
        if sources:
            docs = vectordb.similarity_search(
                question,
                k=k,
                filter={"source": {"$in": sources}, "type": {"$ne": "highlight"}}
            )
        else:
            docs = vectordb.similarity_search(
                question,
                k=k,
                filter={"type": {"$ne": "highlight"}}  # Exclude highlights from regular retrieval
            )


    if not docs and not highlight_docs:
        return {
            "answer": "I cannot answer this question based on the selected document(s).",
            "citations": []
        }

    # Build context: Highlights first (priority), then regular chunks
    context_parts = []
    
    # Add highlights with special tag
    if highlight_docs:
        for h_doc in highlight_docs:
            context_parts.append(f"[USER NOTE - Page {h_doc.metadata.get('page', '?')}]\n{h_doc.page_content}")
    
    # Add regular document chunks
    for d in docs:
        context_parts.append(d.page_content if hasattr(d, "page_content") else d)
    
    context = "\n\n".join(context_parts)

    llm = OllamaLLM(model="mistral")

    prompt = f"""
You are a scientific assistant.

Answer the question using ONLY the context below.
Pay special attention to sections marked [USER NOTE] as they contain important user annotations.
If the answer is not explicitly present in the context,
respond exactly with:

"I cannot answer based on the provided documents."

Context:
{context}

Question:
{question}
"""

    answer = llm.invoke(prompt)

    # citations = []
    # for d in docs:
    #     if hasattr(d, "metadata"):
    #         citations.append({
    #             "source": d.metadata.get("source"),
    #             "page": d.metadata.get("page"),
    #         })

    page_counts = Counter(
        (d.metadata.get("source"), d.metadata.get("page"))
        for d in docs
    )

    citations = [
        {
            "source": source,
            "page": page,
            "count": count
        }
        for (source, page), count in page_counts.items()
    ]

    return {
        "answer": answer,
        "citations": citations
    }


def retrieve_paper_overview(
    question: str,
    session_name: str,
    source: str,
    k_body: int = 4,
):
    """
    Retrieve a structured overview of a paper:
    - Always include abstract
    - Add top-k body chunks for reasoning
    """

    persist_dir = get_session_path(session_name)
    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )

    # ✅ 1. Retrieve ABSTRACT chunks (correct Chroma filter)
    abstract_docs = vectordb.similarity_search(
        "abstract",
        k=5,
        filter={
            "$and": [
                {"source": {"$eq": source}},
                {"section": {"$eq": "abstract"}},
            ]
        }
    )

    # ✅ 2. Retrieve BODY chunks (semantic)
    body_docs = vectordb.similarity_search(
        question,
        k=k_body,
        filter={
            "$and": [
                {"source": {"$eq": source}},
                {"section": {"$eq": "body"}},
            ]
        }
    )

    # ✅ 3. Combine
    docs = []
    docs.extend(abstract_docs)
    docs.extend(body_docs)

    return docs
