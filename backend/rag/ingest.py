from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from rag.utils import get_session_path


def ingest_pdf(path: str, session_name: str, source_name: str):
    """
    Ingest a PDF into a session-specific Chroma vector store.
    source_name is the ORIGINAL filename (stable identifier).
    """

    # 1. Load PDF
    loader = PyPDFLoader(path)
    pages = loader.load()

    # 2. Add metadata (CRITICAL FIX)
    for page in pages:
        page.metadata["source"] = source_name
        page.metadata["page"] = page.metadata.get("page")

    # 3. Split into chunks
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = splitter.split_documents(pages)

    # 4. Embeddings
    embeddings = OllamaEmbeddings(model="nomic-embed-text")

    # 5. Session-specific vector store
    persist_dir = get_session_path(session_name)

    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )

    # 6. Store chunks (auto-persist)
    vectordb.add_documents(chunks)
