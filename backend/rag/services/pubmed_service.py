"""
PubMed Connector Service

Provides functionality to:
- Search papers on PubMed/PMC
- Fetch metadata for specific papers
- Download PDFs from PMC (when available)
- Import papers into the system with proper metadata tracking
"""

import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional
import threading

from Bio import Entrez
import requests
from django.conf import settings

from rag.models import PaperSource, Document, Session
from rag.services.ingestion import IngestionService

logger = logging.getLogger(__name__)

# Configure Entrez with your email (required by NCBI)
Entrez.email = "your.email@example.com"  # TODO: Move to settings
Entrez.tool = "ScientificResearchNavigator"


class PubmedService:
    """Service for interacting with PubMed/PMC API and importing papers."""
    
    def __init__(self):
        self.ingestion_service = IngestionService()
    
    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search PubMed for papers matching the query.
        
        Args:
            query: Search query (e.g., "cancer treatment", "COVID-19[Title]")
            max_results: Maximum number of results to return
        
        Returns:
            List of paper metadata dictionaries
        """
        logger.info(f"Searching PubMed: query='{query}', max_results={max_results}")
        
        try:
            # Search PubMed
            handle = Entrez.esearch(
                db="pubmed",
                term=query,
                retmax=max_results,
                sort="relevance"
            )
            search_results = Entrez.read(handle)
            handle.close()
            
            pmids = search_results.get("IdList", [])
            
            if not pmids:
                logger.info("No papers found")
                return []
            
            # Fetch metadata for all PMIDs
            handle = Entrez.efetch(
                db="pubmed",
                id=",".join(pmids),
                rettype="medline",
                retmode="xml"
            )
            records = Entrez.read(handle)
            handle.close()
            
            results = []
            for article_data in records.get("PubmedArticle", []):
                results.append(self._extract_metadata(article_data))
            
            logger.info(f"Found {len(results)} papers on PubMed")
            return results
        
        except Exception as e:
            logger.error(f"PubMed search failed: {e}")
            raise
    
    def fetch_metadata(self, pmid: str) -> Dict:
        """
        Fetch metadata for a specific PubMed paper.
        
        Args:
            pmid: PubMed identifier (e.g., "12345678")
        
        Returns:
            Paper metadata dictionary
        """
        logger.info(f"Fetching metadata for PMID:{pmid}")
        
        try:
            handle = Entrez.efetch(
                db="pubmed",
                id=pmid,
                rettype="medline",
                retmode="xml"
            )
            records = Entrez.read(handle)
            handle.close()
            
            if not records.get("PubmedArticle"):
                raise ValueError(f"Paper with PMID '{pmid}' not found")
            
            metadata = self._extract_metadata(records["PubmedArticle"][0])
            logger.info(f"Retrieved metadata for '{metadata['title'][:50]}...'")
            return metadata
        
        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to fetch PubMed metadata: {e}")
            raise
    
    def check_pmc_availability(self, pmid: str) -> Optional[str]:
        """
        Check if full-text PDF is available on PMC.
        
        Args:
            pmid: PubMed identifier
        
        Returns:
            PMC ID if available, None otherwise
        """
        try:
            # Convert PMID to PMCID
            handle = Entrez.elink(
                dbfrom="pubmed",
                id=pmid,
                linkname="pubmed_pmc"
            )
            results = Entrez.read(handle)
            handle.close()
            
            if results and results[0].get("LinkSetDb"):
                links = results[0]["LinkSetDb"][0].get("Link", [])
                if links:
                    pmcid = links[0]["Id"]
                    logger.info(f"PMC full-text available: PMC{pmcid}")
                    return pmcid
            
            logger.info(f"No PMC full-text available for PMID:{pmid}")
            return None
        
        except Exception as e:
            logger.warning(f"Error checking PMC availability: {e}")
            return None
    
    def download_pdf(self, pmid: str, save_dir: str) -> Optional[str]:
        """
        Download PDF from PMC if available.
        
        Args:
            pmid: PubMed identifier
            save_dir: Directory to save the PDF
        
        Returns:
            Path to the downloaded PDF file, or None if not available
        """
        logger.info(f"Attempting to download PDF for PMID:{pmid}")
        
        try:
            pmcid = self.check_pmc_availability(pmid)
            
            if not pmcid:
                logger.warning(f"PDF not available for PMID:{pmid} (not in PMC)")
                return None
            
            # Try to download from PMC OA service
            pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/pdf/"
            
            # Create save directory
            Path(save_dir).mkdir(parents=True, exist_ok=True)
            
            # Fetch metadata for filename
            metadata = self.fetch_metadata(pmid)
            safe_title = "".join(c for c in metadata['title'] if c.isalnum() or c in (' ', '-', '_'))[:80]
            filename = f"PMID{pmid}_{safe_title}.pdf"
            filepath = os.path.join(save_dir, filename)
            
            # Download PDF
            response = requests.get(pdf_url, timeout=30, stream=True)
            response.raise_for_status()
            
            with open(filepath, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            logger.info(f"PDF downloaded successfully: {filepath}")
            return filepath
        
        except requests.RequestException as e:
            logger.error(f"PDF download failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error downloading PDF: {e}")
            return None
    
    def import_paper(
        self,
        pmid: str,
        session_name: str,
        download_pdf: bool = True
    ) -> Dict:
        """
        Import a PubMed paper into the system.
        
        Steps:
        1. Fetch metadata from PubMed
        2. Create/update PaperSource record
        3. Download PDF from PMC (if available and requested)
        4. Create Document and ingest (async)
        
        Args:
            pmid: PubMed identifier
            session_name: Name of the session to import into
            download_pdf: Whether to attempt PDF download
        
        Returns:
            Dict with import results
        """
        logger.info(f"Importing PubMed paper PMID:{pmid} into session '{session_name}'")
        
        try:
            # Fetch metadata
            metadata = self.fetch_metadata(pmid)
            
            # Get or create session
            session, _ = Session.objects.get_or_create(name=session_name)
            
            # Create or update PaperSource
            paper_source, created = PaperSource.objects.get_or_create(
                source_type='pubmed',
                external_id=pmid,
                defaults={
                    'title': metadata['title'],
                    'authors': ", ".join(metadata.get('authors', [])),
                    'abstract': metadata.get('abstract', ''),
                    'published_date': metadata.get('published_date'),
                    'entry_url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                    'pdf_url': metadata.get('pmc_url', ''),
                }
            )
            
            if not created:
                logger.info(f"Paper source already exists (ID: {paper_source.id})")
            
            document_id = None
            status = 'METADATA_ONLY'
            message = 'Metadata saved'
            
            if download_pdf:
                # Attempt PDF download
                media_pdf_dir = os.path.join(settings.MEDIA_ROOT, 'pdfs')
                pdf_path = self.download_pdf(pmid, media_pdf_dir)
                
                if pdf_path:
                    # Create Document record
                    document = Document.objects.create(
                        filename=os.path.basename(pdf_path),
                        session=session,
                        status='UPLOADED',
                        title=metadata['title'],
                        abstract=metadata.get('abstract', '')[:500],
                    )
                    
                    document_id = document.id
                    paper_source.document = document
                    paper_source.imported = True
                    paper_source.save()
                    
                    # Start async ingestion
                    logger.info(f"Starting async ingestion for document {document_id}")
                    def ingest_in_background():
                        self.ingestion_service.ingest_document(document.id, pdf_path)
                    
                    thread = threading.Thread(target=ingest_in_background, daemon=True)
                    thread.start()
                    
                    status = 'UPLOADED'
                    message = 'Paper import initiated (PDF available)'
                else:
                    logger.warning(f"PDF not available for PMID:{pmid}, metadata only saved")
                    message = 'Metadata saved (PDF not available in PMC)'
            
            return {
                'success': True,
                'paper_source_id': paper_source.id,
                'document_id': document_id,
                'pmid': pmid,
                'title': metadata['title'],
                'status': status,
                'message': message,
                'pmc_available': metadata.get('pmc_id') is not None
            }
        
        except Exception as e:
            logger.error(f"Failed to import PubMed paper {pmid}: {e}")
            raise
    
    def _extract_metadata(self, article_data: Dict) -> Dict:
        """
        Extract metadata from PubMed XML response.
        
        Args:
            article_data: Parsed PubmedArticle dictionary
        
        Returns:
            Dictionary with standardized metadata
        """
        medline = article_data.get("MedlineCitation", {})
        article = medline.get("Article", {})
        
        # Extract basic info
        pmid = str(medline.get("PMID", ""))
        title = article.get("ArticleTitle", "")
        
        # Extract authors
        authors = []
        author_list = article.get("AuthorList", [])
        for author in author_list:
            if author.get("LastName") and author.get("ForeName"):
                authors.append(f"{author['ForeName']} {author['LastName']}")
            elif author.get("CollectiveName"):
                authors.append(author["CollectiveName"])
        
        # Extract abstract
        abstract_sections = article.get("Abstract", {}).get("AbstractText", [])
        if isinstance(abstract_sections, list):
            abstract = " ".join([str(section) for section in abstract_sections])
        else:
            abstract = str(abstract_sections) if abstract_sections else ""
        
        # Extract publication date
        pub_date = article.get("Journal", {}).get("JournalIssue", {}).get("PubDate", {})
        year = pub_date.get("Year", "")
        month = pub_date.get("Month", "01")
        day = pub_date.get("Day", "01")
        
        published_date = None
        if year:
            try:
                # Convert month name to number if needed
                month_map = {
                    'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                    'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                    'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'
                }
                month_num = month_map.get(month, month) if not month.isdigit() else month
                published_date = f"{year}-{month_num.zfill(2)}-{str(day).zfill(2)}"
                # Validate date
                datetime.strptime(published_date, "%Y-%m-%d")
            except (ValueError, KeyError):
                published_date = f"{year}-01-01"
        
        # Extract journal info
        journal = article.get("Journal", {})
        journal_title = journal.get("Title", "")
        journal_issue = journal.get("JournalIssue", {})
        volume = journal_issue.get("Volume", "")
        issue = journal_issue.get("Issue", "")
        
        # Extract pagination
        pagination = article.get("Pagination", {})
        pages = pagination.get("MedlinePgn", "")
        
        # Extract DOI
        doi = None
        article_ids = article_data.get("PubmedData", {}).get("ArticleIdList", [])
        for article_id in article_ids:
            if article_id.attributes.get("IdType") == "doi":
                doi = str(article_id)
                break
        
        # Extract PMC ID
        pmc_id = None
        for article_id in article_ids:
            if article_id.attributes.get("IdType") == "pmc":
                pmc_id = str(article_id).replace("PMC", "")
                break
        
        # Extract MeSH terms
        mesh_terms = []
        mesh_list = medline.get("MeshHeadingList", [])
        for mesh in mesh_list:
            descriptor = mesh.get("DescriptorName", "")
            if descriptor:
                mesh_terms.append(str(descriptor))
        
        return {
            'pmid': pmid,
            'title': title,
            'authors': authors,
            'abstract': abstract,
            'published_date': published_date,
            'journal': journal_title,
            'volume': volume,
            'issue': issue,
            'pages': pages,
            'doi': doi,
            'pmc_id': pmc_id,
            'mesh_terms': mesh_terms[:10],  # Limit to first 10
            'pubmed_url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            'pmc_url': f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/" if pmc_id else None,
        }
