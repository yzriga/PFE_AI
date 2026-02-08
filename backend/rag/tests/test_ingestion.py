"""
Tests for the unified ingestion pipeline
"""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from rag.models import Session, Document
from rag.services.ingestion import IngestionService


class IngestionServiceTests(TransactionTestCase):
    """
    Test the IngestionService class.
    
    Using TransactionTestCase to handle threading properly.
    """
    
    def setUp(self):
        """Create test session and document"""
        self.session = Session.objects.create(name="Test Session")
        self.service = IngestionService()
    
    def tearDown(self):
        """Cleanup"""
        # Clean up any test documents
        Document.objects.all().delete()
        Session.objects.all().delete()
    
    @patch('rag.services.ingestion.PyPDFLoader')
    @patch('rag.services.ingestion.Chroma')
    def test_successful_ingestion(self, mock_chroma, mock_loader):
        """Test successful document ingestion"""
        # Setup mocks
        mock_page = MagicMock()
        mock_page.page_content = "Sample PDF content\nAbstract: This is a test paper"
        mock_page.metadata = {}
        mock_loader.return_value.load.return_value = [mock_page] * 3
        
        mock_vectordb = MagicMock()
        mock_chroma.return_value = mock_vectordb
        
        # Create document
        document = Document.objects.create(
            filename="test.pdf",
            session=self.session,
            status='UPLOADED'
        )
        
        # Run ingestion
        result = self.service.ingest_document(document.id, "/fake/path/test.pdf")
        
        # Assertions
        self.assertEqual(result["status"], "success")
        self.assertIn("chunks_indexed", result)
        
        # Reload document from DB
        document.refresh_from_db()
        self.assertEqual(document.status, 'INDEXED')
        self.assertIsNotNone(document.processing_started_at)
        self.assertIsNotNone(document.processing_completed_at)
        self.assertEqual(document.page_count, 3)
    
    @patch('rag.services.ingestion.PyPDFLoader')
    def test_ingestion_failure(self, mock_loader):
        """Test ingestion failure handling"""
        # Setup mock to raise exception
        mock_loader.side_effect = Exception("PDF parsing error")
        
        # Create document
        document = Document.objects.create(
            filename="bad.pdf",
            session=self.session,
            status='UPLOADED'
        )
        
        # Run ingestion
        result = self.service.ingest_document(document.id, "/fake/path/bad.pdf")
        
        # Assertions  
        self.assertEqual(result["status"], "error")
        self.assertIn("error", result)
        
        # Reload document from DB
        document.refresh_from_db()
        self.assertEqual(document.status, 'FAILED')
        self.assertIsNotNone(document.error_message)
        self.assertIn("PDF parsing error", document.error_message)
    
    def test_nonexistent_document(self):
        """Test ingestion with non-existent document ID"""
        result = self.service.ingest_document(99999, "/fake/path.pdf")
        
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"], "Document not found")


class IngestionAPITests(TestCase):
    """
    Test the upload API endpoint.
    """
    
    def setUp(self):
        """Create test session"""
        self.session = Session.objects.create(name="API Test Session")
        self.url = "/api/upload/"
    
    @patch('threading.Thread')
    def test_upload_returns_202(self, mock_thread):
        """Test that upload returns 202 Accepted immediately"""
        # Create mock PDF file
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        pdf_content = b"%PDF-1.4\n%EOF\n"  # Minimal valid PDF
        pdf_file = SimpleUploadedFile(
            "test_paper.pdf",
            pdf_content,
            content_type="application/pdf"
        )
        
        # Make request
        response = self.client.post(
            self.url,
            {
                "file": pdf_file,
                "session": self.session.name
            },
            format='multipart'
        )
        
        # Assertions
        self.assertEqual(response.status_code, 202)
        self.assertIn("document_id", response.data)
        self.assertEqual(response.data["status"], "UPLOADED")
        self.assertIn("Processing in background", response.data["message"])
        
        # Verify document was created
        document = Document.objects.get(id=response.data["document_id"])
        self.assertEqual(document.status, 'UPLOADED')
        self.assertEqual(document.session, self.session)
        
        # Verify background thread was started
        mock_thread.assert_called_once()
        mock_thread.return_value.start.assert_called_once()
    
    def test_upload_without_file(self):
        """Test upload without file returns 400"""
        response = self.client.post(
            self.url,
            {"session": self.session.name}
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)
    
    def test_upload_non_pdf(self):
        """Test upload with non-PDF file returns 400"""
        from django.core.files.uploadedfile import SimpleUploadedFile
        
        txt_file = SimpleUploadedFile(
            "test.txt",
            b"Not a PDF",
            content_type="text/plain"
        )
        
        response = self.client.post(
            self.url,
            {
                "file": txt_file,
                "session": self.session.name
            },
            format='multipart'
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("Only PDF files", response.data["error"])


class DocumentStatusAPITests(TestCase):
    """
    Test the document status endpoint.
    """
    
    def setUp(self):
        """Create test data"""
        self.session = Session.objects.create(name="Status Test Session")
        self.document = Document.objects.create(
            filename="status_test.pdf",
            session=self.session,
            status='INDEXED',
            page_count=10
        )
    
    def test_get_document_status(self):
        """Test retrieving document status"""
        url = f"/api/documents/{self.document.id}/status/"
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["document_id"], self.document.id)
        self.assertEqual(response.data["status"], "INDEXED")
        self.assertEqual(response.data["filename"], "status_test.pdf")
        self.assertIn("metadata", response.data)
    
    def test_get_nonexistent_document_status(self):
        """Test status of non-existent document returns 404"""
        url = "/api/documents/99999/status/"
        response = self.client.get(url)
        
        self.assertEqual(response.status_code, 404)
