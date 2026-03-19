import tempfile
from unittest.mock import Mock, patch

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from langchain_core.documents import Document as LangchainDocument
from rest_framework.test import APIClient

from rag.models import Document, IngestionJob, PaperSource, Session
from rag.services.ingestion_jobs import IngestionJobRunner
from rag.services.retrieval import ScoredDocument


class ApiFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.session_name = "e2e-session"
        Session.objects.create(name=self.session_name)

    def test_upload_and_list_documents_flow(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            file_obj = SimpleUploadedFile(
                "sample.pdf",
                b"%PDF-1.4 fake",
                content_type="application/pdf",
            )

            upload_response = self.client.post(
                "/api/upload/",
                {"file": file_obj, "session": self.session_name},
                format="multipart",
            )
            self.assertEqual(upload_response.status_code, 202)
            self.assertIn("document_id", upload_response.data)
            self.assertTrue(Document.objects.filter(id=upload_response.data["document_id"]).exists())
            self.assertTrue(IngestionJob.objects.filter(id=upload_response.data["job_id"]).exists())

            list_response = self.client.get(f"/api/pdfs/?session={self.session_name}")
            self.assertEqual(list_response.status_code, 200)
            self.assertEqual(len(list_response.data["pdfs"]), 1)
            self.assertEqual(list_response.data["pdfs"][0]["storage_path"], "pdfs/sample.pdf")
            self.assertEqual(list_response.data["pdfs"][0]["file_url"], "/media/pdfs/sample.pdf")

    def test_duplicate_upload_name_keeps_real_storage_path(self):
        other_session = Session.objects.create(name="other-session")

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            first_upload = self.client.post(
                "/api/upload/",
                {
                    "file": SimpleUploadedFile("sample.pdf", b"%PDF-1.4 first", content_type="application/pdf"),
                    "session": self.session_name,
                },
                format="multipart",
            )
            self.assertEqual(first_upload.status_code, 202)

            second_upload = self.client.post(
                "/api/upload/",
                {
                    "file": SimpleUploadedFile("sample.pdf", b"%PDF-1.4 second", content_type="application/pdf"),
                    "session": other_session.name,
                },
                format="multipart",
            )
            self.assertEqual(second_upload.status_code, 202)

            second_doc = Document.objects.get(id=second_upload.data["document_id"])
            self.assertEqual(second_doc.filename, "sample.pdf")
            self.assertTrue(second_doc.storage_path.startswith("pdfs/sample_"))
            self.assertNotEqual(second_doc.storage_path, "pdfs/sample.pdf")

            list_response = self.client.get(f"/api/pdfs/?session={other_session.name}")
            self.assertEqual(list_response.status_code, 200)
            self.assertEqual(list_response.data["pdfs"][0]["storage_path"], second_doc.storage_path)
            self.assertEqual(list_response.data["pdfs"][0]["file_url"], f"/media/{second_doc.storage_path}")

    def test_upload_recreates_missing_named_session(self):
        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            upload_response = self.client.post(
                "/api/upload/",
                {
                    "file": SimpleUploadedFile("recovered.pdf", b"%PDF-1.4 fake", content_type="application/pdf"),
                    "session": "Recovered Session",
                },
                format="multipart",
            )

            self.assertEqual(upload_response.status_code, 202)
            self.assertTrue(Session.objects.filter(name="Recovered Session").exists())

    def test_session_can_be_renamed_and_pinned(self):
        response = self.client.patch(
            f"/api/session/{self.session_name}/",
            {"name": "renamed-session", "pinned": True},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(Session.objects.filter(name="renamed-session", pinned=True).exists())
        self.assertFalse(Session.objects.filter(name=self.session_name).exists())

    @patch("rag.services.ingestion.IngestionService.ingest_document")
    def test_worker_processes_queued_upload_job(self, mock_ingest_document):
        mock_ingest_document.return_value = {"status": "success"}

        with tempfile.TemporaryDirectory() as media_root, self.settings(MEDIA_ROOT=media_root):
            upload_response = self.client.post(
                "/api/upload/",
                {
                    "file": SimpleUploadedFile("queued.pdf", b"%PDF-1.4 fake", content_type="application/pdf"),
                    "session": self.session_name,
                },
                format="multipart",
            )

            self.assertEqual(upload_response.status_code, 202)
            job = IngestionJob.objects.get(id=upload_response.data["job_id"])
            self.assertEqual(job.status, "QUEUED")

            call_command("process_ingestion_jobs", "--once")

            job.refresh_from_db()
            self.assertEqual(job.status, "SUCCEEDED")
            mock_ingest_document.assert_called_once()

    @patch("rag.views.ask_with_citations")
    def test_ask_returns_citations(self, mock_ask_with_citations):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(
            filename="qa.pdf",
            session=session,
            status="INDEXED",
        )
        mock_ask_with_citations.return_value = {
            "answer": "Test answer",
            "citations": [
                {
                    "source": doc.filename,
                    "page": 0,
                    "chunk_id": "c1",
                    "snippet": "evidence",
                    "score": 0.91,
                }
            ],
            "is_refusal": False,
            "is_insufficient_evidence": False,
            "retrieved_chunks_count": 1,
            "confidence_score": 0.91,
        }

        response = self.client.post(
            "/api/ask/",
            {
                "question": "What is the evidence?",
                "session": self.session_name,
                "sources": [doc.filename],
                "mode": "qa",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["answer"], "Test answer")
        self.assertEqual(len(response.data["citations"]), 1)
        self.assertEqual(response.data["citations"][0]["source"], doc.filename)

    @patch("rag.views.DiscoveryService.answer_query_from_external_search")
    def test_ask_without_selected_sources_uses_external_discovery_for_specific_query(
        self,
        mock_answer_query_from_external_search,
    ):
        mock_answer_query_from_external_search.return_value = {
            "answer": "Abstract-grounded answer.",
            "citations": [],
            "is_refusal": False,
            "is_insufficient_evidence": False,
            "retrieved_chunks_count": 3,
            "confidence_score": 0.68,
            "discovery_mode": "external_search_answer",
            "source_basis": "abstracts_and_metadata",
            "suggested_sources": [
                {"id": "abc123", "title": "Paper A", "provider": "semanticscholar"}
            ],
        }

        response = self.client.post(
            "/api/ask/",
            {
                "question": "What do papers say about retrieval-augmented generation for clinical decision support?",
                "session": self.session_name,
                "sources": [],
                "mode": "qa",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["discovery_mode"], "external_search_answer")
        self.assertEqual(len(response.data["suggested_sources"]), 1)
        mock_answer_query_from_external_search.assert_called_once()

    def test_ask_without_selected_sources_abstains_for_broad_query(self):
        response = self.client.post(
            "/api/ask/",
            {
                "question": "What is intelligence?",
                "session": self.session_name,
                "sources": [],
                "mode": "qa",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_refusal"])
        self.assertEqual(response.data["discovery_mode"], "abstain_no_context")

    def test_lit_review_requires_two_selected_documents(self):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(filename="solo.pdf", session=session, status="INDEXED")

        response = self.client.post(
            "/api/ask/",
            {
                "question": "Summarize themes and gaps",
                "session": self.session_name,
                "sources": [doc.filename],
                "mode": "lit_review",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("requires at least 2", response.data["error"])

    @patch("rag.views.SynthesisService.generate_literature_review")
    @patch("rag.views.RetrievalService.retrieve")
    def test_lit_review_returns_citations_for_cross_paper_synthesis(
        self,
        mock_retrieve,
        mock_generate_review,
    ):
        session = Session.objects.get(name=self.session_name)
        doc_a = Document.objects.create(filename="a.pdf", session=session, status="INDEXED")
        doc_b = Document.objects.create(filename="b.pdf", session=session, status="INDEXED")
        mock_retrieve.return_value = [
            ScoredDocument(
                LangchainDocument(page_content="Shared approach", metadata={"source": doc_a.filename, "page": 0}),
                score=0.9,
                chunk_id="a1",
            ),
            ScoredDocument(
                LangchainDocument(page_content="Open problem", metadata={"source": doc_b.filename, "page": 1}),
                score=0.8,
                chunk_id="b1",
            ),
        ]
        mock_generate_review.return_value = {
            "title": "Literature Review: test",
            "content": "Structured review",
            "num_sources": 2,
        }

        response = self.client.post(
            "/api/ask/",
            {
                "question": "Summarize themes and gaps",
                "session": self.session_name,
                "sources": [doc_a.filename, doc_b.filename],
                "mode": "lit_review",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["content"], "Structured review")
        self.assertEqual(len(response.data["citations"]), 2)

    @patch("rag.views.SynthesisService.generate_literature_review")
    @patch("rag.views.RetrievalService.retrieve")
    def test_lit_review_balances_retrieval_across_selected_sources(
        self,
        mock_retrieve,
        mock_generate_review,
    ):
        session = Session.objects.get(name=self.session_name)
        doc_a = Document.objects.create(filename="a.pdf", session=session, status="INDEXED")
        doc_b = Document.objects.create(filename="b.pdf", session=session, status="INDEXED")

        def _retrieve(*, query, sources, k, use_hybrid, use_multi_query, use_reranking):
            source = sources[0]
            return [
                ScoredDocument(
                    LangchainDocument(
                        page_content=f"chunk for {source}",
                        metadata={"source": source, "page": 0},
                    ),
                    score=0.9 if source == "a.pdf" else 0.8,
                    chunk_id=f"{source}-1",
                )
            ]

        mock_retrieve.side_effect = _retrieve
        mock_generate_review.return_value = {
            "title": "Literature Review: test",
            "content": "Structured review",
            "num_sources": 2,
        }

        response = self.client.post(
            "/api/ask/",
            {
                "question": "What are the main directions?",
                "session": self.session_name,
                "sources": [doc_a.filename, doc_b.filename],
                "mode": "lit_review",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(mock_retrieve.call_count, 2)
        called_sources = {call.kwargs["sources"][0] for call in mock_retrieve.call_args_list}
        self.assertEqual(called_sources, {"a.pdf", "b.pdf"})

    @patch("rag.views.SynthesisService.generate_literature_review")
    @patch("rag.views.RetrievalService.retrieve")
    def test_lit_review_exposes_warning_metadata(
        self,
        mock_retrieve,
        mock_generate_review,
    ):
        session = Session.objects.get(name=self.session_name)
        doc_a = Document.objects.create(filename="a.pdf", session=session, status="INDEXED")
        doc_b = Document.objects.create(filename="b.pdf", session=session, status="INDEXED")

        def _retrieve(*, query, sources, k, use_hybrid, use_multi_query, use_reranking):
            source = sources[0]
            return [
                ScoredDocument(
                    LangchainDocument(
                        page_content=f"chunk for {source}",
                        metadata={"source": source, "page": 0},
                    ),
                    score=0.82,
                    chunk_id=f"{source}-1",
                )
            ]

        mock_retrieve.side_effect = _retrieve
        mock_generate_review.return_value = {
            "title": "Literature Review: weak overlap",
            "content": "Structured review with caveats",
            "num_sources": 2,
            "review_status": "warning_review",
            "warning": "The selected papers only partially overlap with the requested topic.",
            "review_diagnostics": {"pairwise_overlap": 0.11},
        }

        response = self.client.post(
            "/api/ask/",
            {
                "question": "What are the main directions?",
                "session": self.session_name,
                "sources": [doc_a.filename, doc_b.filename],
                "mode": "lit_review",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["review_status"], "warning_review")
        self.assertIn("partially overlap", response.data["warning"])
        self.assertEqual(response.data["review_diagnostics"]["pairwise_overlap"], 0.11)

    @patch("rag.views.SynthesisService.generate_literature_review")
    @patch("rag.views.RetrievalService.retrieve")
    def test_lit_review_rejects_forced_review_when_evidence_is_single_source(
        self,
        mock_retrieve,
        mock_generate_review,
    ):
        session = Session.objects.get(name=self.session_name)
        doc_a = Document.objects.create(filename="a.pdf", session=session, status="INDEXED")
        doc_b = Document.objects.create(filename="b.pdf", session=session, status="INDEXED")

        def _retrieve(*, query, sources, k, use_hybrid, use_multi_query, use_reranking):
            source = sources[0]
            if source == "a.pdf":
                return [
                    ScoredDocument(
                        LangchainDocument(
                            page_content="relevant chunk for a.pdf",
                            metadata={"source": source, "page": 0},
                        ),
                        score=0.9,
                        chunk_id="a-1",
                    )
                ]
            return []

        mock_retrieve.side_effect = _retrieve

        response = self.client.post(
            "/api/ask/",
            {
                "question": "Produce a literature review",
                "session": self.session_name,
                "sources": [doc_a.filename, doc_b.filename],
                "mode": "lit_review",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["review_status"], "incompatible_sources")
        self.assertIn("at least two different selected papers", response.data["content"])
        mock_generate_review.assert_not_called()

    @patch("rag.views_highlights.HighlightService.index_highlight")
    @patch("rag.views_highlights.HighlightService.search_highlights")
    def test_highlight_create_and_search_flow(
        self,
        mock_search_highlights,
        mock_index_highlight,
    ):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(filename="hl.pdf", session=session, status="INDEXED")
        mock_index_highlight.return_value = "hl_1"
        mock_search_highlights.return_value = [
            {
                "id": 1,
                "document_id": doc.id,
                "filename": doc.filename,
                "page": 1,
                "start_offset": 0,
                "end_offset": 10,
                "text": "highlight text",
                "note": "",
                "tags": [],
                "score": 0.8,
            }
        ]

        create_res = self.client.post(
            "/api/highlights/",
            {
                "document_id": doc.id,
                "page": 1,
                "start_offset": 0,
                "end_offset": 14,
                "text": "highlight text",
                "note": "note",
                "tags": ["tag1"],
            },
            format="json",
        )
        self.assertEqual(create_res.status_code, 201)
        self.assertEqual(create_res.data["filename"], doc.filename)
        self.assertTrue(create_res.data["embedding_indexed"])

        search_res = self.client.get(
            f"/api/highlights/search/?session={self.session_name}&q=highlight"
        )
        self.assertEqual(search_res.status_code, 200)
        self.assertEqual(len(search_res.data["results"]), 1)
        self.assertEqual(search_res.data["results"][0]["filename"], doc.filename)

    @patch("rag.services.ollama_client.create_embeddings")
    @patch("langchain_chroma.Chroma")
    @patch("rag.views.default_storage.delete")
    @patch("rag.views.default_storage.exists")
    def test_delete_pdf_uses_document_storage_path(
        self,
        mock_exists,
        mock_delete,
        mock_chroma_cls,
        mock_create_embeddings,
    ):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(
            filename="sample.pdf",
            storage_path="pdfs/sample_abcd123.pdf",
            session=session,
            status="INDEXED",
        )
        mock_exists.return_value = True
        mock_create_embeddings.return_value = Mock()
        mock_chroma = Mock()
        mock_chroma.get.return_value = {"ids": []}
        mock_chroma_cls.return_value = mock_chroma

        response = self.client.delete(
            "/api/delete/",
            {"session": self.session_name, "filename": doc.filename},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        mock_delete.assert_called_once_with("pdfs/sample_abcd123.pdf")

    @patch("rag.views_discovery.OpenAlexService.fetch_paper_graph")
    def test_related_papers_endpoint_uses_openalex_source_when_available(
        self,
        mock_fetch_paper_graph,
    ):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(filename="paper.pdf", session=session, status="INDEXED", title="Paper")
        PaperSource.objects.create(
            document=doc,
            source_type="openalex",
            external_id="W123",
            title="Paper",
            authors="Alice",
            abstract="Abstract",
        )
        mock_fetch_paper_graph.return_value = {
            "paper": {"id": "W123", "title": "Paper"},
            "references": [{"id": "ref-1", "title": "Reference"}],
            "citations": [],
            "related": [],
            "graph_source": "openalex",
        }

        response = self.client.get(f"/api/papers/related/?document_id={doc.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["paper"]["id"], "W123")
        self.assertEqual(len(response.data["references"]), 1)

    @patch("rag.views_discovery.DiscoveryService.discover_candidates")
    @patch("rag.views_discovery.OpenAlexService.resolve_best_match")
    @patch("rag.views_discovery.OpenAlexService.fetch_paper_graph")
    def test_related_papers_endpoint_resolves_non_openalex_source_before_fallback(
        self,
        mock_fetch_paper_graph,
        mock_resolve_best_match,
        mock_discover_candidates,
    ):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(filename="paper.pdf", session=session, status="INDEXED", title="Paper")
        PaperSource.objects.create(
            document=doc,
            source_type="arxiv",
            external_id="2603.12254v1",
            title="Paper",
            authors="Alice",
            abstract="Abstract",
        )
        mock_resolve_best_match.return_value = {"external_id": "W999"}
        mock_fetch_paper_graph.return_value = {
            "paper": {"id": "W999", "title": "Paper"},
            "references": [],
            "citations": [],
            "related": [{"id": "2603.12254v1", "provider": "arxiv", "title": "Related"}],
            "graph_source": "openalex",
        }

        response = self.client.get(f"/api/papers/related/?document_id={doc.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["paper"]["id"], "W999")
        mock_discover_candidates.assert_not_called()

    @patch("rag.views_discovery.DiscoveryService.discover_candidates")
    @patch("rag.views_discovery.OpenAlexService.resolve_best_match")
    def test_related_papers_endpoint_uses_multi_provider_fallback_when_no_graph_seed_found(
        self,
        mock_resolve_best_match,
        mock_discover_candidates,
    ):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(filename="paper.pdf", session=session, status="INDEXED", title="RAG paper")
        PaperSource.objects.create(
            document=doc,
            source_type="manual",
            external_id="manual-1",
            title="RAG paper",
            authors="Alice",
            abstract="Abstract",
        )
        mock_resolve_best_match.return_value = {}
        mock_discover_candidates.return_value = [
            {"id": "2603.12254v1", "provider": "arxiv", "title": "Related"}
        ]

        response = self.client.get(f"/api/papers/related/?document_id={doc.id}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["graph_source"], "multi_provider_fallback")
        self.assertEqual(len(response.data["related"]), 1)

    def test_about_paper_question_uses_metadata_overview_for_summary_only_source(self):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(
            filename="summary_only_abstract.txt",
            session=session,
            status="INDEXED",
            title="Summary Only Paper",
            abstract="This paper studies retrieval-augmented generation for clinical settings.",
            error_message="Note: Full PDF was unavailable. Summary-only mode.",
        )
        PaperSource.objects.create(
            document=doc,
            source_type="openalex",
            external_id="W123",
            title=doc.title,
            authors="Alice, Bob",
            abstract=doc.abstract,
        )

        response = self.client.post(
            "/api/ask/",
            {
                "question": "what's this paper about?",
                "session": self.session_name,
                "sources": [doc.filename],
                "mode": "qa",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Summary Only Paper", response.data["answer"])
        self.assertIn("source metadata", response.data["answer"])
        self.assertFalse(response.data["is_refusal"])

    def test_about_paper_question_is_explicit_when_summary_only_source_has_no_abstract(self):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(
            filename="europepmc_1234_abstract.txt",
            session=session,
            status="INDEXED",
            title="Beyond automation: what's next for artificial intelligence in sleep?",
            abstract="No abstract available.",
            error_message="Note: Full PDF was unavailable. Summary-only mode.",
        )
        PaperSource.objects.create(
            document=doc,
            source_type="europepmc",
            external_id="40657850",
            title=doc.title,
            authors="Abou Jaoude M.",
            abstract="",
            entry_url="https://europepmc.org/article/MED/40657850",
        )

        response = self.client.post(
            "/api/ask/",
            {
                "question": "what's this paper about?",
                "session": self.session_name,
                "sources": [doc.filename],
                "mode": "qa",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("bibliographic metadata", response.data["answer"])
        self.assertIn("cannot reliably answer what the paper is about", response.data["answer"])
        self.assertIn("https://europepmc.org/article/MED/40657850", response.data["answer"])

    @patch("rag.services.ingestion_jobs.IngestionService.ingest_metadata_only")
    @patch("rag.services.ingestion_jobs.requests.get")
    def test_remote_pdf_import_rejects_html_landing_page_and_falls_back_to_summary(
        self,
        mock_get,
        mock_ingest_metadata_only,
    ):
        session = Session.objects.get(name=self.session_name)
        doc = Document.objects.create(
            filename="openalex_W123.pdf",
            storage_path="pdfs/openalex_W123.pdf",
            session=session,
            status="QUEUED",
            title="Paper",
            abstract="Abstract",
        )
        source = PaperSource.objects.create(
            document=doc,
            source_type="openalex",
            external_id="W123",
            title="Paper",
            authors="Alice",
            abstract="Abstract",
            pdf_url="https://example.org/landing-page",
            entry_url="https://example.org/landing-page",
        )
        response = Mock()
        response.raise_for_status.return_value = None
        response.headers = {"Content-Type": "text/html"}
        response.iter_content.return_value = iter([b"<html>not a pdf</html>"])
        mock_get.return_value = response
        def _fake_ingest_metadata_only(document_id, title, abstract, authors):
            fallback_doc = Document.objects.get(id=document_id)
            fallback_doc.status = "INDEXED"
            fallback_doc.title = title
            fallback_doc.abstract = abstract
            fallback_doc.error_message = "Note: Full PDF was unavailable. Summary-only mode."
            fallback_doc.save(update_fields=["status", "title", "abstract", "error_message"])
            return {"status": "success", "virtual": True}

        mock_ingest_metadata_only.side_effect = _fake_ingest_metadata_only

        runner = IngestionJobRunner()
        runner._run_remote_pdf_import(
            document_id=doc.id,
            paper_source_id=source.id,
            metadata={"title": "Paper", "abstract": "Abstract", "authors": ["Alice"]},
            pdf_url="https://example.org/landing-page",
            storage_path="pdfs/openalex_W123.pdf",
        )

        doc.refresh_from_db()
        self.assertEqual(doc.status, "INDEXED")
        self.assertIn("Summary-only mode", doc.error_message)
        self.assertTrue(doc.filename.endswith("_abstract.txt"))
        self.assertIsNone(doc.storage_path)
