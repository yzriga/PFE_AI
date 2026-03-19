from django.urls import path
from .views import (
    ask_question, 
    upload_pdf, 
    list_pdfs, 
    document_status,
    document_page_text,
    retry_document_ingestion,
    create_session, 
    delete_pdf, 
    list_sessions, 
    session_detail, 
    get_history,
    metrics_summary
)
from .views_arxiv import arxiv_search, arxiv_import
from .views_external import external_search, external_import
from .views_highlights import highlights, delete_highlight, search_highlights
from .views_discovery import related_papers

urlpatterns = [
    path("ask/", ask_question, name="ask_question"),
    path("upload/", upload_pdf, name="upload_pdf"),
    path("pdfs/", list_pdfs, name="list_pdfs"),
    path("documents/<int:document_id>/status/", document_status, name="document_status"),
    path("documents/<int:document_id>/page-text/", document_page_text, name="document_page_text"),
    path("documents/<int:document_id>/retry/", retry_document_ingestion, name="retry_document_ingestion"),
    path("session/", create_session, name="create_session"),
    path("sessions/", list_sessions, name="list_sessions"),
    path("session/<str:session_name>/", session_detail, name="session_detail"),
    path("history/", get_history, name="get_history"),
    path("delete/", delete_pdf, name="delete_pdf"),
    path("metrics/summary/", metrics_summary, name="metrics_summary"),
    
    # Paper search & import
    path("arxiv/search/", arxiv_search, name="arxiv_search"),
    path("arxiv/import/", arxiv_import, name="arxiv_import"),
    path("search/external/", external_search, name="external_search"),
    path("import/external/", external_import, name="external_import"),
    path("papers/related/", related_papers, name="related_papers"),
    path("highlights/", highlights, name="highlights"),
    path("highlights/<int:highlight_id>/", delete_highlight, name="delete_highlight"),
    path("highlights/search/", search_highlights, name="search_highlights"),
]
