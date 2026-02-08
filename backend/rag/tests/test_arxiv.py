"""
Tests for arXiv Connector

Tests the ArxivService and related API endpoints with mocked arXiv API calls.
"""

import os
from datetime import date, datetime
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase, override_settings
from django.urls import reverse
import tempfile

from rag.models import Session, Document, PaperSource
from rag.services.arxiv_service import ArxivService


class MockAuthor:
    """Mock author object with name attribute."""
    def __init__(self, name):
        self.name = name


class MockArxivResult:
    """Mock arxiv.Result object for testing."""
    
    def __init__(self, arxiv_id="2411.04920v4"):
        self.entry_id = f"http://arxiv.org/abs/{arxiv_id}"
        self.title = "Test Paper: Machine Learning Research"
        self.authors = [MockAuthor("John Doe"), MockAuthor("Jane Smith")]
        self.summary = "This is a test abstract about machine learning and AI."
        self.published = datetime(2025, 6, 4, 10, 30, 0)
        self.updated = datetime(2025, 6, 5, 14, 20, 0)
        self.pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        self.categories = ["cs.CL", "cs.AI"]
        self.primary_category = "cs.CL"
        self.doi = "10.1234/example.doi"
        self.journal_ref = "Test Journal 2025"
    
    def download_pdf(self, dirpath, filename):
        """Mock PDF download - creates an empty file."""
        filepath = os.path.join(dirpath, filename)
        with open(filepath, 'wb') as f:
            f.write(b'%PDF-1.4 fake pdf content')


class ArxivServiceTests(TestCase):
    """Test suite for ArxivService."""
    
    def setUp(self):
        self.service = ArxivService()
        self.mock_paper = MockArxivResult()
    
    @patch('rag.services.arxiv_service.arxiv.Client')
    def test_search_returns_results(self, mock_client_class):
        """Test that search returns formatted results."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.results.return_value = [self.mock_paper]
        
        service = ArxivService()
        results = service.search("machine learning", max_results=1)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['arxiv_id'], '2411.04920v4')
        self.assertEqual(results[0]['title'], 'Test Paper: Machine Learning Research')
        self.assertIn('John Doe', results[0]['authors'])
        self.assertIn('Jane Smith', results[0]['authors'])
    
    @patch('rag.services.arxiv_service.arxiv.Client')
    def test_fetch_metadata(self, mock_client_class):
        """Test fetching metadata for a specific paper."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.results.return_value = iter([self.mock_paper])
        
        service = ArxivService()
        metadata = service.fetch_metadata("2411.04920v4")
        
        self.assertEqual(metadata['arxiv_id'], '2411.04920v4')
        self.assertEqual(metadata['title'], 'Test Paper: Machine Learning Research')
        self.assertEqual(len(metadata['authors']), 2)
        self.assertEqual(metadata['primary_category'], 'cs.CL')
    
    @patch('rag.services.arxiv_service.arxiv.Client')
    def test_fetch_metadata_not_found(self, mock_client_class):
        """Test fetching metadata for non-existent paper raises ValueError."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.results.return_value = iter([])  # Empty iterator
        
        service = ArxivService()
        
        with self.assertRaises(ValueError) as context:
            service.fetch_metadata("invalid-id")
        
        self.assertIn("not found", str(context.exception))
    
    @patch('rag.services.arxiv_service.arxiv.Client')
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_download_pdf(self, mock_client_class):
        """Test PDF download creates a file."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.results.side_effect = lambda x: iter([self.mock_paper])
        
        service = ArxivService()
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = service.download_pdf("2411.04920v4", tmpdir)
            
            self.assertTrue(os.path.exists(filepath))
            self.assertTrue(filepath.endswith('.pdf'))
    
    @patch('threading.Thread')
    @patch('rag.services.arxiv_service.arxiv.Client')
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_import_paper_full(self, mock_client_class, mock_thread):
        """Test full paper import (metadata + PDF + ingestion)."""
        # Setup mocks
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        # Return a new iterator on each call (fetch_metadata + download_pdf)
        mock_client.results.side_effect = lambda x: iter([self.mock_paper])
        
        # Mock thread to prevent actual background execution
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance
        
        service = ArxivService()
        
        result = service.import_paper(
            arxiv_id="2411.04920v4",
            session_name="test-session",
            download_pdf=True
        )
        
        # Verify result structure
        self.assertTrue(result['success'])
        self.assertEqual(result['arxiv_id'], '2411.04920v4')
        self.assertEqual(result['status'], 'UPLOADED')
        self.assertIsNotNone(result['document_id'])
        self.assertIsNotNone(result['paper_source_id'])
        
        # Verify database records
        paper_source = PaperSource.objects.get(id=result['paper_source_id'])
        self.assertEqual(paper_source.source_type, 'arxiv')
        self.assertEqual(paper_source.external_id, '2411.04920v4')
        self.assertTrue(paper_source.imported)
        
        document = Document.objects.get(id=result['document_id'])
        self.assertEqual(document.status, 'UPLOADED')
        self.assertEqual(document.session.name, 'test-session')
        
        # Verify background thread was started
        mock_thread_instance.start.assert_called_once()
    
    @patch('rag.services.arxiv_service.arxiv.Client')
    def test_import_paper_metadata_only(self, mock_client_class):
        """Test importing only metadata without downloading PDF."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.results.return_value = iter([self.mock_paper])
        
        service = ArxivService()
        
        result = service.import_paper(
            arxiv_id="2411.04920v4",
            session_name="test-session",
            download_pdf=False
        )
        
        # Verify result
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'METADATA_ONLY')
        self.assertIsNone(result['document_id'])
        self.assertIsNotNone(result['paper_source_id'])
        
        # Verify only PaperSource was created
        paper_source = PaperSource.objects.get(id=result['paper_source_id'])
        self.assertFalse(paper_source.imported)
        self.assertIsNone(paper_source.document)
        
        # Verify no Document was created
        self.assertEqual(Document.objects.count(), 0)


class ArxivAPITests(TestCase):
    """Test suite for arXiv API endpoints."""
    
    def setUp(self):
        self.session = Session.objects.create(name="test-session")
    
    @patch('rag.services.arxiv_service.arxiv.Client')
    def test_search_endpoint(self, mock_client_class):
        """Test GET /api/arxiv/search endpoint."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_paper = MockArxivResult()
        mock_client.results.return_value = [mock_paper]
        
        response = self.client.get('/api/arxiv/search/', {'q': 'machine learning', 'max_results': 5})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['query'], 'machine learning')
        self.assertEqual(len(data['results']), 1)
        self.assertEqual(data['results'][0]['arxiv_id'], '2411.04920v4')
    
    def test_search_endpoint_missing_query(self):
        """Test search endpoint without query parameter returns 400."""
        response = self.client.get('/api/arxiv/search/')
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
    
    def test_search_endpoint_invalid_max_results(self):
        """Test search endpoint with invalid max_results returns 400."""
        response = self.client.get('/api/arxiv/search/', {'q': 'test', 'max_results': 'invalid'})
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
    
    @patch('threading.Thread')
    @patch('rag.services.arxiv_service.arxiv.Client')
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_import_endpoint(self, mock_client_class, mock_thread):
        """Test POST /api/arxiv/import endpoint."""
        # Create session first (use get_or_create to avoid duplicate issues)
        Session.objects.get_or_create(name='test-session')
        
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_paper = MockArxivResult()
        # Return a new iterator on each call
        mock_client.results.side_effect = lambda x: iter([mock_paper])
        
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance
        
        response = self.client.post(
            '/api/arxiv/import/',
            {
                'arxiv_id': '2411.04920v4',
                'session': 'test-session',
                'download_pdf': True
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['arxiv_id'], '2411.04920v4')
        self.assertIsNotNone(data['document_id'])
    
    def test_import_endpoint_missing_arxiv_id(self):
        """Test import endpoint without arxiv_id returns 400."""
        response = self.client.post(
            '/api/arxiv/import/',
            {'session': 'test-session'},
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
    
    def test_import_endpoint_missing_session(self):
        """Test import endpoint without session returns 400."""
        response = self.client.post(
            '/api/arxiv/import/',
            {'arxiv_id': '2411.04920v4'},
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
    
    @patch('rag.services.arxiv_service.arxiv.Client')
    def test_metadata_endpoint(self, mock_client_class):
        """Test GET /api/arxiv/metadata/<id> endpoint."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_paper = MockArxivResult()
        mock_client.results.return_value = iter([mock_paper])
        
        response = self.client.get('/api/arxiv/metadata/2411.04920v4/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['arxiv_id'], '2411.04920v4')
        self.assertEqual(data['title'], 'Test Paper: Machine Learning Research')
    
    @patch('rag.services.arxiv_service.arxiv.Client')
    def test_metadata_endpoint_not_found(self, mock_client_class):
        """Test metadata endpoint with invalid ID returns 404."""
        mock_client = Mock()
        mock_client_class.return_value = mock_client
        mock_client.results.return_value = iter([])
        
        response = self.client.get('/api/arxiv/metadata/invalid-id/')
        
        self.assertEqual(response.status_code, 404)
        self.assertIn('error', response.json())


class PaperSourceModelTests(TestCase):
    """Test suite for PaperSource model."""
    
    def test_create_paper_source(self):
        """Test creating a PaperSource record."""
        paper = PaperSource.objects.create(
            source_type='arxiv',
            external_id='2411.04920v4',
            title='Test Paper',
            authors='John Doe, Jane Smith',
            abstract='Test abstract',
            published_date=date(2025, 6, 4),
            pdf_url='https://arxiv.org/pdf/2411.04920v4.pdf',
            entry_url='https://arxiv.org/abs/2411.04920v4'
        )
        
        self.assertEqual(paper.source_type, 'arxiv')
        self.assertEqual(paper.external_id, '2411.04920v4')
        self.assertFalse(paper.imported)
        self.assertIsNone(paper.document)
    
    def test_unique_constraint(self):
        """Test that (source_type, external_id) must be unique."""
        PaperSource.objects.create(
            source_type='arxiv',
            external_id='2411.04920v4',
            title='Test Paper',
            authors='John Doe',
            abstract='Test abstract'
        )
        
        # Attempting to create duplicate should raise error
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            PaperSource.objects.create(
                source_type='arxiv',
                external_id='2411.04920v4',
                title='Duplicate Paper',
                authors='Jane Smith',
                abstract='Another abstract'
            )
    
    def test_link_to_document(self):
        """Test linking PaperSource to Document."""
        session = Session.objects.create(name='test-session')
        document = Document.objects.create(
            filename='test.pdf',
            session=session,
            title='Test Paper'
        )
        
        paper = PaperSource.objects.create(
            source_type='arxiv',
            external_id='2411.04920v4',
            title='Test Paper',
            authors='John Doe',
            abstract='Test abstract',
            document=document,
            imported=True
        )
        
        self.assertEqual(paper.document, document)
        self.assertTrue(paper.imported)
        self.assertEqual(document.paper_source, paper)
