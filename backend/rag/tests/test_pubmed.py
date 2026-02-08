"""
Tests for PubMed Connector

Tests the PubmedService and related API endpoints with mocked Entrez API calls.
"""

import os
from datetime import date
from unittest.mock import Mock, patch, MagicMock, mock_open
from django.test import TestCase, override_settings
import tempfile

from rag.models import Session, Document, PaperSource
from rag.services.pubmed_service import PubmedService


class MockEntrezRecord:
    """Mock Entrez record structure for PubMed article data."""
    
    def __init__(self, pmid="12345678"):
        self.data = {
            "PubmedArticle": [{
                "MedlineCitation": {
                    "PMID": pmid,
                    "Article": {
                        "ArticleTitle": "Test Paper: Cancer Treatment Research",
                        "AuthorList": [
                            {"LastName": "Smith", "ForeName": "John"},
                            {"LastName": "Doe", "ForeName": "Jane"},
                        ],
                        "Abstract": {
                            "AbstractText": ["This is a test abstract about cancer treatment and immunotherapy."]
                        },
                        "Journal": {
                            "Title": "Test Journal of Medicine",
                            "JournalIssue": {
                                "Volume": "42",
                                "Issue": "3",
                                "PubDate": {
                                    "Year": "2025",
                                    "Month": "Jan",
                                    "Day": "15"
                                }
                            }
                        },
                        "Pagination": {
                            "MedlinePgn": "123-456"
                        }
                    },
                    "MeshHeadingList": [
                        {"DescriptorName": "Neoplasms"},
                        {"DescriptorName": "Immunotherapy"}
                    ]
                },
                "PubmedData": {
                    "ArticleIdList": [
                        MockArticleId("doi", "10.1234/test.2025.001"),
                        MockArticleId("pmc", "PMC1234567")
                    ]
                }
            }]
        }


class MockArticleId:
    """Mock article ID with attributes."""
    def __init__(self, id_type, value):
        self.attributes = {"IdType": id_type}
        self._value = value
    
    def __str__(self):
        return self._value


class MockEntrezSearchResult:
    """Mock Entrez search result."""
    def __init__(self, pmids):
        self.data = {
            "IdList": pmids
        }


class MockEntrezLinkResult:
    """Mock Entrez link result for PMID to PMCID conversion."""
    def __init__(self, pmc_id=None):
        if pmc_id:
            self.data = [{
                "LinkSetDb": [{
                    "Link": [{"Id": pmc_id}]
                }]
            }]
        else:
            self.data = [{"LinkSetDb": []}]


class PubmedServiceTests(TestCase):
    """Test suite for  PubmedService."""
    
    def setUp(self):
        self.service = PubmedService()
        self.mock_record = MockEntrezRecord()
    
    @patch('rag.services.pubmed_service.Entrez.read')
    @patch('rag.services.pubmed_service.Entrez.efetch')
    @patch('rag.services.pubmed_service.Entrez.esearch')
    def test_search_returns_results(self, mock_search, mock_fetch, mock_read):
        """Test that search returns formatted results."""
        # Mock search returning PMIDs
        mock_search_handle = Mock()
        mock_search.return_value = mock_search_handle
        
        mock_fetch_handle = Mock()
        mock_fetch.return_value = mock_fetch_handle
        
        # First read() call for search results, second for fetch
        mock_read.side_effect = [
            MockEntrezSearchResult(["12345678"]).data,
            self.mock_record.data
        ]
        
        results = self.service.search("cancer treatment", max_results=1)
        
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['pmid'], '12345678')
        self.assertEqual(results[0]['title'], 'Test Paper: Cancer Treatment Research')
        self.assertIn('John Smith', results[0]['authors'])
        self.assertIn('Jane Doe', results[0]['authors'])
    
    @patch('rag.services.pubmed_service.Entrez.read')
    @patch('rag.services.pubmed_service.Entrez.efetch')
    def test_fetch_metadata(self, mock_fetch, mock_read):
        """Test fetching metadata for a specific paper."""
        mock_handle = Mock()
        mock_fetch.return_value = mock_handle
        mock_read.return_value = self.mock_record.data
        
        metadata = self.service.fetch_metadata("12345678")
        
        self.assertEqual(metadata['pmid'], '12345678')
        self.assertEqual(metadata['title'], 'Test Paper: Cancer Treatment Research')
        self.assertEqual(len(metadata['authors']), 2)
        self.assertEqual(metadata['journal'], 'Test Journal of Medicine')
        self.assertEqual(metadata['doi'], '10.1234/test.2025.001')
        self.assertEqual(metadata['pmc_id'], '1234567')
    
    @patch('rag.services.pubmed_service.Entrez.read')
    @patch('rag.services.pubmed_service.Entrez.efetch')
    def test_fetch_metadata_not_found(self, mock_fetch, mock_read):
        """Test fetching metadata for non-existent paper raises ValueError."""
        mock_handle = Mock()
        mock_fetch.return_value = mock_handle
        mock_read.return_value = {"PubmedArticle": []}
        
        with self.assertRaises(ValueError) as context:
            self.service.fetch_metadata("99999999")
        
        self.assertIn("not found", str(context.exception))
    
    @patch('rag.services.pubmed_service.Entrez.read')
    @patch('rag.services.pubmed_service.Entrez.elink')
    def test_check_pmc_availability_available(self, mock_link, mock_read):
        """Test checking PMC availability when PDF exists."""
        mock_handle = Mock()
        mock_link.return_value = mock_handle
        mock_read.return_value = MockEntrezLinkResult("7654321").data
        
        pmc_id = self.service.check_pmc_availability("12345678")
        
        self.assertEqual(pmc_id, "7654321")
    
    @patch('rag.services.pubmed_service.Entrez.read')
    @patch('rag.services.pubmed_service.Entrez.elink')
    def test_check_pmc_availability_not_available(self, mock_link, mock_read):
        """Test checking PMC availability when PDF doesn't exist."""
        mock_handle = Mock()
        mock_link.return_value = mock_handle
        mock_read.return_value = MockEntrezLinkResult(None).data
        
        pmc_id = self.service.check_pmc_availability("12345678")
        
        self.assertIsNone(pmc_id)
    
    @patch('rag.services.pubmed_service.requests.get')
    @patch('rag.services.pubmed_service.PubmedService.fetch_metadata')
    @patch('rag.services.pubmed_service.PubmedService.check_pmc_availability')
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_download_pdf_success(self, mock_check_pmc, mock_fetch, mock_requests):
        """Test successful PDF download from PMC."""
        mock_check_pmc.return_value = "7654321"
        mock_fetch.return_value = {
            'title': 'Test Paper',
            'pmid': '12345678'
        }
        
        # Mock successful download
        mock_response = Mock()
        mock_response.iter_content = Mock(return_value=[b'PDF content'])
        mock_response.raise_for_status = Mock()
        mock_requests.return_value = mock_response
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = self.service.download_pdf("12345678", tmpdir)
            
            self.assertIsNotNone(filepath)
            self.assertTrue(filepath.endswith('.pdf'))
            self.assertTrue(os.path.exists(filepath))
    
    @patch('rag.services.pubmed_service.PubmedService.check_pmc_availability')
    def test_download_pdf_not_available(self, mock_check_pmc):
        """Test PDF download when not available in PMC."""
        mock_check_pmc.return_value = None
        
        with tempfile.TemporaryDirectory() as tmpdir:
            filepath = self.service.download_pdf("12345678", tmpdir)
            
            self.assertIsNone(filepath)
    
    @patch('threading.Thread')
    @patch('rag.services.pubmed_service.requests.get')
    @patch('rag.services.pubmed_service.PubmedService.fetch_metadata')
    @patch('rag.services.pubmed_service.PubmedService.check_pmc_availability')
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_import_paper_full(self, mock_check_pmc, mock_fetch, mock_requests, mock_thread):
        """Test full paper import (metadata + PDF + ingestion)."""
        # Setup mocks
        mock_check_pmc.return_value = "7654321"
        mock_fetch.return_value = {
            'title': 'Test Paper: Cancer Treatment',
            'pmid': '12345678',
            'abstract': 'Test abstract',
            'authors': ['John Smith', 'Jane Doe'],
            'published_date': '2025-01-15',
            'journal': 'Test Journal',
            'doi': '10.1234/test.001',
            'pmc_id': '7654321',
            'mesh_terms': ['Cancer', 'Treatment']
        }
        
        mock_response = Mock()
        mock_response.iter_content = Mock(return_value=[b'PDF content'])
        mock_response.raise_for_status = Mock()
        mock_requests.return_value = mock_response
        
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance
        
        # Create session
        Session.objects.get_or_create(name="test-session")
        
        result = self.service.import_paper(
            pmid="12345678",
            session_name="test-session",
            download_pdf=True
        )
        
        # Verify result
        self.assertTrue(result['success'])
        self.assertEqual(result['pmid'], '12345678')
        self.assertEqual(result['status'], 'UPLOADED')
        self.assertIsNotNone(result['document_id'])
        self.assertIsNotNone(result['paper_source_id'])
        
        # Verify database records
        paper_source = PaperSource.objects.get(id=result['paper_source_id'])
        self.assertEqual(paper_source.source_type, 'pubmed')
        self.assertEqual(paper_source.external_id, '12345678')
        self.assertTrue(paper_source.imported)
        
        document = Document.objects.get(id=result['document_id'])
        self.assertEqual(document.status, 'UPLOADED')
        self.assertEqual(document.session.name, 'test-session')
        
        # Verify background thread was started
        mock_thread_instance.start.assert_called_once()
    
    @patch('rag.services.pubmed_service.PubmedService.fetch_metadata')
    @patch('rag.services.pubmed_service.PubmedService.check_pmc_availability')
    def test_import_paper_metadata_only(self, mock_check_pmc, mock_fetch):
        """Test importing only metadata without downloading PDF."""
        mock_check_pmc.return_value = None  # No PMC available
        mock_fetch.return_value = {
            'title': 'Test Paper',
            'pmid': '12345678',
            'abstract': 'Test abstract',
            'authors': ['John Smith'],
            'published_date': '2025-01-15'
        }
        
        # Create session
        Session.objects.get_or_create(name="test-session")
        
        result = self.service.import_paper(
            pmid="12345678",
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
        self.assertIsNone(paper_source.document)
        self.assertFalse(paper_source.imported)


class PubmedAPITests(TestCase):
    """Test suite for PubMed API endpoints."""
    
    @patch('rag.services.pubmed_service.Entrez.read')
    @patch('rag.services.pubmed_service.Entrez.efetch')
    @patch('rag.services.pubmed_service.Entrez.esearch')
    def test_search_endpoint(self, mock_search, mock_fetch, mock_read):
        """Test GET /api/pubmed/search endpoint."""
        mock_search_handle = Mock()
        mock_search.return_value = mock_search_handle
        mock_fetch_handle = Mock()
        mock_fetch.return_value = mock_fetch_handle
        
        mock_record = MockEntrezRecord()
        mock_read.side_effect = [
            MockEntrezSearchResult(["12345678"]).data,
            mock_record.data
        ]
        
        response = self.client.get('/api/pubmed/search/?q=cancer&max=1')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['query'], 'cancer')
        self.assertGreaterEqual(data['count'], 0)
        self.assertIn('results', data)
    
    def test_search_endpoint_no_query(self):
        """Test search endpoint without query returns 400."""
        response = self.client.get('/api/pubmed/search/')
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
    
    @patch('threading.Thread')
    @patch('rag.services.pubmed_service.requests.get')
    @patch('rag.services.pubmed_service.PubmedService.fetch_metadata')
    @patch('rag.services.pubmed_service.PubmedService.check_pmc_availability')
    @override_settings(MEDIA_ROOT=tempfile.mkdtemp())
    def test_import_endpoint(self, mock_check_pmc, mock_fetch, mock_requests, mock_thread):
        """Test POST /api/pubmed/import endpoint."""
        # Create session first
        Session.objects.get_or_create(name='test-session')
        
        mock_check_pmc.return_value = "7654321"
        mock_fetch.return_value = {
            'title': 'Test Paper',
            'pmid': '12345678',
            'abstract': 'Test',
            'authors': ['John Smith'],
            'published_date': '2025-01-15',
            'pmc_id': '7654321'
        }
        
        mock_response = Mock()
        mock_response.iter_content = Mock(return_value=[b'PDF'])
        mock_response.raise_for_status = Mock()
        mock_requests.return_value = mock_response
        
        mock_thread_instance = Mock()
        mock_thread.return_value = mock_thread_instance
        
        response = self.client.post(
            '/api/pubmed/import/',
            {
                'pmid': '12345678',
                'session': 'test-session',
                'download_pdf': True
            },
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 202)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['pmid'], '12345678')
    
    def test_import_endpoint_missing_pmid(self):
        """Test import endpoint without pmid returns 400."""
        response = self.client.post(
            '/api/pubmed/import/',
            {'session': 'test-session'},
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
    
    def test_import_endpoint_missing_session(self):
        """Test import endpoint without session returns 400."""
        response = self.client.post(
            '/api/pubmed/import/',
            {'pmid': '12345678'},
            content_type='application/json'
        )
        
        self.assertEqual(response.status_code, 400)
        self.assertIn('error', response.json())
    
    @patch('rag.services.pubmed_service.Entrez.read')
    @patch('rag.services.pubmed_service.Entrez.efetch')
    def test_metadata_endpoint(self, mock_fetch, mock_read):
        """Test GET /api/pubmed/metadata/<pmid> endpoint."""
        mock_handle = Mock()
        mock_fetch.return_value = mock_handle
        mock_read.return_value = MockEntrezRecord().data
        
        response = self.client.get('/api/pubmed/metadata/12345678/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['pmid'], '12345678')
        self.assertIn('title', data)
        self.assertIn('authors', data)
    
    @patch('rag.services.pubmed_service.Entrez.read')
    @patch('rag.services.pubmed_service.Entrez.elink')
    def test_check_pmc_endpoint(self, mock_link, mock_read):
        """Test GET /api/pubmed/check-pmc/<pmid> endpoint."""
        mock_handle = Mock()
        mock_link.return_value = mock_handle
        mock_read.return_value = MockEntrezLinkResult("7654321").data
        
        response = self.client.get('/api/pubmed/check-pmc/12345678/')
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['pmid'], '12345678')
        self.assertTrue(data['pmc_available'])
        self.assertEqual(data['pmc_id'], '7654321')
