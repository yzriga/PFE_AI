from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from rag.models import Highlight, Document, Session
from rag.services.highlight_service import HighlightService


def _serialize_highlight(hl: Highlight) -> dict:
    return {
        "id": hl.id,
        "document_id": hl.document_id,
        "filename": hl.document.filename,
        "page": hl.page,
        "start_offset": hl.start_offset,
        "end_offset": hl.end_offset,
        "text": hl.text,
        "note": hl.note,
        "tags": hl.tags,
        "created_at": hl.created_at,
        "updated_at": hl.updated_at,
    }


@api_view(["GET", "POST"])
def highlights(request):
    service = HighlightService()

    if request.method == "GET":
        document_id = request.GET.get("document_id")
        session_name = request.GET.get("session")

        qs = Highlight.objects.select_related("document", "document__session")
        if document_id:
            qs = qs.filter(document_id=document_id)
        if session_name:
            qs = qs.filter(document__session__name=session_name)

        data = [_serialize_highlight(hl) for hl in qs.order_by("-created_at")]
        return Response({"highlights": data}, status=status.HTTP_200_OK)

    # POST create
    document_id = request.data.get("document_id")
    page = int(request.data.get("page", 1))
    text = (request.data.get("text") or "").strip()
    note = (request.data.get("note") or "").strip()
    tags = request.data.get("tags") or []
    start_offset = int(request.data.get("start_offset", 0))
    end_offset = int(request.data.get("end_offset", max(len(text), 1)))

    if not document_id or not text:
        return Response(
            {"error": "document_id and text are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return Response(
            {"error": "Document not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    hl = Highlight.objects.create(
        document=document,
        page=page,
        start_offset=start_offset,
        end_offset=end_offset,
        text=text,
        note=note,
        tags=tags if isinstance(tags, list) else [],
    )

    embedding_indexed = True
    try:
        service.index_highlight(hl)
    except Exception as exc:
        embedding_indexed = False
        # Keep highlight even if embedding backend is unavailable
        hl.note = f"{hl.note}\n[Embedding index failed: {exc}]".strip()
        hl.save(update_fields=["note"])

    payload = _serialize_highlight(hl)
    payload["embedding_indexed"] = embedding_indexed
    return Response(payload, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
def delete_highlight(request, highlight_id: int):
    try:
        hl = Highlight.objects.select_related("document", "document__session").get(
            id=highlight_id
        )
    except Highlight.DoesNotExist:
        return Response(
            {"error": "Highlight not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    service = HighlightService()
    service.delete_highlight_embedding(hl)
    hl.delete()
    return Response({"deleted": True}, status=status.HTTP_200_OK)


@api_view(["GET"])
def search_highlights(request):
    session_name = (request.GET.get("session") or "").strip()
    query = (request.GET.get("q") or "").strip()
    limit = int(request.GET.get("limit", 20))

    if not session_name or not query:
        return Response(
            {"error": "session and q are required"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        session = Session.objects.get(name=session_name)
    except Session.DoesNotExist:
        return Response(
            {"error": "Session not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    service = HighlightService()
    results = service.search_highlights(session=session, query=query, limit=limit)

    return Response(
        {
            "session": session.name,
            "query": query,
            "results": results,
        },
        status=status.HTTP_200_OK,
    )
