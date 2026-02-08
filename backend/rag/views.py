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
from .services.synthesis import SynthesisService

from .router import is_title_question, is_about_paper_question, is_page_count_question

@api_view(["POST"])
def ask_question(request):
    question_text = request.data.get("question")
    session_name = request.data.get("session")
    sources = request.data.get("sources") or []
    mode = request.data.get("mode", "qa")  # NEW: default to "qa" mode

    if not question_text:
        return Response(
            {"error": "Missing 'question'"},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Validate mode
    if mode not in ["qa", "compare", "lit_review"]:
        return Response(
            {"error": f"Invalid mode '{mode}'. Must be 'qa', 'compare', or 'lit_review'."},
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
        # ===== MULTI-DOCUMENT MODES (NEW) =====
        if mode == "compare":
            from langchain_chroma import Chroma
            from langchain_ollama import OllamaEmbeddings
            from .utils import get_session_path
            
            # Retrieve documents from vector DB
            persist_dir = get_session_path(session.name)
            embeddings = OllamaEmbeddings(model="nomic-embed-text")
            vectordb = Chroma(persist_directory=persist_dir, embedding_function=embeddings)
            
            # Get documents with filtering if sources specified
            if sources:
                docs = vectordb.similarity_search(
                    question_text,
                    k=10,  # Get more docs for comparison
                    filter={"source": {"$in": sources}}
                )
            else:
                docs = vectordb.similarity_search(question_text, k=10)
            
            # Use synthesis service
            synthesis = SynthesisService()
            result = synthesis.compare_papers(
                question=question_text,
                docs=docs,
                sources=sources or None
            )
            
            # Store in Answer with mode info
            Answer.objects.create(
                question=question_obj,
                text=f"[COMPARE MODE] {result.get('topic', question_text)}",
                citations=[]  # Citations embedded in claims structure
            )
            
            return Response(result, status=status.HTTP_200_OK)
        
        elif mode == "lit_review":
            from langchain_chroma import Chroma
            from langchain_ollama import OllamaEmbeddings
            from .utils import get_session_path
            
            # Retrieve documents from vector DB
            persist_dir = get_session_path(session.name)
            embeddings = OllamaEmbeddings(model="nomic-embed-text")
            vectordb = Chroma(persist_directory=persist_dir, embedding_function=embeddings)
            
            # Get documents with filtering if sources specified
            if sources:
                docs = vectordb.similarity_search(
                    question_text,
                    k=15,  # Get more docs for comprehensive review
                    filter={"source": {"$in": sources}}
                )
            else:
                docs = vectordb.similarity_search(question_text, k=15)
            
            # Use synthesis service
            synthesis = SynthesisService()
            result = synthesis.generate_literature_review(
                topic=question_text,
                docs=docs,
                sources=sources or None
            )
            
            # Store in Answer with mode info
            Answer.objects.create(
                question=question_obj,
                text=f"[LIT_REVIEW] {result.get('title', question_text)}",
                citations=[]  # Citations embedded in sections structure
            )
            
            return Response(result, status=status.HTTP_200_OK)
        
        # ===== QA MODE (EXISTING LOGIC) =====
        elif mode == "qa":
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
    Upload a PDF file and trigger async ingestion.

    Expected form-data:
    - file: PDF
    - session: Session name (optional)
    
    Returns immediately with 202 Accepted and processing starts in background.
    """
    import threading
    from django.core.files.storage import default_storage
    from django.core.files.base import ContentFile
    from rag.services.ingestion import IngestionService
    
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
    
    # Normalize filename
    normalized = normalize_filename(file.name)

    # Register document in relational DB with UPLOADED status
    document, created = Document.objects.get_or_create(
        filename=normalized,
        session=session
    )
    
    # Reset status if re-uploading
    if not created:
        document.status = 'UPLOADED'
        document.error_message = None
        document.processing_started_at = None
        document.processing_completed_at = None
        document.save()

    # Trigger async ingestion
    def ingest_in_background():
        service = IngestionService()
        service.ingest_document(document.id, str(full_path))
    
    thread = threading.Thread(target=ingest_in_background, daemon=True)
    thread.start()

    return Response(
        {
            "message": "PDF upload initiated. Processing in background.",
            "document_id": document.id,
            "filename": file.name,
            "session": session.name,
            "status": document.status
        },
        status=status.HTTP_202_ACCEPTED
    )


@api_view(["GET"])
def list_pdfs(request):
    """
    List PDFs available in a session with their processing status.
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

    pdfs = session.documents.values(
        "id",
        "filename",
        "title",
        "abstract",
        "status",
        "page_count",
        "uploaded_at",
        "error_message"
    )

    return Response(
        {
            "session": session.name,
            "pdfs": list(pdfs),
        },
        status=status.HTTP_200_OK
    )


@api_view(["GET"])
def document_status(request, document_id):
    """
    Get detailed status of a document ingestion.
    
    Returns processing status, timestamps, and any error messages.
    """
    try:
        document = Document.objects.get(id=document_id)
        
        processing_time = None
        if document.processing_started_at and document.processing_completed_at:
            processing_time = (
                document.processing_completed_at - document.processing_started_at
            ).total_seconds()
        
        return Response({
            "document_id": document.id,
            "filename": document.filename,
            "session": document.session.name,
            "status": document.status,
            "uploaded_at": document.uploaded_at,
            "processing_started_at": document.processing_started_at,
            "processing_completed_at": document.processing_completed_at,
            "processing_time_seconds": processing_time,
            "error_message": document.error_message,
            "metadata": {
                "title": document.title,
                "abstract": document.abstract,
                "page_count": document.page_count
            }
        }, status=status.HTTP_200_OK)
        
    except Document.DoesNotExist:
        return Response(
            {"error": "Document not found"},
            status=status.HTTP_404_NOT_FOUND
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
