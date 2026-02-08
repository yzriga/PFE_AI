"""
arXiv Connector Service

Provides functionality to:
- Search papers on arXiv
- Fetch metadata for specific papers
- Download PDFs
- Import papers into the system with proper metadata tracking
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

import arxiv
import requests
from django.conf import settings

from rag.models import PaperSource, Document, Session
from rag.services.ingestion import IngestionService

logger = logging.getLogger(__name__)


class ArxivService:
    """Service for interacting with arXiv API and importing papers."""
    
    def __init__(self):
        self.client = arxiv.Client()
        self.ingestion_service = IngestionService()
    
    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search arXiv for papers matching the query.
        
        Args:
            query: Search query (e.g., "quantum computing", "ti:machine learning")
            max_results: Maximum number of results to return
        
        Returns:
            List of paper metadata dictionaries
        """
        logger.info(f"Searching arXiv: query='{query}', max_results={max_results}")
        
        try:
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.SubmittedDate,
                sort_order=arxiv.SortOrder.Descending
            )
            
            results = []
            for paper in self.client.results(search):
                results.append(self._extract_metadata(paper))
            
            logger.info(f"Found {len(results)} papers on arXiv")
            return results
        
        except Exception as e:
            logger.error(f"arXiv search failed: {e}")
            raise
    
    def fetch_metadata(self, arxiv_id: str) -> Dict:
        """
        Fetch metadata for a specific arXiv paper.
        
        Args:
            arxiv_id: arXiv identifier (e.g., "2411.04920", "2411.04920v4")
        
        Returns:
            Paper metadata dictionary
        """
        logger.info(f"Fetching metadata for arXiv:{arxiv_id}")
        
        try:
            search = arxiv.Search(id_list=[arxiv_id])
            paper = next(self.client.results(search))
            
            metadata = self._extract_metadata(paper)
            logger.info(f"Retrieved metadata for '{metadata['title'][:50]}...'")
            return metadata
        
        except StopIteration:
            logger.error(f"arXiv paper not found: {arxiv_id}")
            raise ValueError(f"Paper with arXiv ID '{arxiv_id}' not found")
        except Exception as e:
            logger.error(f"Failed to fetch arXiv metadata: {e}")
            raise
    
    def download_pdf(self, arxiv_id: str, save_dir: str) -> str:
        """
        Download PDF for a specific arXiv paper.
        
        Args:
            arxiv_id: arXiv identifier
            save_dir: Directory to save the PDF
        
        Returns:
            Path to the downloaded PDF file
        """
        logger.info(f"Downloading PDF for arXiv:{arxiv_id}")
        
        try:
            search = arxiv.Search(id_list=[arxiv_id])
            paper = next(self.client.results(search))
            
            # Create save directory if it doesn't exist
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            
            # Sanitize filename (remove special characters)
            safe_title = "".join(c for c in paper.title if c.isalnum() or c in (' ', '-', '_'))[:100]
            filename = f"{arxiv_id.replace('/', '_')}_{safe_title}.pdf"
            filepath = os.path.join(save_dir, filename)
            
            # Download using arxiv library's built-in method
            paper.download_pdf(dirpath=save_dir, filename=filename)
            
            logger.info(f"PDF downloaded successfully: {filepath}")
            return filepath
        
        except StopIteration:
            logger.error(f"arXiv paper not found: {arxiv_id}")
            raise ValueError(f"Paper with arXiv ID '{arxiv_id}' not found")
        except Exception as e:
            logger.error(f"PDF download failed: {e}")
            raise
    
    def import_paper(
        self,
        arxiv_id: str,
        session_name: str,
        download_pdf: bool = True
    ) -> Dict:
        """
        Import an arXiv paper into the system.
        
        Steps:
        1. Fetch metadata from arXiv
        2. Create PaperSource record
        3. Download PDF (if requested)
        4. Create Document and ingest (async)
        
        Args:
            arxiv_id: arXiv identifier
            session_name: Name of the session to import into
            download_pdf: Whether to download and ingest the PDF
        
        Returns:
            Dictionary with import status and IDs
        """
        logger.info(f"Importing arXiv paper {arxiv_id} into session '{session_name}'")
        
        try:
            # 1. Fetch metadata
            metadata = self.fetch_metadata(arxiv_id)
            
            # 2. Get or create session
            session, _ = Session.objects.get_or_create(name=session_name)
            
            # 3. Create or get PaperSource
            paper_source, created = PaperSource.objects.get_or_create(
                source_type='arxiv',
                external_id=arxiv_id,
                defaults={
                    'title': metadata['title'],
                    'authors': ', '.join(metadata['authors']),
                    'abstract': metadata['abstract'],
                    'published_date': metadata['published_date'],
                    'pdf_url': metadata['pdf_url'],
                    'entry_url': metadata['entry_url'],
                }
            )
            
            if not created:
                logger.info(f"PaperSource already exists for arXiv:{arxiv_id}")
            
            # 4. Download and ingest PDF if requested
            document_id = None
            if download_pdf:
                # Download PDF
                media_pdf_dir = os.path.join(settings.MEDIA_ROOT, 'pdfs')
                pdf_path = self.download_pdf(arxiv_id, media_pdf_dir)
                
                # Create Document record
                filename = os.path.basename(pdf_path)
                document = Document.objects.create(
                    filename=filename,
                    session=session,
                    title=metadata['title'],
                    abstract=metadata['abstract'],
                    status='UPLOADED'
                )
                document_id = document.id
                
                # Link PaperSource to Document
                paper_source.document = document
                paper_source.imported = True
                paper_source.save()
                
                # Start async ingestion
                logger.info(f"Starting async ingestion for document {document_id}")
                import threading
                def ingest_in_background():
                    self.ingestion_service.ingest_document(document.id, pdf_path)
                
                thread = threading.Thread(target=ingest_in_background, daemon=True)
                thread.start()
            
            return {
                'success': True,
                'paper_source_id': paper_source.id,
                'document_id': document_id,
                'arxiv_id': arxiv_id,
                'title': metadata['title'],
                'status': 'UPLOADED' if download_pdf else 'METADATA_ONLY',
                'message': 'Paper import initiated' if download_pdf else 'Metadata saved (PDF not downloaded)'
            }
        
        except Exception as e:
            logger.error(f"Failed to import arXiv paper {arxiv_id}: {e}")
            raise
    
    def _extract_metadata(self, paper: arxiv.Result) -> Dict:
        """
        Extract metadata from arxiv.Result object.
        
        Args:
            paper: arxiv.Result object
        
        Returns:
            Dictionary with standardized metadata
        """
        return {
            'arxiv_id': paper.entry_id.split('/abs/')[-1],  # Extract ID from URL
            'title': paper.title,
            'authors': [author.name for author in paper.authors],
            'abstract': paper.summary,
            'published_date': paper.published.date(),
            'updated_date': paper.updated.date() if paper.updated else None,
            'pdf_url': paper.pdf_url,
            'entry_url': paper.entry_id,
            'categories': paper.categories,
            'primary_category': paper.primary_category,
            'doi': paper.doi if paper.doi else None,
            'journal_ref': paper.journal_ref if paper.journal_ref else None,
        }
