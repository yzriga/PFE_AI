"""
API views for highlights and annotations (D5).

Provides CRUD operations for user highlights with:
- Text selection with page/offset positioning
- User notes and tags
- Semantic embedding for retrieval integration
"""

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from .models import Document, Highlight, HighlightEmbedding
from .services.highlight_service import HighlightService


@api_view(['POST'])
def create_highlight(request):
    """
    Create a new highlight/annotation on a document.
    
    POST /api/highlights/
    Body:
    {
      "document_id": 123,
      "page": 5,
      "start_offset": 100,
      "end_offset": 250,
      "text": "Selected text from document",
      "note": "My personal note about this passage",
      "tags": ["important", "methodology"]
    }
    
    Response 201:
    {
      "id": 45,
      "document_id": 123,
      "page": 5,
      "start_offset": 100,
      "end_offset": 250,
      "text": "Selected text...",
      "note": "My personal note...",
      "tags": ["important", "methodology"],
      "embedded": true,
      "embedding_id": "highlight_45_abc123",
      "created_at": "2026-02-09T10:30:00Z",
      "updated_at": "2026-02-09T10:30:00Z"
    }
    """
    # Validate required fields
    required_fields = ['document_id', 'page', 'start_offset', 'end_offset', 'text']
    for field in required_fields:
        if field not in request.data:
            return Response(
                {"error": f"Missing required field: {field}"},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    # Validate document exists
    document_id = request.data.get('document_id')
    try:
        document = Document.objects.get(id=document_id)
    except Document.DoesNotExist:
        return Response(
            {"error": f"Document {document_id} not found"},
            status=status.HTTP_404_NOT_FOUND
        )
    
    # Validate page number
    page = request.data.get('page')
    if document.page_count and page > document.page_count:
        return Response(
            {"error": f"Page {page} exceeds document page count ({document.page_count})"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Create highlight
    highlight = Highlight.objects.create(
        document=document,
        page=page,
        start_offset=request.data.get('start_offset'),
        end_offset=request.data.get('end_offset'),
        text=request.data.get('text'),
        note=request.data.get('note', ''),
        tags=request.data.get('tags', [])
    )
    
    # Create embedding for semantic retrieval
    highlight_service = HighlightService()
    embedding_id = highlight_service.embed_highlight(highlight)
    
    # Return created highlight
    return Response({
        "id": highlight.id,
        "document_id": highlight.document.id,
        "page": highlight.page,
        "start_offset": highlight.start_offset,
        "end_offset": highlight.end_offset,
        "text": highlight.text,
        "note": highlight.note,
        "tags": highlight.tags,
        "embedded": embedding_id is not None,
        "embedding_id": embedding_id,
        "created_at": highlight.created_at,
        "updated_at": highlight.updated_at
    }, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def list_highlights(request):
    """
    List highlights with optional filtering.
    
    GET /api/highlights/?document_id=123&tag=important&page=5
    
    Query params:
    - document_id: Filter by document
    - tag: Filter by tag (exact match)
    - page: Filter by page number
    
    Response 200:
    {
      "count": 5,
      "highlights": [
        {
          "id": 45,
          "document_id": 123,
          "document_filename": "paper.pdf",
          "page": 5,
          "text": "...",
          "note": "...",
          "tags": [...],
          "created_at": "...",
          "updated_at": "..."
        }
      ]
    }
    """
    # Start with all highlights
    highlights = Highlight.objects.all()
    
    # Apply filters
    document_id = request.query_params.get('document_id')
    if document_id:
        highlights = highlights.filter(document_id=document_id)
    
    page = request.query_params.get('page')
    if page:
        highlights = highlights.filter(page=int(page))
    
    # Order by document, page, position
    highlights = highlights.order_by('document', 'page', 'start_offset')
    
    # Apply tag filter (in Python to avoid SQLite JSON issues)
    tag = request.query_params.get('tag')
    
    # Serialize
    result = []
    for h in highlights:
        # Filter by tag if specified
        if tag and tag not in h.tags:
            continue
            
        result.append({
            "id": h.id,
            "document_id": h.document.id,
            "document_filename": h.document.filename,
            "page": h.page,
            "start_offset": h.start_offset,
            "end_offset": h.end_offset,
            "text": h.text,
            "note": h.note,
            "tags": h.tags,
            "created_at": h.created_at,
            "updated_at": h.updated_at
        })
    
    return Response({
        "count": len(result),
        "highlights": result
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
def get_highlight(request, highlight_id):
    """
    Get a single highlight by ID.
    
    GET /api/highlights/<id>/
    
    Response 200:
    {
      "id": 45,
      "document_id": 123,
      "document_filename": "paper.pdf",
      "page": 5,
      ...
    }
    """
    highlight = get_object_or_404(Highlight, id=highlight_id)
    
    return Response({
        "id": highlight.id,
        "document_id": highlight.document.id,
        "document_filename": highlight.document.filename,
        "page": highlight.page,
        "start_offset": highlight.start_offset,
        "end_offset": highlight.end_offset,
        "text": highlight.text,
        "note": highlight.note,
        "tags": highlight.tags,
        "created_at": highlight.created_at,
        "updated_at": highlight.updated_at
    }, status=status.HTTP_200_OK)


@api_view(['PUT', 'PATCH'])
def update_highlight(request, highlight_id):
    """
    Update a highlight's note and/or tags.
    
    PUT/PATCH /api/highlights/<id>/
    Body:
    {
      "note": "Updated note",
      "tags": ["important", "revised"]
    }
    
    Response 200:
    {
      "id": 45,
      ...
    }
    
    Note: Text and position fields are immutable after creation.
    """
    highlight = get_object_or_404(Highlight, id=highlight_id)
    
    # Update mutable fields only
    if 'note' in request.data:
        highlight.note = request.data['note']
    
    if 'tags' in request.data:
        highlight.tags = request.data['tags']
    
    highlight.save()
    
    # Re-embed if note changed significantly
    if 'note' in request.data and request.data['note']:
        highlight_service = HighlightService()
        highlight_service.update_embedding(highlight)
    
    return Response({
        "id": highlight.id,
        "document_id": highlight.document.id,
        "document_filename": highlight.document.filename,
        "page": highlight.page,
        "start_offset": highlight.start_offset,
        "end_offset": highlight.end_offset,
        "text": highlight.text,
        "note": highlight.note,
        "tags": highlight.tags,
        "created_at": highlight.created_at,
        "updated_at": highlight.updated_at
    }, status=status.HTTP_200_OK)


@api_view(['DELETE'])
def delete_highlight(request, highlight_id):
    """
    Delete a highlight and its embedding.
    
    DELETE /api/highlights/<id>/
    
    Response 204: (no content)
    """
    highlight = get_object_or_404(Highlight, id=highlight_id)
    
    # Delete embedding from ChromaDB first
    highlight_service = HighlightService()
    highlight_service.delete_embedding(highlight)
    
    # Delete highlight (cascade deletes HighlightEmbedding)
    highlight.delete()
    
    return Response(status=status.HTTP_204_NO_CONTENT)
