from pathlib import Path

from django.core.files.storage import default_storage
from django.core.files.base import ContentFile

from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status

from .models import Session, Document, Question, Answer
from .utils import get_default_session, normalize_filename
from .query import ask_with_citations, retrieve_paper_overview
from .ingest import ingest_pdf

from .router import is_title_question, is_about_paper_question

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

    if sources:
        sources = [normalize_filename(s) for s in sources]

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

    if sources and is_title_question(question_text):
        doc = Document.objects.filter(
            session=session,
            filename=sources[0]
        ).first()

        if doc and doc.title:
            Answer.objects.create(
                question=question_obj,
                text=doc.title,
                citations=[
                    {
                        "source": doc.filename,
                        "page": 0
                    }
                ]
            )

            return Response(
                {
                    "answer": doc.title,
                    "citations": [
                        {
                            "source": doc.filename,
                            "page": 0
                        }
                    ]
                },
                status=status.HTTP_200_OK
            )

    # 🔹 PAPER OVERVIEW ROUTING
    if sources and is_about_paper_question(question_text):
        docs = retrieve_paper_overview(
            question=question_text,
            session_name=session.name,
            source=sources[0],
        )

        result = ask_with_citations(
            question=question_text,
            session_name=session.name,
            docs_override=docs,
        )

        Answer.objects.create(
            question=question_obj,
            text=result["answer"],
            citations=result["citations"],
        )

        return Response(
            {
                "answer": result["answer"],
                "citations": result["citations"],
            },
            status=status.HTTP_200_OK,
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
    normalized = normalize_filename(file.name)

    document, _ = Document.objects.get_or_create(
        filename=normalized,
        session=session
    )

    # Ingest into session-scoped vector store
    ingest_pdf(
        path=str(full_path),
        session_name=session.name,
        document=document
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
