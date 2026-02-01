from langchain_chroma import Chroma
from langchain_ollama import OllamaLLM, OllamaEmbeddings

from rag.utils import get_session_path


def ask_with_citations(
    question: str,
    session_name: str,
    sources=None,
    docs_override=None,
    k: int = 5,
):
    persist_dir = get_session_path(session_name)
    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    # USE OVERRIDE IF PROVIDED
    if docs_override is not None:
        docs = docs_override

    else:
        if sources:
            docs = vectordb.similarity_search(
                question,
                k=k,
                filter={
                    "$and": [
                        {"source": {"$in": sources}}
                    ]
                }
            )
        else:
            docs = vectordb.similarity_search(question, k=k)

    if not docs:
        return {
            "answer": "I cannot answer this question based on the selected document(s).",
            "citations": []
        }

    # Normalize docs → text
    context = "\n\n".join(
        d.page_content if hasattr(d, "page_content") else d
        for d in docs
    )

    llm = OllamaLLM(model="mistral")

    prompt = f"""
You are a scientific assistant.

Answer the question using ONLY the context below.
If the answer is not explicitly present in the context,
respond exactly with:

"I cannot answer based on the provided documents."

Context:
{context}

Question:
{question}
"""

    answer = llm.invoke(prompt)

    citations = []
    for d in docs:
        if hasattr(d, "metadata"):
            citations.append({
                "source": d.metadata.get("source"),
                "page": d.metadata.get("page"),
            })

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
