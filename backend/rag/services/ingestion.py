"""
Unified Ingestion Service

Handles PDF processing with robust error handling and status tracking.
"""
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from django.utils import timezone
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma

from rag.models import Document
from rag.utils import get_session_path
from rag.metadata import extract_title_and_abstract

logger = logging.getLogger(__name__)


class IngestionService:
    """
    Service for ingesting PDFs into the vector database.
    """
    
    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 200,
        embedding_model: str = "nomic-embed-text"
    ):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.embedding_model = embedding_model
        self.embeddings = OllamaEmbeddings(model=embedding_model)
    
    def ingest_document(self, document_id: int, pdf_path: str) -> dict:
        """
        Ingest a single document.
        
        Args:
            document_id: Database ID of the document
            pdf_path: Filesystem path to the PDF
            
        Returns:
            dict with status and metadata
        """
        try:
            document = Document.objects.get(id=document_id)
            logger.info(f"Starting ingestion for document {document_id}: {document.filename}")
            
            # Update status to PROCESSING
            document.status = 'PROCESSING'
            document.processing_started_at = timezone.now()
            document.save(update_fields=['status', 'processing_started_at'])
            
            # Step 1: Load PDF
            loader = PyPDFLoader(pdf_path)
            pages = loader.load()
            
            if not pages:
                raise ValueError("PDF has no readable pages")
            
            logger.info(f"Loaded {len(pages)} pages from {document.filename}")
            
            # Step 2: Extract metadata from first page
            first_page_text = pages[0].page_content
            title, abstract = extract_title_and_abstract(first_page_text)
            
            # Update document metadata
            document.title = title
            document.abstract = abstract
            document.page_count = len(pages)
            document.save(update_fields=['title', 'abstract', 'page_count'])
            
            logger.info(f"Extracted metadata - Title: {title[:50] if title else 'None'}")
            
            # Step 3: Tag pages with metadata
            for i, page in enumerate(pages):
                page.metadata["source"] = document.filename
                page.metadata["page"] = i
                page.metadata["section"] = "abstract" if i == 0 else "body"
            
            # Step 4: Split into chunks
            splitter = RecursiveCharacterTextSplitter(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap
            )
            chunks = splitter.split_documents(pages)
            
            logger.info(f"Split into {len(chunks)} chunks")
            
            # Step 5: Store in session-scoped vector database
            persist_dir = get_session_path(document.session.name)
            vectordb = Chroma(
                persist_directory=persist_dir,
                embedding_function=self.embeddings
            )
            
            vectordb.add_documents(chunks)
            
            logger.info(f"Indexed {len(chunks)} chunks to {persist_dir}")
            
            # Step 6: Mark as INDEXED
            document.status = 'INDEXED'
            document.processing_completed_at = timezone.now()
            document.error_message = None
            document.save(update_fields=['status', 'processing_completed_at', 'error_message'])
            
            processing_time = (document.processing_completed_at - document.processing_started_at).total_seconds()
            
            logger.info(f"Successfully indexed document {document_id} in {processing_time:.2f}s")
            
            return {
                "status": "success",
                "document_id": document_id,
                "chunks_indexed": len(chunks),
                "processing_time_seconds": processing_time,
                "title": title,
                "page_count": len(pages)
            }
            
        except Document.DoesNotExist:
            logger.error(f"Document {document_id} not found")
            return {
                "status": "error",
                "error": "Document not found"
            }
        
        except Exception as e:
            logger.exception(f"Error ingesting document {document_id}")
            
            # Mark as FAILED and store error
            try:
                document = Document.objects.get(id=document_id)
                document.status = 'FAILED'
                document.processing_completed_at = timezone.now()
                document.error_message = str(e)
                document.save(update_fields=['status', 'processing_completed_at', 'error_message'])
            except Exception as save_error:
                logger.error(f"Failed to update document status: {save_error}")
            
            return {
                "status": "error",
                "document_id": document_id,
                "error": str(e)
            }
    
    def reingest_document(self, document_id: int, pdf_path: str) -> dict:
        """
        Re-ingest a failed document.
        """
        logger.info(f"Re-ingesting document {document_id}")
        return self.ingest_document(document_id, pdf_path)
