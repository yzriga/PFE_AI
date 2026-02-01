from pathlib import Path

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Session, Document, Question, Answer
from .utils import get_default_session
from .query import ask_with_citations
from .ingest import ingest_pdf


@api_view(["POST"])
def ask_question(request):
    """
    Ask a question over the ingested scientific documents.

    Expected JSON payload:
    {
        "question": "...",
        "session": "SessionA",
        "sources": ["paper.pdf"]   // optional
    }
    """
    question_text = request.data.get("question")
    session_name = request.data.get("session")
    sources = request.data.get("sources")

    if not question_text:
        return Response(
            {"error": "Missing 'question' field"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Resolve session
    session = (
        Session.objects.get(name=session_name)
        if session_name
        else get_default_session()
    )

    # Persist question
    question_obj = Question.objects.create(
        text=question_text,
        session=session
    )

    # Ask RAG (session + optional source restriction)
    result = ask_with_citations(
        question=question_text,
        session_name=session.name,
        sources=sources
    )

    # Persist answer
    Answer.objects.create(
        question=question_obj,
        text=result["answer"],
        citations=result["citations"]
    )

    return Response(
        {
            "answer": result["answer"],
            "citations": result["citations"]
        },
        status=status.HTTP_200_OK
    )


@api_view(["POST"])
def upload_pdf(request):
    """
    Upload a PDF file and ingest it into a session-scoped vector database.

    Expected form-data:
    - file: PDF
    - session: Session name (optional)
    """
    file = request.FILES.get("file")
    session_name = request.POST.get("session")

    if not file:
        return Response(
            {"error": "No file provided"},
            status=status.HTTP_400_BAD_REQUEST
        )

    if not file.name.lower().endswith(".pdf"):
        return Response(
            {"error": "Only PDF files are allowed"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Resolve session
    session = (
        Session.objects.get(name=session_name)
        if session_name
        else get_default_session()
    )

    # Save file
    saved_path = default_storage.save(
        f"pdfs/{file.name}",
        ContentFile(file.read())
    )

    full_path = Path(default_storage.path(saved_path))
    original_filename = file.name  # THIS is what users see


    # Register document in relational DB
    Document.objects.get_or_create(
        filename=file.name,
        session=session
    )

    # Ingest into session-scoped vector store
    ingest_pdf(
        path=str(full_path),
        session_name=session.name,
        source_name=original_filename
    )

    return Response(
        {
            "message": "PDF uploaded and ingested successfully",
            "filename": file.name,
            "session": session.name
        },
        status=status.HTTP_201_CREATED
    )


@api_view(["GET"])
def list_pdfs(request):
    """
    List PDFs available in a session.
    """
    session_name = request.GET.get("session")

    session = (
        Session.objects.get(name=session_name)
        if session_name
        else get_default_session()
    )

    pdfs = session.documents.values_list("filename", flat=True)

    return Response(
        {
            "session": session.name,
            "pdfs": list(pdfs),
        },
        status=status.HTTP_200_OK
    )
