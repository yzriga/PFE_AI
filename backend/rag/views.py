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

from .router import is_title_question, is_about_paper_question, is_page_count_question

@api_view(["POST"])
def ask_question(request):
    question_text = request.data.get("question")
    session_name = request.data.get("session")
    sources = request.data.get("sources") or []

    if not question_text:
        return Response(
            {"error": "Missing 'question'"},
            status=status.HTTP_400_BAD_REQUEST
        )

    # Normalize sources
    sources = [normalize_filename(s) for s in sources]

    # Resolve session
    try:
        session = (
            Session.objects.get(name=session_name)
            if session_name
            else get_default_session()
        )
    except Session.DoesNotExist:
        return Response(
            {"error": f"Session '{session_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    question_obj = Question.objects.create(
        text=question_text,
        session=session
    )

    try:
        # ===== METADATA QUESTIONS =====
        if is_title_question(question_text) and sources:
            doc = Document.objects.get(
                session=session,
                filename=sources[0]
            )
            answer_text = doc.title or "Title not available."

            result = {
                "answer": answer_text,
                "citations": []
            }

        elif is_page_count_question(question_text) and sources:
            doc = Document.objects.get(
                session=session,
                filename=sources[0]
            )
            count = doc.page_count or "unknown"
            result = {
                "answer": f"The document '{doc.filename}' has {count} pages.",
                "citations": []
            }

        elif is_about_paper_question(question_text) and sources:
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

        else:
            # ===== DEFAULT RAG =====
            result = ask_with_citations(
                question=question_text,
                session_name=session.name,
                sources=sources or None,
            )

        Answer.objects.create(
            question=question_obj,
            text=result["answer"],
            citations=result["citations"]
        )

        return Response(result, status=status.HTTP_200_OK)

    except Exception as e:
        # 🔒 GUARANTEED JSON ERROR
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
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
    try:
        session = (
            Session.objects.get(name=session_name)
            if session_name
            else get_default_session()
        )
    except Session.DoesNotExist:
        return Response(
            {"error": f"Session '{session_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
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

    try:
        session = (
            Session.objects.get(name=session_name)
            if session_name
            else get_default_session()
        )
    except Session.DoesNotExist:
        return Response(
            {"error": f"Session '{session_name}' not found."},
            status=status.HTTP_404_NOT_FOUND
        )

    # pdfs = session.documents.values_list("filename", flat=True)

    pdfs = session.documents.values(
        "filename",
        "title",
        "abstract"
    )


    return Response(
        {
            "session": session.name,
            "pdfs": list(pdfs),
        },
        status=status.HTTP_200_OK
    )


@api_view(["POST"])
def create_session(request):
    name = request.data.get("name")

    if not name:
        return Response(
            {"error": "Session name required"},
            status=status.HTTP_400_BAD_REQUEST
        )

    session, created = Session.objects.get_or_create(name=name)

    return Response(
        {
            "session": session.name,
            "created": created
        },
        status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
    )


@api_view(["GET"])
def list_sessions(request):
    sessions = Session.objects.all().order_by("-created_at")
    data = [{"name": s.name, "created_at": s.created_at} for s in sessions]
    return Response(data, status=status.HTTP_200_OK)


@api_view(["DELETE"])
def delete_session(request, session_name):
    try:
        session = Session.objects.get(name=session_name)
        # Chroma cleanup: get the path and delete the directory
        import shutil
        from .utils import get_session_path
        persist_dir = get_session_path(session_name)
        if Path(persist_dir).exists():
            shutil.rmtree(persist_dir)
            
        # Filesystem cleanup: potentially delete all PDFs unique to this session
        for doc in session.documents.all():
            other_uses = Document.objects.filter(filename=doc.filename).exclude(id=doc.id).exists()
            if not other_uses:
                file_path = f"pdfs/{doc.filename}"
                if default_storage.exists(file_path):
                    default_storage.delete(file_path)
        
        session.delete()
        return Response({"message": "Session and all associated data deleted"}, status=status.HTTP_200_OK)
    except Session.DoesNotExist:
        return Response({"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
@api_view(["DELETE"])
def delete_pdf(request):
    """
    Remove a PDF from a session:
    1. Delete from relational DB
    2. Delete from Chroma vector store
    3. Cleanup physical file if no other session uses it
    """
    session_name = request.data.get("session")
    filename = request.data.get("filename")

    if not session_name or not filename:
        return Response(
            {"error": "Missing 'session' or 'filename'"},
            status=status.HTTP_400_BAD_REQUEST
        )

    try:
        session = Session.objects.get(name=session_name)
        document = Document.objects.get(session=session, filename=filename)
    except (Session.DoesNotExist, Document.DoesNotExist):
        return Response(
            {"error": "Document or Session not found"},
            status=status.HTTP_404_NOT_FOUND
        )

    # 1. Delete from Chroma
    from langchain_chroma import Chroma
    from langchain_ollama import OllamaEmbeddings
    from .utils import get_session_path

    persist_dir = get_session_path(session_name)
    embeddings = OllamaEmbeddings(model="nomic-embed-text")
    vectordb = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings
    )

    try:
        # Get IDs of documents to delete
        res = vectordb.get(where={"source": filename})
        if res["ids"]:
            vectordb.delete(ids=res["ids"])
    except Exception as e:
        print(f"Error deleting from Chroma: {e}")

    # 2. Delete from Filesystem
    file_path = f"pdfs/{filename}"
    other_uses = Document.objects.filter(filename=filename).exclude(id=document.id).exists()
    if not other_uses:
        if default_storage.exists(file_path):
            default_storage.delete(file_path)

    # 3. Delete from Relational DB
    document.delete()

    return Response(
        {"message": f"Document '{filename}' deleted successfully"},
        status=status.HTTP_200_OK
    )
