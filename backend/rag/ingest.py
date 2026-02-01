from pathlib import Path
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

from rag.utils import get_session_path, normalize_filename
from rag.metadata import extract_title_and_abstract
from rag.models import Document


def ingest_pdf(path: str, session_name: str, document: Document):
    pdf_name = document.filename

    # 1. Load PDF
    loader = PyPDFLoader(path)
    pages = loader.load()

    if not pages:
        return

    # 2. Extract metadata from FIRST PAGE
    first_page_text = pages[0].page_content
    title, abstract = extract_title_and_abstract(first_page_text)

    # 3. Persist metadata
    document.title = title
    document.abstract = abstract
    document.save(update_fields=["title", "abstract"])

    # 4. Attach metadata to pages
    # for page in pages:
    #     page.metadata["source"] = pdf_name
    #     page.metadata["page"] = page.metadata.get("page")
    for i, page in enumerate(pages):
        page.metadata["source"] = pdf_name
        page.metadata["page"] = i

        if i == 0:
            page.metadata["section"] = "abstract"
        else:
            page.metadata["section"] = "body"

    # 5. Split
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=200
    )
    chunks = splitter.split_documents(pages)

    # 6. Store in session vector DB
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    persist_dir = get_session_path(session_name)

    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    vectordb.add_documents(chunks)
