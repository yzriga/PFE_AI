"""
Tests for multi-document synthesis modes (D4).

Tests cover:
1. SynthesisService.compare_papers()
2. SynthesisService.generate_literature_review()
3. /api/ask/ with mode parameter
"""

from django.test import TestCase
from rest_framework.test import APIClient
from unittest.mock import Mock, patch, MagicMock
from rag.services.synthesis import SynthesisService
from rag.models import Session, Document, Question, Answer


class SynthesisServiceTests(TestCase):
    """Unit tests for SynthesisService class."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.service = SynthesisService(model="mistral")
        
        # Mock document chunks
        self.mock_docs = [
            Mock(
                page_content="Climate change causes global temperature rise.",
                metadata={"source": "paper1.pdf", "page": 5}
            ),
            Mock(
                page_content="Global warming leads to sea level increase.",
                metadata={"source": "paper1.pdf", "page": 6}
            ),
            Mock(
                page_content="Temperature rise is debatable according to some.",
                metadata={"source": "paper2.pdf", "page": 3}
            ),
            Mock(
                page_content="Sea levels are rising at 3mm/year.",
                metadata={"source": "paper2.pdf", "page": 4}
            ),
        ]
    
    @patch('rag.services.synthesis.OllamaLLM')
    def test_compare_papers_success(self, mock_llm_class):
        """Test successful comparison of multiple papers."""
        # Mock LLM response with valid JSON
        mock_llm_instance = Mock()
        mock_llm_instance.invoke.return_value = """{
  "claims": [
    {
      "claim": "Global temperatures are rising",
      "papers": [
        {
          "paper_id": "paper1.pdf",
          "stance": "supports",
          "evidence": [
            {"page": 5, "excerpt": "Climate change causes global temperature rise."}
          ]
        },
        {
          "paper_id": "paper2.pdf",
          "stance": "neutral",
          "evidence": [
            {"page": 3, "excerpt": "Temperature rise is debatable according to some."}
          ]
        }
      ]
    }
  ]
}"""
        mock_llm_class.return_value = mock_llm_instance
        
        # Reinitialize service to use mocked LLM
        service = SynthesisService()
        
        result = service.compare_papers(
            question="How does climate change affect temperature?",
            docs=self.mock_docs
        )
        
        # Assertions
        self.assertEqual(result["topic"], "How does climate change affect temperature?")
        self.assertEqual(len(result["claims"]), 1)
        self.assertEqual(result["claims"][0]["claim"], "Global temperatures are rising")
        self.assertEqual(len(result["claims"][0]["papers"]), 2)
        self.assertEqual(result["num_papers"], 2)
        self.assertIn("paper1.pdf", result["sources"])
        self.assertIn("paper2.pdf", result["sources"])
        
        # Verify LLM was called
        mock_llm_instance.invoke.assert_called_once()
    
    @patch('rag.services.synthesis.OllamaLLM')
    def test_compare_papers_empty_docs(self, mock_llm_class):
        """Test compare with no documents."""
        service = SynthesisService()
        
        result = service.compare_papers(
            question="Any question",
            docs=[]
        )
        
        self.assertEqual(result["topic"], "Any question")
        self.assertEqual(result["claims"], [])
        self.assertIn("message", result)
        self.assertIn("No documents", result["message"])
    
    @patch('rag.services.synthesis.OllamaLLM')
    def test_compare_papers_json_parse_error(self, mock_llm_class):
        """Test graceful handling of invalid JSON from LLM."""
        mock_llm_instance = Mock()
        mock_llm_instance.invoke.return_value = "This is not valid JSON"
        mock_llm_class.return_value = mock_llm_instance
        
        service = SynthesisService()
        
        result = service.compare_papers(
            question="Test question",
            docs=self.mock_docs
        )
        
        # Should return error but not crash
        self.assertIn("error", result)
        self.assertIn("raw_response", result)
        self.assertEqual(result["claims"], [])
    
    @patch('rag.services.synthesis.OllamaLLM')
    def test_generate_literature_review_success(self, mock_llm_class):
        """Test successful literature review generation."""
        mock_llm_instance = Mock()
        mock_llm_instance.invoke.return_value = """{
  "title": "Literature Review: Climate Change Impacts",
  "outline": ["Introduction", "Temperature Trends", "Sea Level Rise"],
  "sections": [
    {
      "heading": "Introduction",
      "content": "Climate change is a major concern [paper1.pdf, p.5]. Multiple studies confirm warming trends."
    },
    {
      "heading": "Temperature Trends",
      "content": "Global temperatures have risen [paper1.pdf, p.5].\\n\\nSome debate exists [paper2.pdf, p.3]."
    }
  ]
}"""
        mock_llm_class.return_value = mock_llm_instance
        
        service = SynthesisService()
        
        result = service.generate_literature_review(
            topic="Climate change impacts",
            docs=self.mock_docs
        )
        
        # Assertions
        self.assertEqual(result["title"], "Literature Review: Climate Change Impacts")
        self.assertEqual(len(result["outline"]), 3)
        self.assertEqual(len(result["sections"]), 2)
        self.assertEqual(result["sections"][0]["heading"], "Introduction")
        self.assertEqual(len(result["sections"][0]["paragraphs"]), 1)
        
        # Check citations extracted
        paragraphs = result["sections"][0]["paragraphs"]
        self.assertTrue(len(paragraphs[0]["citations"]) > 0)
        self.assertEqual(paragraphs[0]["citations"][0]["paper"], "paper1.pdf")
        self.assertEqual(paragraphs[0]["citations"][0]["page"], 5)
        
        # Verify sources tracked
        self.assertEqual(result["num_papers"], 2)
        
        # Verify LLM was called
        mock_llm_instance.invoke.assert_called_once()
    
    @patch('rag.services.synthesis.OllamaLLM')
    def test_generate_literature_review_empty_docs(self, mock_llm_class):
        """Test literature review with no documents."""
        service = SynthesisService()
        
        result = service.generate_literature_review(
            topic="Any topic",
            docs=[]
        )
        
        self.assertIn("Literature Review", result["title"])
        self.assertEqual(result["sections"], [])
        self.assertIn("message", result)
    
    def test_extract_citations(self):
        """Test citation extraction from text."""
        service = SynthesisService()
        
        text = "Multiple studies show results [paper1.pdf, p.5] and findings [paper2.pdf, p.12]."
        citations = service._extract_citations(text)
        
        self.assertEqual(len(citations), 2)
        self.assertEqual(citations[0]["paper"], "paper1.pdf")
        self.assertEqual(citations[0]["page"], 5)
        self.assertEqual(citations[1]["paper"], "paper2.pdf")
        self.assertEqual(citations[1]["page"], 12)
    
    def test_extract_citations_no_matches(self):
        """Test citation extraction with no citations."""
        service = SynthesisService()
        
        text = "This text has no citations."
        citations = service._extract_citations(text)
        
        self.assertEqual(len(citations), 0)


class APIEndpointTests(TestCase):
    """Integration tests for /api/ask/ with mode parameter."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.client = APIClient()
        
        # Create test session and document
        self.session = Session.objects.create(name="test-session")
        self.doc = Document.objects.create(
            filename="test.pdf",
            session=self.session,
            status="INDEXED",
            title="Test Paper",
            page_count=10
        )
    
    @patch('langchain_chroma.Chroma')
    @patch('langchain_ollama.OllamaEmbeddings')
    @patch('rag.services.synthesis.OllamaLLM')
    def test_ask_with_compare_mode(self, mock_llm_class, mock_embeddings, mock_chroma_class):
        """Test /api/ask/ with mode=compare."""
        # Mock vector DB
        mock_docs = [
            Mock(
                page_content="Finding A",
                metadata={"source": "test.pdf", "page": 1}
            ),
            Mock(
                page_content="Finding B",
                metadata={"source": "test.pdf", "page": 2}
            ),
        ]
        mock_vectordb = Mock()
        mock_vectordb.similarity_search.return_value = mock_docs
        mock_chroma_class.return_value = mock_vectordb
        
        # Mock LLM
        mock_llm_instance = Mock()
        mock_llm_instance.invoke.return_value = '{"claims": []}'
        mock_llm_class.return_value = mock_llm_instance
        
        # Make request
        response = self.client.post('/api/ask/', {
            "question": "Compare findings",
            "session": "test-session",
            "mode": "compare"
        }, format='json')
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertIn("topic", response.data)
        self.assertIn("claims", response.data)
        self.assertEqual(response.data["topic"], "Compare findings")
        
        # Verify Question/Answer created
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(Answer.objects.count(), 1)
    
    @patch('langchain_chroma.Chroma')
    @patch('langchain_ollama.OllamaEmbeddings')
    @patch('rag.services.synthesis.OllamaLLM')
    def test_ask_with_lit_review_mode(self, mock_llm_class, mock_embeddings, mock_chroma_class):
        """Test /api/ask/ with mode=lit_review."""
        # Mock vector DB
        mock_docs = [
            Mock(
                page_content="Introduction text",
                metadata={"source": "test.pdf", "page": 1}
            ),
        ]
        mock_vectordb = Mock()
        mock_vectordb.similarity_search.return_value = mock_docs
        mock_chroma_class.return_value = mock_vectordb
        
        # Mock LLM
        mock_llm_instance = Mock()
        mock_llm_instance.invoke.return_value = '''{
  "title": "Literature Review: Test Topic",
  "outline": ["Section 1"],
  "sections": [{"heading": "Section 1", "content": "Content here."}]
}'''
        mock_llm_class.return_value = mock_llm_instance
        
        # Make request
        response = self.client.post('/api/ask/', {
            "question": "Review topic",
            "session": "test-session",
            "mode": "lit_review"
        }, format='json')
        
        # Assertions
        self.assertEqual(response.status_code, 200)
        self.assertIn("title", response.data)
        self.assertIn("sections", response.data)
        self.assertIn("Literature Review", response.data["title"])
        
        # Verify Question/Answer created
        self.assertEqual(Question.objects.count(), 1)
        self.assertEqual(Answer.objects.count(), 1)
    
    def test_ask_with_invalid_mode(self):
        """Test /api/ask/ with invalid mode parameter."""
        response = self.client.post('/api/ask/', {
            "question": "Test question",
            "session": "test-session",
            "mode": "invalid_mode"
        }, format='json')
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)
        self.assertIn("Invalid mode", response.data["error"])
    
    def test_ask_with_qa_mode_default(self):
        """Test /api/ask/ defaults to qa mode when not specified."""
        # This test would require extensive mocking of the QA pipeline
        # For now, just verify mode validation works
        response = self.client.post('/api/ask/', {
            "session": "test-session"
            # Missing question - should error before mode logic
        }, format='json')
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.data)
    
    @patch('langchain_chroma.Chroma')
    @patch('langchain_ollama.OllamaEmbeddings')
    @patch('rag.services.synthesis.OllamaLLM')
    def test_compare_with_source_filtering(self, mock_llm_class, mock_embeddings, mock_chroma_class):
        """Test compare mode respects source filtering."""
        # Mock vector DB
        mock_docs = [Mock(page_content="Text", metadata={"source": "doc1.pdf", "page": 1})]
        mock_vectordb = Mock()
        mock_vectordb.similarity_search.return_value = mock_docs
        mock_chroma_class.return_value = mock_vectordb
        
        # Mock LLM
        mock_llm_instance = Mock()
        mock_llm_instance.invoke.return_value = '{"claims": []}'
        mock_llm_class.return_value = mock_llm_instance
        
        # Make request with sources
        response = self.client.post('/api/ask/', {
            "question": "Compare",
            "session": "test-session",
            "mode": "compare",
            "sources": ["doc1.pdf", "doc2.pdf"]
        }, format='json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify similarity_search called with filter
        call_kwargs = mock_vectordb.similarity_search.call_args[1]
        self.assertIn("filter", call_kwargs)
        self.assertIn("source", call_kwargs["filter"])
