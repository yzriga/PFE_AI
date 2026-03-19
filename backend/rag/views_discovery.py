from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from rag.models import Document
from rag.services.discovery import DiscoveryService
from rag.services.openalex_service import OpenAlexService


@api_view(["GET"])
def related_papers(request):
    document_id = request.GET.get("document_id")
    paper_id = (request.GET.get("paper_id") or "").strip()
    limit = int(request.GET.get("limit", 6))

    service = OpenAlexService()
    discovery_service = DiscoveryService()

    try:
        document = None
        if document_id:
            document = Document.objects.select_related("paper_source").get(id=document_id)
            paper_source = getattr(document, "paper_source", None)
            if paper_source and paper_source.source_type == "openalex":
                paper_id = paper_source.external_id
            elif paper_source:
                resolved = service.resolve_best_match(
                    title=document.title or paper_source.title or "",
                    arxiv_id=paper_source.external_id if paper_source.source_type == "arxiv" else "",
                    doi=paper_source.external_id if paper_source.source_type == "doi" else "",
                )
                if resolved.get("external_id"):
                    paper_id = resolved["external_id"]

        if paper_id:
            payload = service.fetch_paper_graph(paper_id, limit=limit)
            if document is not None:
                payload["document"] = {
                    "id": document.id,
                    "filename": document.filename,
                    "title": document.title,
                }
            return Response(payload, status=status.HTTP_200_OK)

        if document is None:
            return Response(
                {"error": "document_id or paper_id is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        query = (document.title or document.abstract or document.filename or "").strip()
        if not query:
            return Response(
                {"error": "No usable metadata found for discovery"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        related = discovery_service.discover_candidates(query, max_results=limit)
        return Response(
            {
                "paper": {
                    "id": None,
                    "title": document.title or document.filename,
                    "authors": [],
                    "year": None,
                    "url": "",
                    "abstract": document.abstract or "",
                    "provider": getattr(getattr(document, "paper_source", None), "source_type", "local"),
                },
                "references": [],
                "citations": [],
                "related": related,
                "graph_source": "multi_provider_fallback",
                "document": {
                    "id": document.id,
                    "filename": document.filename,
                    "title": document.title,
                },
            },
            status=status.HTTP_200_OK,
        )
    except Document.DoesNotExist:
        return Response({"error": "Document not found"}, status=status.HTTP_404_NOT_FOUND)
    except ValueError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
