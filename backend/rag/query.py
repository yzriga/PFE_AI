from langchain_chroma import Chroma
from langchain_ollama import OllamaLLM, OllamaEmbeddings

from rag.utils import get_session_path


def ask_with_citations(
    question: str,
    session_name: str,
    sources: list[str] | None = None,
    k: int = 5
):
    """
    Ask a question over a session-scoped Chroma vector store.
    Optionally restrict retrieval to specific PDF sources.
    """

    # 1. Resolve session vector store path
    persist_dir = get_session_path(session_name)

    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    # 2. Retrieve documents (STRICT filtering if sources provided)
    if sources:
        docs = vectordb.similarity_search(
            question,
            k=k,
            filter={"source": {"$in": sources}}
        )
    else:
        docs = vectordb.similarity_search(question, k=k)

    # 3. Hard fail if nothing retrieved
    if not docs:
        return {
            "answer": "I cannot answer this question based on the selected document(s).",
            "citations": []
        }

    # 4. Build grounded context
    context = "\n\n".join(d.page_content for d in docs)

    # 5. Strictly grounded LLM prompt
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

    # 6. Structured citations
    citations = [
        {
            "source": d.metadata.get("source"),
            "page": d.metadata.get("page"),
        }
        for d in docs
    ]

    return {
        "answer": answer,
        "citations": citations
    }
