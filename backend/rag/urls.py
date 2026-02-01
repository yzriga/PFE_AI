from django.urls import path
from .views import ask_question
from .views import ask_question, upload_pdf, list_pdfs

urlpatterns = [
    path("ask/", ask_question, name="ask_question"),
    path("upload/", upload_pdf, name="upload_pdf"),
    path("pdfs/", list_pdfs),
]
