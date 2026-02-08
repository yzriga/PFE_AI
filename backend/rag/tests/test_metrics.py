"""
Tests for D6: Evaluation + Monitoring System

Tests cover:
- RunLog model creation and relationships
- MetricsService logging and aggregation
- /api/metrics/summary endpoint
- Integration with /api/ask/ endpoint
"""
from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APIClient
from unittest.mock import patch, Mock
import json

from rag.models import Session, Document, Question, Answer, RunLog
from rag.services.metrics_service import MetricsService


class RunLogModelTests(TestCase):
    """Test RunLog model creation and relationships."""
    
    def setUp(self):
        self.session = Session.objects.create(name="test_session")
        self.question = Question.objects.create(
            text="Test question?",
            session=self.session
        )
    
    def test_create_runlog_success(self):
        """Test creating RunLog with all fields."""
        log = RunLog.objects.create(
            session=self.session,
            question=self.question,
            question_text="Test question?",
            mode="qa",
            sources=["paper1.pdf", "paper2.pdf"],
            latency_ms=523,
            retrieved_chunks=[
                {"doc": "paper1.pdf", "page": 5, "score": 0.87}
            ],
            prompt_tokens=150,
            completion_tokens=75
        )
        
        self.assertEqual(log.session, self.session)
        self.assertEqual(log.question, self.question)
        self.assertEqual(log.mode, "qa")
        self.assertEqual(log.latency_ms, 523)
        self.assertEqual(len(log.retrieved_chunks), 1)
        self.assertIsNone(log.error_type)
    
    def test_create_runlog_with_error(self):
        """Test creating RunLog for failed query."""
        log = RunLog.objects.create(
            session=self.session,
            question_text="Test question?",
            mode="qa",
            sources=[],
            latency_ms=120,
            retrieved_chunks=[],
            error_type="ChromaConnectionError",
            error_message="Failed to connect to ChromaDB"
        )
        
        self.assertEqual(log.error_type, "ChromaConnectionError")
        self.assertIsNotNone(log.error_message)
        self.assertIsNone(log.question)  # No Question object for failed queries
    
    def test_runlog_ordering(self):
        """Test RunLog ordering (newest first)."""
        # Create 3 logs with different timestamps
        log1 = RunLog.objects.create(
            session=self.session,
            question_text="First",
            mode="qa",
            sources=[],
            latency_ms=100,
            retrieved_chunks=[]
        )
        
        log2 = RunLog.objects.create(
            session=self.session,
            question_text="Second",
            mode="qa",
            sources=[],
            latency_ms=200,
            retrieved_chunks=[]
        )
        
        log3 = RunLog.objects.create(
            session=self.session,
            question_text="Third",
            mode="qa",
            sources=[],
            latency_ms=300,
            retrieved_chunks=[]
        )
        
        # Query ordered logs
        logs = RunLog.objects.all()
        
        # Should be ordered newest first
        self.assertEqual(logs[0].question_text, "Third")
        self.assertEqual(logs[1].question_text, "Second")
        self.assertEqual(logs[2].question_text, "First")
    
    def test_runlog_session_relationship(self):
        """Test RunLog -> Session relationship."""
        log = RunLog.objects.create(
            session=self.session,
            question_text="Test",
            mode="qa",
            sources=[],
            latency_ms=100,
            retrieved_chunks=[]
        )
        
        # Access via reverse relationship
        session_logs = self.session.run_logs.all()
        self.assertEqual(session_logs.count(), 1)
        self.assertEqual(session_logs[0], log)


class MetricsServiceTests(TestCase):
    """Test MetricsService logging and aggregation methods."""
    
    def setUp(self):
        self.session = Session.objects.create(name="test_session")
        self.service = MetricsService()
    
    def test_log_query_success(self):
        """Test logging a successful query."""
        question = Question.objects.create(
            text="What is machine learning?",
            session=self.session
        )
        
        log = self.service.log_query(
            session=self.session,
            question=question,
            question_text="What is machine learning?",
            mode="qa",
            sources=["paper1.pdf"],
            latency_ms=450,
            retrieved_chunks=[
                {"doc": "paper1.pdf", "page": 3, "score": 0.92}
            ]
        )
        
        self.assertIsNotNone(log)
        self.assertEqual(log.session, self.session)
        self.assertEqual(log.question, question)
        self.assertEqual(log.mode, "qa")
        self.assertEqual(log.latency_ms, 450)
        self.assertIsNone(log.error_type)
        
        # Verify it's in database
        db_log = RunLog.objects.get(id=log.id)
        self.assertEqual(db_log.question_text, "What is machine learning?")
    
    def test_log_query_with_error(self):
        """Test logging a failed query."""
        error = ConnectionError("Cannot connect to Chroma")
        
        log = self.service.log_query(
            session=self.session,
            question_text="Test question",
            mode="qa",
            sources=[],
            latency_ms=100,
            retrieved_chunks=[],
            error=error
        )
        
        self.assertEqual(log.error_type, "ConnectionError")
        self.assertIn("Cannot connect", log.error_message)
    
    def test_get_summary_empty(self):
        """Test get_summary with no data."""
        summary = self.service.get_summary(since_days=7)
        
        self.assertEqual(summary["queries"]["total"], 0)
        self.assertEqual(summary["errors"]["count"], 0)
        self.assertEqual(summary["retrieval"]["avg_chunks_per_query"], 0)
    
    def test_get_summary_with_data(self):
        """Test get_summary with sample data."""
        # Create 10 successful queries
        for i in range(10):
            RunLog.objects.create(
                session=self.session,
                question_text=f"Question {i}",
                mode="qa" if i < 7 else "compare",
                sources=[],
                latency_ms=500 + i * 50,  # 500, 550, 600, ...
                retrieved_chunks=[
                    {"doc": "test.pdf", "page": 1, "score": 0.8},
                    {"doc": "test.pdf", "page": 2, "score": 0.7}
                ]
            )
        
        # Create 2 failed queries
        for i in range(2):
            RunLog.objects.create(
                session=self.session,
                question_text=f"Failed {i}",
                mode="qa",
                sources=[],
                latency_ms=100,
                retrieved_chunks=[],
                error_type="TimeoutError",
                error_message="Query timeout"
            )
        
        summary = self.service.get_summary(since_days=7)
        
        # Check totals
        self.assertEqual(summary["queries"]["total"], 12)
        self.assertEqual(summary["queries"]["by_mode"]["qa"], 9)  # 7 success + 2 error
        self.assertEqual(summary["queries"]["by_mode"]["compare"], 3)
        
        # Check latency
        self.assertGreater(summary["queries"]["latency_avg"], 0)
        self.assertGreater(summary["queries"]["latency_p50"], 0)
        self.assertGreater(summary["queries"]["latency_p95"], 0)
        
        # Check errors
        self.assertEqual(summary["errors"]["count"], 2)
        self.assertAlmostEqual(summary["errors"]["rate"], 2/12, places=2)
        self.assertEqual(len(summary["errors"]["top_errors"]), 1)
        self.assertEqual(summary["errors"]["top_errors"][0]["type"], "TimeoutError")
        self.assertEqual(summary["errors"]["top_errors"][0]["count"], 2)
        
        # Check retrieval
        self.assertAlmostEqual(summary["retrieval"]["avg_chunks_per_query"], 1.67, places=1)
        self.assertGreater(summary["retrieval"]["avg_score"], 0)
        
        # Check sessions
        self.assertEqual(summary["sessions"]["active_count"], 1)
    
    def test_percentile_calculation(self):
        """Test _percentile helper method."""
        values = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
        
        p50 = self.service._percentile(values, 50)
        self.assertAlmostEqual(p50, 550, delta=50)  # Median
        
        p95 = self.service._percentile(values, 95)
        self.assertGreater(p95, 900)  # Near max
        
        p0 = self.service._percentile(values, 0)
        self.assertEqual(p0, 100)  # Min
    
    def test_percentile_empty_list(self):
        """Test _percentile with empty list."""
        result = self.service._percentile([], 50)
        self.assertEqual(result, 0)
    
    def test_get_session_history(self):
        """Test get_session_history method."""
        # Create 5 logs
        for i in range(5):
            RunLog.objects.create(
                session=self.session,
                question_text=f"Question {i}",
                mode="qa",
                sources=[],
                latency_ms=400 + i * 100,
                retrieved_chunks=[{"doc": "test.pdf", "page": 1}]
            )
        
        # Get history
        history = self.service.get_session_history(self.session, limit=3)
        
        self.assertEqual(len(history), 3)  # Limited to 3
        self.assertEqual(history[0]["question"], "Question 4")  # Newest first
        self.assertEqual(history[1]["question"], "Question 3")
        self.assertEqual(history[2]["question"], "Question 2")
        
        # Check structure
        self.assertIn("id", history[0])
        self.assertIn("mode", history[0])
        self.assertIn("latency_ms", history[0])
        self.assertIn("chunks_count", history[0])
        self.assertIn("created_at", history[0])


class MetricsAPITests(TestCase):
    """Test /api/metrics/summary endpoint."""
    
    def setUp(self):
        self.client = APIClient()
        self.session = Session.objects.create(name="test_session")
    
    def test_metrics_summary_default(self):
        """Test GET /api/metrics/summary with default params."""
        # Create sample data
        RunLog.objects.create(
            session=self.session,
            question_text="Test question",
            mode="qa",
            sources=[],
            latency_ms=500,
            retrieved_chunks=[]
        )
        
        response = self.client.get("/api/metrics/summary/")
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        # Check structure
        self.assertIn("period", data)
        self.assertIn("queries", data)
        self.assertIn("errors", data)
        self.assertIn("retrieval", data)
        self.assertIn("sessions", data)
        
        # Check values
        self.assertEqual(data["period"]["days"], 7)  # Default
        self.assertEqual(data["queries"]["total"], 1)
    
    def test_metrics_summary_custom_period(self):
        """Test GET /api/metrics/summary?since=30."""
        response = self.client.get("/api/metrics/summary/", {"since": "30"})
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        
        self.assertEqual(data["period"]["days"], 30)
    
    def test_metrics_summary_invalid_since(self):
        """Test GET /api/metrics/summary with invalid 'since' param."""
        response = self.client.get("/api/metrics/summary/", {"since": "invalid"})
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())
    
    def test_metrics_summary_negative_since(self):
        """Test GET /api/metrics/summary with negative 'since'."""
        response = self.client.get("/api/metrics/summary/", {"since": "-5"})
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())


class RunLogIntegrationTests(TestCase):
    """Test that queries actually create RunLog entries."""
    
    def setUp(self):
        self.client = APIClient()
        self.session = Session.objects.create(name="test_session")
        
        # Create a test document
        self.document = Document.objects.create(
            filename="test.pdf",
            session=self.session,
            status="INDEXED",
            page_count=10
        )
    
    @patch('rag.views.ask_with_citations')
    @patch('langchain_chroma.Chroma')
    def test_ask_question_creates_runlog_qa_mode(self, mock_chroma, mock_ask):
        """Test that /api/ask/ in QA mode creates RunLog."""
        # Mock RAG response
        mock_ask.return_value = {
            "answer": "Test answer",
            "citations": [{"source": "test.pdf", "page": 5}]
        }
        
        # Make request
        response = self.client.post("/api/ask/", {
            "question": "What is the main contribution?",
            "session": "test_session",
            "mode": "qa"
        }, format='json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify RunLog was created
        logs = RunLog.objects.filter(session=self.session)
        self.assertEqual(logs.count(), 1)
        
        log = logs.first()
        self.assertEqual(log.mode, "qa")
        self.assertEqual(log.question_text, "What is the main contribution?")
        self.assertGreaterEqual(log.latency_ms, 0)  # Can be 0 in fast mocked tests
        self.assertIsNone(log.error_type)
    
    @patch('rag.services.synthesis.SynthesisService')
    @patch('langchain_chroma.Chroma')
    @patch('langchain_ollama.OllamaEmbeddings')
    def test_ask_question_creates_runlog_compare_mode(self, mock_embed, mock_chroma, mock_synthesis):
        """Test that /api/ask/ in compare mode creates RunLog."""
        # Mock synthesis response
        mock_service = Mock()
        mock_service.compare_papers.return_value = {
            "topic": "Test comparison",
            "claims": []
        }
        mock_synthesis.return_value = mock_service
        
        # Mock vectordb
        mock_db = Mock()
        mock_db.similarity_search.return_value = []
        mock_chroma.return_value = mock_db
        
        # Make request
        response = self.client.post("/api/ask/", {
            "question": "Compare the methodologies",
            "session": "test_session",
            "mode": "compare"
        }, format='json')
        
        self.assertEqual(response.status_code, 200)
        
        # Verify RunLog was created
        logs = RunLog.objects.filter(session=self.session)
        self.assertEqual(logs.count(), 1)
        
        log = logs.first()
        self.assertEqual(log.mode, "compare")
        self.assertGreater(log.latency_ms, 0)
    
    @patch('rag.views.ask_with_citations')
    def test_ask_question_logs_error(self, mock_ask):
        """Test that errors are logged in RunLog."""
        # Mock error
        mock_ask.side_effect = Exception("Chroma connection failed")
        
        # Make request
        response = self.client.post("/api/ask/", {
            "question": "Test question",
            "session": "test_session"
        }, format='json')
        
        self.assertEqual(response.status_code, 500)
        
        # Verify error was logged
        logs = RunLog.objects.filter(session=self.session)
        self.assertEqual(logs.count(), 1)
        
        log = logs.first()
        self.assertEqual(log.error_type, "Exception")
        self.assertIn("Chroma connection failed", log.error_message)
