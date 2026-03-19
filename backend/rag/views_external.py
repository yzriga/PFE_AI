"""
Unified External Search Views
"""
import logging
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .services.arxiv_service import ArxivService
from .services.pubmed_service import PubmedService
from .services.semanticscholar_service import SemanticScholarService
from .services.acl_service import ACLService
from .services.medrxiv_service import MedRxivService
from .services.openalex_service import OpenAlexService
from .services.europepmc_service import EuropePmcService
from .services.resilience import CircuitOpenError, TransientExternalError

logger = logging.getLogger(__name__)

@api_view(['GET'])
def external_search(request):
    """
    Unified search endpoint.
    Params: 
    - q: Query
    - source: 'openalex', 'europepmc', 'arxiv', 'pubmed', 'semanticscholar', 'acl', or 'medrxiv'
    """
    query = request.GET.get('q', '').strip()
    provider = request.GET.get('source', 'arxiv').lower()
    max_results = int(request.GET.get('max_results', 10))

    if not query:
        return Response({'error': 'Query parameter "q" is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        if provider == 'openalex':
            service = OpenAlexService()
        elif provider == 'europepmc':
            service = EuropePmcService()
        elif provider == 'arxiv':
            service = ArxivService()
        elif provider == 'pubmed':
            service = PubmedService()
        elif provider == 'semanticscholar':
            service = SemanticScholarService()
        elif provider == 'acl':
            service = ACLService()
        elif provider == 'medrxiv':
            service = MedRxivService()
        else:
            return Response({'error': f'Unsupported provider: {provider}'}, status=status.HTTP_400_BAD_REQUEST)


        results = service.search(query, max_results)
        
        # Ensure unified keys for the frontend
        unified_results = []
        for r in results:
            unified_results.append({
                'id': r.get('arxiv_id') or r.get('external_id'),
                'external_id': r.get('external_id'),
                'title': r.get('title'),
                'authors': r.get('authors'),
                'abstract': r.get('abstract'),
                'url': r.get('entry_url'),
                'date': r.get('published_date'),
                'provider': provider
            })

        return Response({
            'query': query,
            'source': provider,
            'results': unified_results
        })

    except TransientExternalError as e:
        logger.warning(f"Transient search failure for {provider}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    except CircuitOpenError as e:
        logger.warning(f"Circuit open for {provider}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as e:
        logger.error(f"Search failed for {provider}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
@api_view(['POST'])
def external_import(request):
    """
    Unified import endpoint.
    Params: 
    - id: Paper ID
    - source: 'openalex', 'europepmc', 'arxiv', 'pubmed', or 'semanticscholar'
    - session: Session name
    """
    paper_id = request.data.get('id', '').strip()
    provider = request.data.get('source', 'arxiv').lower()
    session_name = request.data.get('session', '').strip()

    if not paper_id:
        return Response({'error': 'id is required'}, status=status.HTTP_400_BAD_REQUEST)

    from .models import Session
    from .utils import get_default_session

    # Resolve session
    try:
        session = (
            Session.objects.get(name=session_name)
            if session_name
            else get_default_session()
        )
    except Session.DoesNotExist:
        return Response({'error': f'Session {session_name} not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        if provider == 'openalex':
            service = OpenAlexService()
            result = service.import_paper(work_id=paper_id, session_name=session.name)
        elif provider == 'europepmc':
            service = EuropePmcService()
            result = service.import_paper(paper_id=paper_id, session_name=session.name)
        elif provider == 'arxiv':
            service = ArxivService()
            result = service.import_paper(arxiv_id=paper_id, session_name=session.name)
        elif provider == 'pubmed':
            service = PubmedService()
            result = service.import_paper(pubmed_id=paper_id, session_name=session.name)
        elif provider == 'semanticscholar':
            service = SemanticScholarService()
            result = service.import_paper(paper_id=paper_id, session_name=session.name)
        elif provider == 'acl':
            service = ACLService()
            result = service.import_paper(paper_id=paper_id, session_name=session.name)
        elif provider == 'medrxiv':
            service = MedRxivService()
            result = service.import_paper(paper_id=paper_id, session_name=session.name)
        else:
            return Response({'error': f'Unsupported provider: {provider}'}, status=status.HTTP_400_BAD_REQUEST)


        return Response(result, status=status.HTTP_202_ACCEPTED)

    except TransientExternalError as e:
        logger.warning(f"Transient import failure for {provider}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    except CircuitOpenError as e:
        logger.warning(f"Circuit open for {provider}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    except Exception as e:
        logger.error(f"Import failed for {provider}: {e}")
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
