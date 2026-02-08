from django.urls import path
from .views import (
    ask_question, 
    upload_pdf, 
    list_pdfs, 
    document_status,
    create_session, 
    delete_pdf, 
    list_sessions, 
    delete_session
)
from .views_arxiv import (
    arxiv_search,
    arxiv_import,
    arxiv_metadata
)

urlpatterns = [
    path("ask/", ask_question, name="ask_question"),
    path("upload/", upload_pdf, name="upload_pdf"),
    path("pdfs/", list_pdfs, name="list_pdfs"),
    path("documents/<int:document_id>/status/", document_status, name="document_status"),
    path("session/", create_session, name="create_session"),
    path("sessions/", list_sessions, name="list_sessions"),
    path("session/<str:session_name>/", delete_session, name="delete_session"),
    path("delete/", delete_pdf, name="delete_pdf"),
    
    # arXiv endpoints
    path("arxiv/search/", arxiv_search, name="arxiv_search"),
    path("arxiv/import/", arxiv_import, name="arxiv_import"),
    path("arxiv/metadata/<str:arxiv_id>/", arxiv_metadata, name="arxiv_metadata"),
]
