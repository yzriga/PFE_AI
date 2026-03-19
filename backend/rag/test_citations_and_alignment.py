from unittest.mock import patch

from django.test import TestCase
from langchain_core.documents import Document as LangchainDocument
from rest_framework.test import APIClient

from rag.models import Document, Session
from rag.query import build_snippet_citations
from rag.services.retrieval import ScoredDocument


class CitationRegressionTests(TestCase):
    def test_build_snippet_citations_deduplicates_by_chunk_id(self):
        doc1 = LangchainDocument(
            page_content="First chunk text",
            metadata={"source": "paper.pdf", "page": 2},
        )
        doc2 = LangchainDocument(
            page_content="Duplicate chunk text",
            metadata={"source": "paper.pdf", "page": 2},
        )

        scored = [
            ScoredDocument(doc1, score=0.92, chunk_id="chunk-1"),
            ScoredDocument(doc2, score=0.85, chunk_id="chunk-1"),
        ]
        citations = build_snippet_citations(scored)

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["chunk_id"], "chunk-1")
        self.assertEqual(citations[0]["page"], 2)

    def test_to_citation_dict_keeps_page_metadata_for_frontend_alignment(self):
        long_text = "A" * 240
        doc = LangchainDocument(
            page_content=long_text,
            metadata={"source": "source.pdf", "page": 7},
        )
        citation = ScoredDocument(doc, score=0.7777, chunk_id="cid-1").to_citation_dict()

        self.assertEqual(citation["source"], "source.pdf")
        self.assertEqual(citation["page"], 7)
        self.assertEqual(citation["snippet"], "A" * 200)
        self.assertEqual(citation["score"], 0.7777)

    def test_to_citation_dict_strips_embedded_nul_bytes(self):
        doc = LangchainDocument(
            page_content="Lc[W](t) :=\nX\n\n\x00control",
            metadata={"source": "source.pdf", "page": 7},
        )

        citation = ScoredDocument(doc, score=0.5, chunk_id="cid-null").to_citation_dict()

        self.assertNotIn("\x00", citation["snippet"])


class PageAlignmentApiRegressionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.session = Session.objects.create(name="alignment-session")
        self.document = Document.objects.create(
            filename="alignment.pdf",
            storage_path="pdfs/alignment_abcd123.pdf",
            session=self.session,
            status="INDEXED",
        )

    @patch("rag.views.default_storage.exists")
    @patch("rag.views.default_storage.path")
    @patch("pypdf.PdfReader")
    def test_document_page_text_is_one_indexed(self, mock_reader_cls, mock_storage_path, mock_storage_exists):
        class _FakePage:
            def __init__(self, text):
                self._text = text

            def extract_text(self):
                return self._text

        class _FakeReader:
            def __init__(self, _path):
                self.pages = [_FakePage("page-one"), _FakePage("page-two")]

        mock_storage_exists.return_value = True
        mock_storage_path.return_value = "/tmp/alignment.pdf"
        mock_reader_cls.side_effect = _FakeReader

        response = self.client.get(
            f"/api/documents/{self.document.id}/page-text/?page=1"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["page"], 1)
        self.assertEqual(response.data["page_count"], 2)
        self.assertEqual(response.data["text"], "page-one")
        mock_storage_exists.assert_called_once_with("pdfs/alignment_abcd123.pdf")
        mock_storage_path.assert_called_once_with("pdfs/alignment_abcd123.pdf")
