"""
arXiv API Views
"""
import logging
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from .services.arxiv_service import ArxivService

logger = logging.getLogger(__name__)

@api_view(['GET'])
def arxiv_search(request):
    query = request.GET.get('q', '').strip()
    if not query:
        return Response({'error': 'Query parameter "q" is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        max_results = int(request.GET.get('max_results', 10))
        max_results = min(max_results, 50)
    except ValueError:
        return Response({'error': 'Invalid max_results parameter'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        service = ArxivService()
        results = service.search(query, max_results)
        return Response({'query': query, 'count': len(results), 'results': results})
    except Exception as e:
        logger.error(f"arXiv search failed: {e}")
        return Response({'error': f'Search failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
def arxiv_import(request):
    arxiv_id = request.data.get('arxiv_id', '').strip()
    session_name = request.data.get('session', '').strip()
    download_pdf = request.data.get('download_pdf', True)

    if not arxiv_id:
        return Response({'error': 'arxiv_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    from .models import Session
    from .utils import get_default_session

    try:
        session = (
            Session.objects.get(name=session_name)
            if session_name
            else get_default_session()
        )
    except Session.DoesNotExist:
        return Response({'error': f'Session {session_name} not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        service = ArxivService()
        result = service.import_paper(arxiv_id=arxiv_id, session_name=session.name, download_pdf=download_pdf)
        return Response(result, status=status.HTTP_202_ACCEPTED)
    except Exception as e:
        logger.error(f"arXiv import failed: {e}")
        return Response({'error': f'Import failed: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
