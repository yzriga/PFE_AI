"""
Tests for highlights and annotations system (D5).

Tests cover:
1. Highlight model creation and relationships
2. CRUD API endpoints
3. HighlightService embedding operations
4. Query integration with highlight retrieval
"""

from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from rag.models import Session, Document, Highlight, HighlightEmbedding
from rag.services.highlight_service import HighlightService


class HighlightModelTests(TestCase):
    """Tests for Highlight and HighlightEmbedding models."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.session = Session.objects.create(name="test-session")
        self.document = Document.objects.create(
            filename="test.pdf",
            session=self.session,
            status="INDEXED",
            page_count=10
        )
    
    def test_create_highlight(self):
        """Test creating a highlight with all fields."""
        highlight = Highlight.objects.create(
            document=self.document,
            page=5,
            start_offset=100,
            end_offset=250,
            text="This is highlighted text from the document.",
            note="My personal note about this passage.",
            tags=["important", "methodology"]
        )
        
        self.assertEqual(highlight.document, self.document)
        self.assertEqual(highlight.page, 5)
        self.assertEqual(highlight.start_offset, 100)
        self.assertEqual(highlight.end_offset, 250)
        self.assertIn("highlighted text", highlight.text)
        self.assertEqual(highlight.note, "My personal note about this passage.")
        self.assertEqual(len(highlight.tags), 2)
        self.assertIn("important", highlight.tags)
    
    def test_highlight_ordering(self):
        """Test highlights are ordered by document, page, offset."""
        h1 = Highlight.objects.create(
            document=self.document, page=3, start_offset=50, end_offset=100,
            text="First"
        )
        h2 = Highlight.objects.create(
            document=self.document, page=1, start_offset=10, end_offset=20,
            text="Second"
        )
        h3 = Highlight.objects.create(
            document=self.document, page=1, start_offset=30, end_offset=40,
            text="Third"
        )
        
        highlights = list(Highlight.objects.all())
        
        # Should be ordered by page, then start_offset
        self.assertEqual(highlights[0], h2)  # Page 1, offset 10
        self.assertEqual(highlights[1], h3)  # Page 1, offset 30
        self.assertEqual(highlights[2], h1)  # Page 3, offset 50
    
    def test_highlight_embedding_relationship(self):
        """Test OneToOne relationship between Highlight and HighlightEmbedding."""
        highlight = Highlight.objects.create(
            document=self.document, page=1, start_offset=0, end_offset=10,
            text="Test"
        )
        
        embedding = HighlightEmbedding.objects.create(
            highlight=highlight,
            embedding_id="highlight_1_123"
        )
        
        # Test forward relationship
        self.assertEqual(highlight.embedding, embedding)
        
        # Test reverse relationship
        self.assertEqual(embedding.highlight, highlight)
    
    def test_highlight_cascade_delete(self):
        """Test that deleting highlight also deletes embedding."""
        highlight = Highlight.objects.create(
            document=self.document, page=1, start_offset=0, end_offset=10,
            text="Test"
        )
        embedding = HighlightEmbedding.objects.create(
            highlight=highlight,
            embedding_id="test_id"
        )
        
        highlight_id = highlight.id
        embedding_id = embedding.id
        
        highlight.delete()
        
        # Both should be deleted
        self.assertFalse(Highlight.objects.filter(id=highlight_id).exists())
        self.assertFalse(HighlightEmbedding.objects.filter(id=embedding_id).exists())


class HighlightAPITests(TestCase):
    """Tests for highlight CRUD API endpoints."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        self.session = Session.objects.create(name="test-session")
        self.document = Document.objects.create(
            filename="test.pdf",
            session=self.session,
            status="INDEXED",
            page_count=10
        )
    
    @patch('rag.views_highlights.HighlightService')
    def test_create_highlight_success(self, mock_service_class):
        """Test successful highlight creation."""
        mock_service = Mock()
        mock_service.embed_highlight.return_value = "highlight_1_123"
        mock_service_class.return_value = mock_service
        
        response = self.client.post('/api/highlights/', {
            "document_id": self.document.id,
            "page": 5,
            "start_offset": 100,
            "end_offset": 250,
            "text": "Highlighted text",
            "note": "My note",
            "tags": ["important"]
        }, format='json')
        
        self.assertEqual(response.status_code, 201)
        self.assertIn("id", response.data)
        self.assertEqual(response.data["page"], 5)
        self.assertEqual(response.data["text"], "Highlighted text")
        self.assertEqual(response.data["note"], "My note")
        self.assertEqual(response.data["tags"], ["important"])
        self.assertTrue(response.data["embedded"])
        self.assertEqual(response.data["embedding_id"], "highlight_1_123")
        
        # Verify highlight was created
        self.assertEqual(Highlight.objects.count(), 1)
        
        # Verify embed_highlight was called
        mock_service.embed_highlight.assert_called_once()
    
    def test_create_highlight_missing_fields(self):
        """Test creating highlight with missing required fields."""
        response = self.client.post('/api/highlights/', {
            "document_id": self.document.id,
            "page": 5
            # Missing start_offset, end_offset, text
        }, format='json')
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)
    
    def test_create_highlight_document_not_found(self):
        """Test creating highlight for non-existent document."""
        response = self.client.post('/api/highlights/', {
            "document_id": 99999,
            "page": 1,
            "start_offset": 0,
            "end_offset": 10,
            "text": "Test"
        }, format='json')
        
        self.assertEqual(response.status_code, 404)
        self.assertIn("error", response.data)
    
    def test_create_highlight_page_exceeds_count(self):
        """Test validation of page number against document page count."""
        response = self.client.post('/api/highlights/', {
            "document_id": self.document.id,
            "page": 99,  # Document only has 10 pages
            "start_offset": 0,
            "end_offset": 10,
            "text": "Test"
        }, format='json')
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("exceeds document page count", response.data["error"])
    
    def test_list_highlights(self):
        """Test listing all highlights."""
        # Create test highlights
        Highlight.objects.create(
            document=self.document, page=1, start_offset=0, end_offset=10,
            text="First", tags=["tag1"]
        )
        Highlight.objects.create(
            document=self.document, page=2, start_offset=50, end_offset=100,
            text="Second", tags=["tag2"]
        )
        
        response = self.client.get('/api/highlights/list/')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 2)
        self.assertEqual(len(response.data["highlights"]), 2)
    
    def test_list_highlights_filter_by_document(self):
        """Test filtering highlights by document."""
        doc2 = Document.objects.create(
            filename="other.pdf",
            session=self.session,
            status="INDEXED"
        )
        
        Highlight.objects.create(
            document=self.document, page=1, start_offset=0, end_offset=10,
            text="Doc 1"
        )
        Highlight.objects.create(
            document=doc2, page=1, start_offset=0, end_offset=10,
            text="Doc 2"
        )
        
        response = self.client.get(f'/api/highlights/list/?document_id={self.document.id}')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertEqual(response.data["highlights"][0]["document_filename"], "test.pdf")
    
    def test_list_highlights_filter_by_tag(self):
        """Test filtering highlights by tag."""
        Highlight.objects.create(
            document=self.document, page=1, start_offset=0, end_offset=10,
            text="First", tags=["important"]
        )
        Highlight.objects.create(
            document=self.document, page=2, start_offset=0, end_offset=10,
            text="Second", tags=["minor"]
        )
        
        response = self.client.get('/api/highlights/list/?tag=important')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertIn("important", response.data["highlights"][0]["tags"])
    
    def test_get_highlight(self):
        """Test retrieving single highlight."""
        highlight = Highlight.objects.create(
            document=self.document, page=5, start_offset=100, end_offset=200,
            text="Test highlight"
        )
        
        response = self.client.get(f'/api/highlights/{highlight.id}/')
        
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], highlight.id)
        self.assertEqual(response.data["text"], "Test highlight")
        self.assertEqual(response.data["page"], 5)
    
    def test_get_highlight_not_found(self):
        """Test retrieving non-existent highlight."""
        response = self.client.get('/api/highlights/99999/')
        
        self.assertEqual(response.status_code, 404)
    
    @patch('rag.views_highlights.HighlightService')
    def test_update_highlight(self, mock_service_class):
        """Test updating highlight note and tags."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        
        highlight = Highlight.objects.create(
            document=self.document, page=1, start_offset=0, end_offset=10,
            text="Original text", note="Original note", tags=["old"]
        )
        
        response = self.client.put(f'/api/highlights/{highlight.id}/update/', {
            "note": "Updated note",
            "tags": ["new", "updated"]
        }, format='json')
        
        self.assertEqual(response.status_code, 200)
        
        # Refresh from DB
        highlight.refresh_from_db()
        self.assertEqual(highlight.note, "Updated note")
        self.assertEqual(highlight.tags, ["new", "updated"])
        
        # Verify update_embedding was called
        mock_service.update_embedding.assert_called_once()
    
    @patch('rag.views_highlights.HighlightService')
    def test_delete_highlight(self, mock_service_class):
        """Test deleting highlight."""
        mock_service = Mock()
        mock_service_class.return_value = mock_service
        
        highlight = Highlight.objects.create(
            document=self.document, page=1, start_offset=0, end_offset=10,
            text="To delete"
        )
        highlight_id = highlight.id
        
        response = self.client.delete(f'/api/highlights/{highlight_id}/delete/')
        
        self.assertEqual(response.status_code, 204)
        
        # Verify highlight was deleted
        self.assertFalse(Highlight.objects.filter(id=highlight_id).exists())
        
        # Verify delete_embedding was called
        mock_service.delete_embedding.assert_called_once()


class HighlightServiceTests(TestCase):
    """Tests for HighlightService embedding operations."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.session = Session.objects.create(name="test-session")
        self.document = Document.objects.create(
            filename="test.pdf",
            session=self.session,
            status="INDEXED"
        )
        self.highlight = Highlight.objects.create(
            document=self.document,
            page=5,
            start_offset=100,
            end_offset=250,
            text="This is important text.",
            note="My analysis of this passage."
        )
    
    @patch('rag.services.highlight_service.Chroma')
    @patch('rag.services.highlight_service.OllamaEmbeddings')
    def test_embed_highlight_success(self, mock_embeddings, mock_chroma_class):
        """Test successful highlight embedding."""
        mock_vectordb = Mock()
        mock_chroma_class.return_value = mock_vectordb
        
        service = HighlightService()
        embedding_id = service.embed_highlight(self.highlight)
        
        # Verify embedding ID was generated
        self.assertIsNotNone(embedding_id)
        self.assertIn(f"highlight_{self.highlight.id}", embedding_id)
        
        # Verify add_texts was called with combined text + note
        mock_vectordb.add_texts.assert_called_once()
        call_args = mock_vectordb.add_texts.call_args[1]
        self.assertIn("important text", call_args["texts"][0])
        self.assertIn("USER NOTE", call_args["texts"][0])
        self.assertIn("My analysis", call_args["texts"][0])
        
        # Verify metadata includes type=highlight
        metadata = call_args["metadatas"][0]
        self.assertEqual(metadata["type"], "highlight")
        self.assertEqual(metadata["highlight_id"], self.highlight.id)
        self.assertEqual(metadata["page"], 5)
        
        # Verify HighlightEmbedding was created
        self.assertTrue(HighlightEmbedding.objects.filter(highlight=self.highlight).exists())
    
    @patch('rag.services.highlight_service.Chroma')
    @patch('rag.services.highlight_service.OllamaEmbeddings')
    def test_retrieve_highlights(self, mock_embeddings, mock_chroma_class):
        """Test retrieving relevant highlights for a query."""
        mock_docs = [
            Mock(
                page_content="Highlighted text with [USER NOTE]: Important finding",
                metadata={"type": "highlight", "page": 5, "highlight_id": 1}
            )
        ]
        
        mock_vectordb = Mock()
        mock_vectordb.similarity_search.return_value = mock_docs
        mock_chroma_class.return_value = mock_vectordb
        
        service = HighlightService()
        results = service.retrieve_highlights(
            session_name="test-session",
            query="What are the important findings?",
            k=3
        )
        
        self.assertEqual(len(results), 1)
        self.assertIn("USER NOTE", results[0].page_content)
        
        # Verify similarity_search was called with type filter
        call_kwargs = mock_vectordb.similarity_search.call_args[1]
        self.assertEqual(call_kwargs["filter"]["type"], "highlight")
        self.assertEqual(call_kwargs["k"], 3)
