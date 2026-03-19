import logging
import requests
import time
from typing import List, Dict, Optional
from .semanticscholar_service import SemanticScholarService

logger = logging.getLogger(__name__)

class MedRxivService(SemanticScholarService):
    """
    Service for interacting with medRxiv.
    Uses Semantic Scholar as the search engine with medRxiv filtering.
    """

    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search medRxiv via Semantic Scholar.
        """
        logger.info(f"Searching medRxiv: query='{query}'")

        try:
            url = f"{self.BASE_URL}/paper/search"
            params = {
                "query": query,
                "limit": min(max_results * 2, 50),
                "fields": "title,authors,abstract,url,year,externalIds,openAccessPdf,venue",
                "venue": "medRxiv,bioRxiv"
            }
            
            data = self._safe_request(url, params)
            results = []
            for paper in data.get("data", []):
                meta = self._extract_metadata(paper)
                
                # Fix Entry URL to point to medRxiv if DOI is present
                doi = paper.get("externalIds", {}).get("DOI")
                if doi and "10.1101" in doi:
                    meta["entry_url"] = f"https://www.medrxiv.org/content/{doi}v1"
                    
                results.append(meta)
                if len(results) >= max_results:
                    break

            return results


        except Exception as e:
            logger.error(f"medRxiv search failed: {e}")
            raise

    def import_paper(self, paper_id: str, session_name: str) -> Dict:
        # Reuse SS import logic but specify source_type
        return super().import_paper(paper_id, session_name, source_type='medrxiv')

