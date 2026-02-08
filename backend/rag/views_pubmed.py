"""
API Views for PubMed Connector

Provides REST endpoints for:
- Searching PubMed
- Importing papers from PubMed/PMC
- Fetching paper metadata
"""

import logging
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from rag.services.pubmed_service import PubmedService

logger = logging.getLogger(__name__)


@api_view(['GET'])
def pubmed_search(request):
    """
    Search PubMed for papers.
    
    Query parameters:
        q (str): Search query (required)
        max (int): Maximum results to return (default: 10, max: 50)
    
    Returns:
        JSON response with search results
    
    Example:
        GET /api/pubmed/search/?q=cancer+treatment&max=5
    """
    query = request.GET.get('q')
    if not query:
        return Response(
            {'error': 'Query parameter "q" is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    max_results = request.GET.get('max', 10)
    try:
        max_results = int(max_results)
        if max_results < 1 or max_results > 50:
            max_results = 10
    except ValueError:
        max_results = 10
    
    try:
        service = PubmedService()
        results = service.search(query, max_results)
        
        return Response({
            'query': query,
            'count': len(results),
            'results': results
        })
    
    except Exception as e:
        logger.error(f"PubMed search failed: {e}")
        return Response(
            {'error': f'Search failed: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def pubmed_import(request):
    """
    Import a paper from PubMed into a session.
    
    Request body (JSON):
        pmid (str): PubMed ID (required)
        session (str): Session name (required)
        download_pdf (bool): Whether to download PDF from PMC (default: true)
    
    Returns:
        JSON response with import status (202 Accepted if successful)
    
    Example:
        POST /api/pubmed/import/
        {
            "pmid": "12345678",
            "session": "medical-research",
            "download_pdf": true
        }
    """
    pmid = request.data.get('pmid')
    session_name = request.data.get('session')
    download_pdf = request.data.get('download_pdf', True)
    
    if not pmid:
        return Response(
            {'error': 'Field "pmid" is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not session_name:
        return Response(
            {'error': 'Field "session" is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        service = PubmedService()
        result = service.import_paper(
            pmid=pmid,
            session_name=session_name,
            download_pdf=download_pdf
        )
        
        return Response(result, status=status.HTTP_202_ACCEPTED)
    
    except ValueError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"PubMed import failed: {e}")
        return Response(
            {'error': f'Import failed: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def pubmed_metadata(request, pmid):
    """
    Fetch metadata for a specific PubMed paper.
    
    URL parameters:
        pmid (str): PubMed ID
    
    Returns:
        JSON response with paper metadata
    
    Example:
        GET /api/pubmed/metadata/12345678/
    """
    try:
        service = PubmedService()
        metadata = service.fetch_metadata(pmid)
        
        return Response(metadata)
    
    except ValueError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_404_NOT_FOUND
        )
    except Exception as e:
        logger.error(f"Failed to fetch PubMed metadata: {e}")
        return Response(
            {'error': f'Failed to fetch metadata: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def pubmed_check_pmc(request, pmid):
    """
    Check if full-text PDF is available on PMC for a given PMID.
    
    URL parameters:
        pmid (str): PubMed ID
    
    Returns:
        JSON response with PMC availability status
    
    Example:
        GET /api/pubmed/check-pmc/12345678/
    """
    try:
        service = PubmedService()
        pmc_id = service.check_pmc_availability(pmid)
        
        return Response({
            'pmid': pmid,
            'pmc_available': pmc_id is not None,
            'pmc_id': pmc_id,
            'pmc_url': f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmc_id}/" if pmc_id else None
        })
    
    except Exception as e:
        logger.error(f"Failed to check PMC availability: {e}")
        return Response(
            {'error': f'Failed to check PMC: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
