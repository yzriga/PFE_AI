from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase
from rest_framework.test import APIClient

from rag.models import Document, IngestionJob, PaperSource, Session
from rag.services.discovery import DiscoveryService
from rag.services.import_utils import looks_like_pdf_url, queue_remote_import
from rag.services.ingestion_jobs import IngestionJobRunner
from rag.services.job_queue import enqueue_job
from rag.services.openalex_service import OpenAlexService
from rag.services.resilience import CircuitOpenError, TransientExternalError
from rag.services.semanticscholar_service import SemanticScholarService
from rag.services.synthesis import SynthesisService


class SemanticScholarServiceTests(SimpleTestCase):
    def test_extract_metadata_normalizes_null_fields(self):
        service = SemanticScholarService()

        metadata = service._extract_metadata(
            {
                "paperId": "abc123",
                "title": "Clinical Paper",
                "authors": [{"name": "Author One"}, {"name": None}],
                "abstract": None,
                "url": None,
                "year": 2026,
                "openAccessPdf": None,
            }
        )

        self.assertEqual(metadata["external_id"], "abc123")
        self.assertEqual(metadata["authors"], ["Author One"])
        self.assertEqual(metadata["abstract"], "No abstract available.")
        self.assertEqual(metadata["entry_url"], "")
        self.assertEqual(metadata["published_date"], "2026")

    @patch.object(SemanticScholarService, "search")
    def test_fetch_paper_graph_derives_related_papers_from_title_search(self, mock_search):
        service = SemanticScholarService()
        mock_search.return_value = [
            {
                "external_id": "other-paper",
                "title": "Related Paper",
                "authors": ["Author"],
                "abstract": "Abstract",
                "published_date": "2026",
                "entry_url": "https://example.org/paper",
                "source_type": "semanticscholar",
            }
        ]

        related = service._derive_related_papers("seed-paper", "Seed Title", limit=3)

        self.assertEqual(len(related), 1)
        self.assertEqual(related[0]["relationship"], "related_search")


class OpenAlexServiceTests(SimpleTestCase):
    def test_reconstruct_abstract_from_inverted_index(self):
        service = OpenAlexService()
        abstract = service._reconstruct_abstract(
            {
                "attention": [0],
                "is": [1],
                "all": [2],
                "you": [3],
                "need": [4],
            }
        )
        self.assertEqual(abstract, "attention is all you need")

    def test_openalex_metadata_ignores_landing_page_as_pdf(self):
        service = OpenAlexService()
        metadata = service._extract_metadata(
            {
                "id": "https://openalex.org/W123",
                "display_name": "Paper",
                "authorships": [],
                "abstract_inverted_index": {},
                "publication_year": 2024,
                "best_oa_location": {"landing_page_url": "https://publisher.org/article/123"},
                "primary_location": {"landing_page_url": "https://publisher.org/article/123"},
                "open_access": {"oa_url": "https://publisher.org/article/123"},
            }
        )
        self.assertEqual(metadata["pdf_url"], "")

    @patch("rag.services.openalex_service.settings")
    def test_openalex_content_download_url_uses_content_api_when_available(self, mock_settings):
        mock_settings.OPENALEX_API_KEY = "oa-key"
        service = OpenAlexService()
        url = service._content_download_url(
            {
                "content_url": "https://content.openalex.org/works/W123",
                "has_content_pdf": True,
            }
        )
        self.assertEqual(url, "https://content.openalex.org/works/W123.pdf?api_key=oa-key")

    def test_graph_items_prefer_arxiv_import_when_arxiv_id_exists(self):
        service = OpenAlexService()
        item = service._to_graph_item(
            {
                "external_id": "W123",
                "arxiv_id": "2603.12254v1",
                "title": "Paper",
                "authors": ["Alice"],
                "published_date": "2026",
                "entry_url": "https://openalex.org/W123",
                "abstract": "Abstract",
                "source_type": "openalex",
            },
            "related",
        )
        self.assertEqual(item["provider"], "arxiv")
        self.assertEqual(item["id"], "2603.12254v1")

    def test_resolve_best_match_prefers_exact_arxiv_match(self):
        service = OpenAlexService()
        service.search = lambda query, max_results, prefer_content=False: [
            {
                "external_id": "W123",
                "title": "One-step Latent-free Image Generation with Pixel Mean Flows",
                "arxiv_id": "2603.12254v1",
                "doi": "",
            }
        ]
        match = service.resolve_best_match(
            title="One-step Latent-free Image Generation with Pixel Mean Flows",
            arxiv_id="2603.12254v1",
        )
        self.assertEqual(match["external_id"], "W123")


class DiscoveryServiceTests(SimpleTestCase):
    def test_topic_oriented_transformer_question_is_treated_as_discoverable(self):
        service = DiscoveryService()
        self.assertTrue(service.should_use_external_discovery("Explain transformer architecture"))

    def test_ai_topic_provider_order_prefers_arxiv(self):
        service = DiscoveryService()
        self.assertEqual(
            service._provider_order("What do recent papers say about RAG for LLM agents?"),
            ["arxiv", "openalex", "europepmc"],
        )

    def test_arxiv_suggestions_keep_arxiv_provider(self):
        service = DiscoveryService()
        suggestion = service._result_to_suggestion(
            {
                "arxiv_id": "2603.12254v1",
                "external_id": "2603.12254v1",
                "title": "Test Paper",
                "authors": ["Alice"],
                "abstract": "Abstract",
                "entry_url": "https://arxiv.org/abs/2603.12254v1",
                "published_date": "2026-03-01",
                "source_type": "arxiv",
            }
        )
        self.assertEqual(suggestion["provider"], "arxiv")
        self.assertEqual(suggestion["id"], "2603.12254v1")

    @patch.object(DiscoveryService, "_generate_answer")
    @patch.object(DiscoveryService, "_search_provider")
    def test_discovery_falls_back_to_other_providers_when_semantic_scholar_is_rate_limited(
        self,
        mock_search_provider,
        mock_generate_answer,
    ):
        mock_generate_answer.return_value = "Transformer overview from discovered sources."

        def _side_effect(provider, query, max_results):
            if provider == "openalex":
                raise TransientExternalError("OpenAlex rate limited (429)")
            if provider == "europepmc":
                return [
                    {
                        "external_id": "PMC1234",
                        "title": "Attention Is All You Need",
                        "authors": ["Ashish Vaswani"],
                        "abstract": "Transformer architecture based on attention.",
                        "published_date": "2017-06-12",
                        "entry_url": "https://europepmc.org/article/MED/1234",
                        "source_type": "europepmc",
                    }
                ]
            return []

        mock_search_provider.side_effect = _side_effect

        result = DiscoveryService().answer_query_from_external_search("Explain transformer architecture")

        self.assertEqual(result["discovery_mode"], "external_search_answer_with_fallback")
        self.assertEqual(result["suggested_sources"][0]["provider"], "europepmc")
        self.assertEqual(result["suggested_sources"][0]["id"], "PMC1234")

    @patch.object(DiscoveryService, "_search_provider")
    def test_discovery_returns_provider_unavailable_response_when_all_searches_fail(
        self,
        mock_search_provider,
    ):
        mock_search_provider.side_effect = TransientExternalError("provider unavailable")

        result = DiscoveryService().answer_query_from_external_search("Explain transformer architecture")

        self.assertEqual(result["discovery_mode"], "external_search_unavailable")
        self.assertTrue(result["is_refusal"])


class ImportUtilsTests(TestCase):
    def test_looks_like_pdf_url_only_accepts_direct_pdf_urls(self):
        self.assertTrue(looks_like_pdf_url("https://example.org/paper.pdf"))
        self.assertFalse(looks_like_pdf_url("https://example.org/landing-page"))

    def test_queue_remote_import_uses_summary_filename_for_non_pdf_url(self):
        session = Session.objects.create(name="queue-remote-summary")
        result = queue_remote_import(
            session_name=session.name,
            source_type="openalex",
            external_id="W123",
            metadata={
                "title": "Landing page only",
                "authors": ["Alice"],
                "abstract": "Abstract",
                "published_date": "2026",
                "entry_url": "https://example.org/article",
            },
            pdf_url="https://example.org/article",
            filename_prefix="openalex",
        )
        doc = Document.objects.get(id=result["document_id"])
        self.assertTrue(doc.filename.endswith("_abstract.txt"))
        self.assertIsNone(doc.storage_path)


class ExternalViewErrorMappingTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    @patch("rag.views_external.SemanticScholarService.search")
    def test_external_search_maps_transient_errors_to_429(self, mock_search):
        mock_search.side_effect = TransientExternalError("Semantic Scholar rate limited (429)")

        response = self.client.get("/api/search/external/?q=llm&source=semanticscholar")

        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data["error"], "Semantic Scholar rate limited (429)")

    @patch("rag.views_external.SemanticScholarService.search")
    def test_external_search_maps_open_circuit_to_503(self, mock_search):
        mock_search.side_effect = CircuitOpenError("Circuit open for provider 'semanticscholar' during 'request'")

        response = self.client.get("/api/search/external/?q=llm&source=semanticscholar")

        self.assertEqual(response.status_code, 503)


class DocumentPageTextTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.session = Session.objects.create(name="page-text-session")

    def test_document_page_text_falls_back_to_metadata_for_virtual_documents(self):
        document = Document.objects.create(
            filename="pubmed_1234.pdf",
            session=self.session,
            title="Sample title",
            abstract="Sample abstract",
            status="INDEXED",
            error_message="Note: Full PDF was unavailable. Summary-only mode.",
        )
        PaperSource.objects.create(
            document=document,
            source_type="pubmed",
            external_id="1234",
            title="Sample title",
            authors="Alice Smith, Bob Jones",
            abstract="Sample abstract",
            entry_url="https://pubmed.ncbi.nlm.nih.gov/1234/",
        )

        response = self.client.get(f"/api/documents/{document.id}/page-text/?page=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["content_type"], "text")
        self.assertIn("TITLE: Sample title", response.data["text"])
        self.assertIn("ABSTRACT:", response.data["text"])


class ExternalImportQueueTests(TestCase):
    @patch.object(SemanticScholarService, "fetch_metadata")
    def test_semantic_scholar_import_enqueues_durable_job(self, mock_fetch_metadata):
        mock_fetch_metadata.return_value = {
            "external_id": "abc123",
            "title": "Queued paper",
            "authors": ["Alice", "Bob"],
            "abstract": "Abstract text",
            "published_date": "2026",
            "entry_url": "https://example.org/paper",
            "pdf_url": "https://example.org/paper.pdf",
            "source_type": "semanticscholar",
        }
        session = Session.objects.create(name="import-session")

        result = SemanticScholarService().import_paper("abc123", session.name)

        self.assertTrue(result["success"])
        self.assertIn("job_id", result)
        job = IngestionJob.objects.get(id=result["job_id"])
        self.assertEqual(job.status, "QUEUED")
        self.assertEqual(job.job_type, "SEMANTIC_SCHOLAR_IMPORT")

    @patch.object(OpenAlexService, "fetch_metadata")
    @patch.object(OpenAlexService, "_resolve_fulltext_url")
    def test_openalex_import_enqueues_remote_pdf_job(
        self,
        mock_resolve_fulltext_url,
        mock_fetch_metadata,
    ):
        mock_fetch_metadata.return_value = {
            "external_id": "W123",
            "title": "OpenAlex paper",
            "authors": ["Alice"],
            "abstract": "Abstract text",
            "published_date": "2026",
            "entry_url": "https://openalex.org/W123",
            "pdf_url": "",
            "doi": "10.1000/test",
            "source_type": "openalex",
        }
        mock_resolve_fulltext_url.return_value = "https://example.org/paper.pdf"
        session = Session.objects.create(name="openalex-import-session")

        result = OpenAlexService().import_paper("W123", session.name)

        self.assertTrue(result["success"])
        job = IngestionJob.objects.get(id=result["job_id"])
        self.assertEqual(job.job_type, "REMOTE_PDF_IMPORT")


class LiteratureReviewSynthesisTests(SimpleTestCase):
    def test_generate_literature_review_formats_structured_cross_paper_output(self):
        docs = [
            type(
                "Doc",
                (),
                {"metadata": {"source": "a.pdf", "page": 0}, "page_content": "A chunk about retrievers."},
            )(),
            type(
                "Doc",
                (),
                {"metadata": {"source": "b.pdf", "page": 1}, "page_content": "B chunk about generation."},
            )(),
        ]

        responses = iter([
            "FOCUS: a.pdf studies retrieval pretraining.\nMETHODS: a.pdf uses retrieval-aware objectives.\nCONTRIBUTIONS: a.pdf improves retrieval-conditioned language modeling.\nLIMITATIONS: a.pdf leaves robustness underexplored.",
            "FOCUS: b.pdf studies retrieval-augmented generation.\nMETHODS: b.pdf injects retrieved evidence during generation.\nCONTRIBUTIONS: b.pdf improves generation with retrieval conditioning.\nLIMITATIONS: b.pdf leaves efficiency tradeoffs partially unresolved.",
            "- a.pdf and b.pdf both rely on explicit retrieval to improve downstream language modeling.",
            "- a.pdf emphasizes pretraining, whereas b.pdf emphasizes generation-time conditioning.",
            "- a.pdf uses retrieval-aware objectives, while b.pdf focuses on conditioning generation on retrieved evidence.",
            "- a.pdf and b.pdf both leave robustness and efficiency tradeoffs only partially resolved.",
            "- Together, a.pdf and b.pdf suggest retrieval is valuable, but system design depends on whether the focus is pretraining or generation.",
        ])
        service = SynthesisService()
        service.llm = type("StubLlm", (), {"invoke": lambda self, prompt: next(responses)})()

        result = service.generate_literature_review("retrieval directions", docs, ["a.pdf", "b.pdf"])

        self.assertEqual(result["num_sources"], 2)
        self.assertIn("1. Scope of Review", result["content"])
        self.assertIn("a.pdf", result["content"])
        self.assertIn("b.pdf", result["content"])
        self.assertNotIn("The text provided appears", result["content"])
        self.assertNotIn("did not return a valid structured review", result["content"])

    def test_generate_literature_review_marks_weakly_related_papers_as_incompatible(self):
        docs = [
            type(
                "Doc",
                (),
                {
                    "metadata": {"source": "vision.pdf", "page": 0},
                    "page_content": "Image segmentation with convolutional encoders and benchmark datasets.",
                },
            )(),
            type(
                "Doc",
                (),
                {
                    "metadata": {"source": "genomics.pdf", "page": 0},
                    "page_content": "Gene expression analysis for oncology cohorts with biomarker discovery pipelines.",
                },
            )(),
        ]

        responses = iter([
            "FOCUS: vision.pdf studies image segmentation benchmarks.\nMETHODS: vision.pdf uses convolutional encoders and dense prediction.\nCONTRIBUTIONS: vision.pdf improves segmentation accuracy on imaging datasets.\nLIMITATIONS: vision.pdf leaves clinical validation unexplored.",
            "FOCUS: genomics.pdf studies cancer biomarker discovery from gene expression data.\nMETHODS: genomics.pdf uses transcriptomic analysis and cohort stratification.\nCONTRIBUTIONS: genomics.pdf identifies genomic biomarkers for oncology cohorts.\nLIMITATIONS: genomics.pdf leaves imaging-based evidence unexplored.",
        ])
        service = SynthesisService()
        service.llm = type("StubLlm", (), {"invoke": lambda self, prompt: next(responses)})()

        result = service.generate_literature_review(
            "retrieval-augmented generation for clinical question answering",
            docs,
            ["vision.pdf", "genomics.pdf"],
        )

        self.assertEqual(result["review_status"], "incompatible_sources")
        self.assertIn("do not support a reliable unified literature review", result["warning"])
        self.assertIn("Why a Unified Review Is Limited", result["content"])
        self.assertNotIn("Common Approaches Across Papers", result["content"])


class CompareSynthesisTests(SimpleTestCase):
    def test_compare_papers_falls_back_to_question_aware_claims_when_json_is_invalid(self):
        docs = [
            type(
                "Doc",
                (),
                {
                    "metadata": {"source": "a.pdf", "page": 0},
                    "page_content": "Paper A uses dense retrieval over Wikipedia passages for generation.",
                },
            )(),
            type(
                "Doc",
                (),
                {
                    "metadata": {"source": "b.pdf", "page": 2},
                    "page_content": "Paper B enriches embeddings with topic signals to improve retrieval precision.",
                },
            )(),
        ]

        responses = iter([
            "Here is the comparison in prose, not JSON.",
            "Still not valid JSON.",
            "QUESTION_FOCUS: a.pdf frames the problem around dense retrieval for generation.\nMETHOD_OR_EVIDENCE: a.pdf retrieves Wikipedia passages with a dense retriever.\nTAKEAWAY: a.pdf changes the generation architecture by coupling it to retrieved passages.",
            "QUESTION_FOCUS: b.pdf frames the problem around improving retrieval quality before generation.\nMETHOD_OR_EVIDENCE: b.pdf augments embeddings with topic signals and term-based structure.\nTAKEAWAY: b.pdf changes the retrieval representation rather than the core generator.",
            "- a.pdf changes the RAG pipeline by coupling generation to dense passage retrieval, whereas b.pdf changes retrieval representation through topic-enriched embeddings.\n- a.pdf emphasizes end-to-end retrieval-augmented generation, while b.pdf emphasizes improving retrieval precision before generation.",
        ])
        service = SynthesisService()
        service.llm = type("StubLlm", (), {"invoke": lambda self, prompt: next(responses)})()

        result = service.compare_papers(
            "How do the papers differ in retrieval?",
            docs,
            ["a.pdf", "b.pdf"],
        )

        self.assertEqual(result["num_papers"], 2)
        self.assertEqual(len(result["claims"]), 2)
        self.assertIn("simplified comparison", result["message"])
        self.assertEqual(result["claims"][0]["papers"][0]["stance"], "supports")
        self.assertTrue(result["claims"][0]["papers"][0]["evidence"])
        self.assertIn("whereas", result["claims"][0]["claim"])
        self.assertIn("a.pdf", result["claims"][0]["claim"])
        self.assertIn("b.pdf", result["claims"][0]["claim"])


class IngestionJobRunnerTests(TestCase):
    def test_document_ingestion_error_result_marks_job_failed(self):
        session = Session.objects.create(name="runner-session")
        document = Document.objects.create(
            filename="broken.pdf",
            session=session,
            status="QUEUED",
            storage_path="pdfs/broken.pdf",
        )
        job, _ = enqueue_job(
            "DOCUMENT_INGEST",
            document=document,
            session=session,
            payload={"document_id": document.id},
            max_attempts=1,
        )

        runner = IngestionJobRunner()
        runner.ingestion_service = Mock()
        runner.ingestion_service.ingest_document.return_value = {
            "status": "error",
            "message": "embedding model missing",
        }

        with patch("rag.services.ingestion_jobs.default_storage.exists", return_value=True), patch(
            "rag.services.ingestion_jobs.default_storage.path",
            return_value="/tmp/broken.pdf",
        ):
            processed = runner.process_next_job()

        processed.refresh_from_db()
        document.refresh_from_db()
        self.assertEqual(processed.status, "FAILED")
        self.assertEqual(document.status, "FAILED")
        self.assertIn("embedding model missing", processed.last_error)
