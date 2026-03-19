import logging
import requests
import time
from typing import List, Dict, Optional
from .semanticscholar_service import SemanticScholarService

logger = logging.getLogger(__name__)

class ACLService(SemanticScholarService):
    """
    Service for interacting with ACL Anthology.
    Uses Semantic Scholar as the search engine with venue filtering.
    """

    def search(self, query: str, max_results: int = 10) -> List[Dict]:
        """
        Search ACL Anthology via Semantic Scholar.
        """
        logger.info(f"Searching ACL Anthology: query='{query}'")

        try:
            url = f"{self.BASE_URL}/paper/search"
            # Using paper search with venue filtering via the API
            # This is more efficient than local filtering on broad results
            params = {
                "query": query,
                "limit": min(max_results * 2, 50), # Get more candidates to filter
                "fields": "title,authors,abstract,url,year,externalIds,openAccessPdf,venue,publicationVenue",
                "venue": "ACL Anthology,EMNLP,NAACL,EACL,COLING,TACL,CL,ACL"
            }
            
            data = self._safe_request(url, params)
            results = []
            
            # Post-filtering to ensure we only get NLP-related conference papers
            acl_keywords = ["acl", "emnlp", "naacl", "eacl", "coling", "anthology", "tacl", "computational linguistics"]
            
            for paper in data.get("data", []):
                venue = (paper.get("venue") or "").lower()
                external_ids = paper.get("externalIds") or {}
                doi = external_ids.get("DOI")
                acl_id = external_ids.get("ACL")
                
                # Identify if it's an ACL paper via venue, ACL ID, or ACL DOI prefix
                is_acl = (
                    any(kw in venue for kw in acl_keywords) or 
                    acl_id is not None or 
                    (doi and ("10.18653" in doi or "10.3115" in doi))
                )
                
                if is_acl:
                    meta = self._extract_metadata(paper)
                    
                    # Redirect Explorer to ACL Anthology if possible
                    if acl_id:
                        meta["entry_url"] = f"https://aclanthology.org/{acl_id}/"
                    elif doi and "10.18653/v1/" in doi:
                        # Extract ACL ID from DOI
                        doi_id = doi.split("10.18653/v1/")[-1]
                        meta["entry_url"] = f"https://aclanthology.org/{doi_id}/"
                    elif doi and "10.3115/v1/" in doi:
                        doi_id = doi.split("10.3115/v1/")[-1]
                        meta["entry_url"] = f"https://aclanthology.org/{doi_id}/"
                        
                    results.append(meta)
                    
                    if len(results) >= max_results:
                        break


            return results


        except Exception as e:
            logger.error(f"ACL Anthology search failed: {e}")
            raise

    def import_paper(self, paper_id: str, session_name: str) -> Dict:
        # Reuse SS import logic but specify source_type
        return super().import_paper(paper_id, session_name, source_type='acl')

