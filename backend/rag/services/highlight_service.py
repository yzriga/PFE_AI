"""
Service for managing highlight embeddings in ChromaDB.

Enables semantic retrieval of user annotations during RAG queries.
"""

import logging
from typing import Optional
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from rag.models import Highlight, HighlightEmbedding
from rag.utils import get_session_path

logger = logging.getLogger(__name__)


class HighlightService:
    """Service for embedding and retrieving user highlights."""
    
    def __init__(self):
        """Initialize embeddings model."""
        self.embeddings = OllamaEmbeddings(model="nomic-embed-text")
    
    def embed_highlight(self, highlight: Highlight) -> Optional[str]:
        """
        Create embedding for a highlight and store in ChromaDB.
        
        Embeds the combination of highlighted text + user note
        for richer semantic matching during retrieval.
        
        Args:
            highlight: Highlight model instance
        
        Returns:
            embedding_id if successful, None if failed
        """
        try:
            # Get session's vector DB
            session_name = highlight.document.session.name
            persist_dir = get_session_path(session_name)
            
            vectordb = Chroma(
                persist_directory=persist_dir,
                embedding_function=self.embeddings
            )
            
            # Combine text + note for richer embedding
            content = highlight.text
            if highlight.note:
                content += f"\n\n[USER NOTE]: {highlight.note}"
            
            # Generate unique ID
            embedding_id = f"highlight_{highlight.id}_{highlight.document.id}"
            
            # Add to ChromaDB
            vectordb.add_texts(
                texts=[content],
                metadatas=[{
                    "type": "highlight",
                    "highlight_id": highlight.id,
                    "document_id": highlight.document.id,
                    "source": highlight.document.filename,
                    "page": highlight.page,
                    "tags": ",".join(highlight.tags) if highlight.tags else ""
                }],
                ids=[embedding_id]
            )
            
            # Store embedding reference
            HighlightEmbedding.objects.create(
                highlight=highlight,
                embedding_id=embedding_id
            )
            
            logger.info(f"Embedded highlight {highlight.id} as {embedding_id}")
            return embedding_id
            
        except Exception as e:
            logger.error(f"Failed to embed highlight {highlight.id}: {e}")
            return None
    
    def update_embedding(self, highlight: Highlight) -> bool:
        """
        Update existing highlight embedding after note/tag changes.
        
        Args:
            highlight: Highlight with updated content
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if embedding exists
            if not hasattr(highlight, 'embedding'):
                # No existing embedding, create new one
                return self.embed_highlight(highlight) is not None
            
            # Get existing embedding
            embedding_obj = highlight.embedding
            embedding_id = embedding_obj.embedding_id
            
            # Get vector DB
            session_name = highlight.document.session.name
            persist_dir = get_session_path(session_name)
            
            vectordb = Chroma(
                persist_directory=persist_dir,
                embedding_function=self.embeddings
            )
            
            # Delete old embedding
            vectordb.delete(ids=[embedding_id])
            
            # Create new embedding with updated content
            content = highlight.text
            if highlight.note:
                content += f"\n\n[USER NOTE]: {highlight.note}"
            
            vectordb.add_texts(
                texts=[content],
                metadatas=[{
                    "type": "highlight",
                    "highlight_id": highlight.id,
                    "document_id": highlight.document.id,
                    "source": highlight.document.filename,
                    "page": highlight.page,
                    "tags": ",".join(highlight.tags) if highlight.tags else ""
                }],
                ids=[embedding_id]
            )
            
            logger.info(f"Updated embedding for highlight {highlight.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update embedding for highlight {highlight.id}: {e}")
            return False
    
    def delete_embedding(self, highlight: Highlight) -> bool:
        """
        Delete highlight embedding from ChromaDB.
        
        Args:
            highlight: Highlight to delete
        
        Returns:
            True if successful, False otherwise
        """
        try:
            # Check if embedding exists
            if not hasattr(highlight, 'embedding'):
                logger.warning(f"Highlight {highlight.id} has no embedding to delete")
                return True  # Nothing to delete
            
            embedding_id = highlight.embedding.embedding_id
            
            # Get vector DB
            session_name = highlight.document.session.name
            persist_dir = get_session_path(session_name)
            
            vectordb = Chroma(
                persist_directory=persist_dir,
                embedding_function=self.embeddings
            )
            
            # Delete from ChromaDB
            vectordb.delete(ids=[embedding_id])
            
            logger.info(f"Deleted embedding {embedding_id} for highlight {highlight.id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete embedding for highlight {highlight.id}: {e}")
            return False
    
    def retrieve_highlights(
        self,
        session_name: str,
        query: str,
        k: int = 3
    ) -> list:
        """
        Retrieve relevant highlights for a query.
        
        Used during RAG to inject user notes as priority context.
        
        Args:
            session_name: Session to search in
            query: User's question
            k: Number of highlights to retrieve
        
        Returns:
            List of highlight documents with metadata
        """
        try:
            persist_dir = get_session_path(session_name)
            
            vectordb = Chroma(
                persist_directory=persist_dir,
                embedding_function=self.embeddings
            )
            
            # Search with filter for highlights only
            results = vectordb.similarity_search(
                query,
                k=k,
                filter={"type": "highlight"}
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to retrieve highlights: {e}")
            return []
