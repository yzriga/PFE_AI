"""
arXiv API Views

Endpoints for searching and importing papers from arXiv.
"""

import logging

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from rag.services.arxiv_service import ArxivService

logger = logging.getLogger(__name__)


@api_view(['GET'])
def arxiv_search(request):
    """
    Search for papers on arXiv.
    
    Query Parameters:
        q (str): Search query (required)
        max_results (int): Maximum number of results (default: 10, max: 50)
    
    Example:
        GET /api/arxiv/search?q=machine+learning&max_results=5
    
    Response:
        {
            "query": "machine learning",
            "count": 5,
            "results": [
                {
                    "arxiv_id": "2411.04920v4",
                    "title": "Paper Title",
                    "authors": ["Author 1", "Author 2"],
                    "abstract": "...",
                    "published_date": "2025-06-04",
                    "pdf_url": "https://arxiv.org/pdf/2411.04920v4",
                    "entry_url": "https://arxiv.org/abs/2411.04920v4",
                    "categories": ["cs.CL", "cs.AI"],
                    "primary_category": "cs.CL"
                },
                ...
            ]
        }
    """
    query = request.GET.get('q', '').strip()
    if not query:
        return Response(
            {'error': 'Query parameter "q" is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        max_results = int(request.GET.get('max_results', 10))
        max_results = min(max_results, 50)  # Cap at 50 to prevent abuse
    except ValueError:
        return Response(
            {'error': 'Invalid max_results parameter'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        service = ArxivService()
        results = service.search(query, max_results)
        
        return Response({
            'query': query,
            'count': len(results),
            'results': results
        })
    
    except Exception as e:
        logger.error(f"arXiv search failed: {e}")
        return Response(
            {'error': f'Search failed: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
def arxiv_import(request):
    """
    Import a paper from arXiv into a session.
    
    Request Body:
        {
            "arxiv_id": "2411.04920v4",  // required
            "session": "my-session",      // required
            "download_pdf": true          // optional, default: true
        }
    
    Response (202 Accepted):
        {
            "success": true,
            "paper_source_id": 1,
            "document_id": 42,
            "arxiv_id": "2411.04920v4",
            "title": "Paper Title",
            "status": "UPLOADED",
            "message": "Paper import initiated"
        }
    
    Note: PDF download and ingestion happen asynchronously.
    Use GET /api/documents/<document_id>/status/ to monitor progress.
    """
    arxiv_id = request.data.get('arxiv_id', '').strip()
    session_name = request.data.get('session', '').strip()
    download_pdf = request.data.get('download_pdf', True)
    
    # Validation
    if not arxiv_id:
        return Response(
            {'error': 'Field "arxiv_id" is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not session_name:
        return Response(
            {'error': 'Field "session" is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    try:
        service = ArxivService()
        result = service.import_paper(
            arxiv_id=arxiv_id,
            session_name=session_name,
            download_pdf=download_pdf
        )
        
        return Response(result, status=status.HTTP_202_ACCEPTED)
    
    except ValueError as e:
        # Paper not found or invalid ID
        return Response(
            {'error': str(e)},
            status=status.HTTP_404_NOT_FOUND
        )
    
    except Exception as e:
        logger.error(f"arXiv import failed: {e}")
        return Response(
            {'error': f'Import failed: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
def arxiv_metadata(request, arxiv_id):
    """
    Fetch metadata for a specific arXiv paper without importing.
    
    URL Parameter:
        arxiv_id (str): arXiv identifier
    
    Example:
        GET /api/arxiv/metadata/2411.04920v4
    
    Response:
        {
            "arxiv_id": "2411.04920v4",
            "title": "Paper Title",
            "authors": ["Author 1", "Author 2"],
            "abstract": "...",
            "published_date": "2025-06-04",
            "pdf_url": "https://arxiv.org/pdf/2411.04920v4",
            ...
        }
    """
    try:
        service = ArxivService()
        metadata = service.fetch_metadata(arxiv_id)
        
        return Response(metadata)
    
    except ValueError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_404_NOT_FOUND
        )
    
    except Exception as e:
        logger.error(f"Failed to fetch arXiv metadata: {e}")
        return Response(
            {'error': f'Failed to fetch metadata: {str(e)}'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
