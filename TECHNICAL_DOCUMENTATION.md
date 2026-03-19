# Technical Documentation: Scientific Research Navigator

This document describes the current implementation of Scientific Research Navigator, including runtime architecture, request lifecycles, provider strategy, retrieval behavior, ingestion semantics, fallback logic, and operational tradeoffs.

It is written to reflect the repository's current codepaths rather than the original design intent.

## 1. System Overview

Scientific Research Navigator is a session-based scientific paper workspace composed of:
- a Django + DRF backend in `backend/rag`
- a React frontend in `frontend/src`
- Ollama-hosted local models for embeddings and text generation
- session-scoped Chroma vector stores
- relational persistence for sessions, documents, answers, run logs, and highlights

The system supports two major interaction styles:
- local-context workflows over uploaded/imported sources
- discovery-driven workflows where no source is selected and the backend finds candidate papers first

The core design principle is:
- keep each session isolated while still allowing iterative corpus growth through paper discovery and import

## 2. Runtime Architecture

### 2.1 Backend Runtime

Backend stack:
- Django
- Django REST Framework
- function-based API views

Primary locations:
- settings: `backend/config/settings.py`
- root URLs: `backend/config/urls.py`
- application URLs: `backend/rag/urls.py`
- core views: `backend/rag/views.py`

The backend is responsible for:
- session management
- document ingestion
- external discovery
- import orchestration
- retrieval and QA
- synthesis modes
- highlight indexing/search
- run logging and metrics aggregation

### 2.2 Frontend Runtime

Frontend stack:
- React
- single stateful application component in `frontend/src/App.js`
- API client in `frontend/src/api.js`

The frontend is responsible for:
- session switching
- source list management
- mode switching
- document upload flow
- external search/import flow
- chat rendering
- citation drawer / PDF.js viewer
- related-paper discovery panel
- highlight CRUD and search

### 2.3 Persistent Storage Layers

Relational database:
- sessions
- documents
- paper metadata
- questions / answers
- ingestion jobs
- run logs
- highlights

Media storage:
- uploaded/imported PDFs under Django media storage, typically `media/pdfs/`

Vector storage:
- Chroma session directories under `CHROMA_PERSIST_DIR/<session_name>`
- highlights stored in a dedicated collection in the same session path

## 3. Domain Model

Defined primarily in `backend/rag/models.py`.

### 3.1 Session

Represents an isolated research workspace.

Key semantics:
- unique `name`
- owns documents, questions, run logs, and ingestion jobs
- maps to one Chroma persist directory

### 3.2 Document

Represents an uploaded PDF or a virtual metadata-only imported source.

Important fields:
- `filename`
- `storage_path`
- `session`
- `title`
- `abstract`
- `page_count`
- `status`
- `processing_started_at`
- `processing_completed_at`
- `error_message`

Status lifecycle:
- `UPLOADED`
- `QUEUED`
- `PROCESSING`
- `INDEXED`
- `FAILED`

Semantic meaning:
- a document can be a real PDF or a summary-only virtual source
- summary-only sources are still indexed into Chroma
- `error_message` is used both for failures and for explicit notes such as summary-only mode

### 3.3 PaperSource

Tracks external-paper provenance and metadata.

Important fields:
- `source_type`
- `external_id`
- `document`
- `title`
- `authors`
- `abstract`
- `published_date`
- `pdf_url`
- `entry_url`
- `imported`

Current `source_type` values include:
- `arxiv`
- `pubmed`
- `doi`
- `openalex`
- `europepmc`
- `core`
- `manual`
- `acl`
- `medrxiv`

Semantic meaning:
- `PaperSource` is the canonical record of external identity
- `Document` is the local ingestable artifact
- a document may exist without a usable PDF but still be linked to a paper source

### 3.4 IngestionJob

Database-backed durable job model for ingestion and import operations.

Supported `job_type` values:
- `DOCUMENT_INGEST`
- `ARXIV_IMPORT`
- `PUBMED_IMPORT`
- `SEMANTIC_SCHOLAR_IMPORT`
- `REMOTE_PDF_IMPORT`

Important fields:
- `status`
- `payload`
- `document`
- `paper_source`
- `session`
- `attempts`
- `max_attempts`
- `available_at`
- `worker_id`

Semantic meaning:
- ingestion/import work is durable and retryable
- the worker process pulls queued jobs from the database
- failures are retried with exponential backoff

### 3.5 Question and Answer

`Question`:
- belongs to a session
- stores the raw user text

`Answer`:
- one-to-one with `Question`
- stores:
  - answer text
  - citation payload
  - structured metadata

`Answer.metadata` is used for:
- compare mode payloads
- literature review titles
- discovery mode annotations
- suggested paper lists

### 3.6 RunLog

Stores telemetry for each ask request.

Tracks:
- mode
- selected sources
- latency
- retrieval timing
- generation timing
- retrieved chunks
- refusal / insufficient-evidence flags
- confidence score
- error metadata

### 3.7 Highlight and HighlightEmbedding

`Highlight` stores:
- document reference
- page and character offsets
- text
- note
- tags

`HighlightEmbedding` stores:
- one vector identity per highlight

Highlights are searchable semantically and lexically.

## 4. API Surface

Declared in `backend/rag/urls.py`.

### 4.1 Session APIs

- `POST /api/session/`
- `GET /api/sessions/`
- `DELETE /api/session/<session_name>/`

Behavior:
- create-or-get by name
- session deletion also attempts Chroma cleanup and file cleanup

### 4.2 Document APIs

- `POST /api/upload/`
- `GET /api/pdfs/?session=<name>`
- `DELETE /api/delete/`
- `GET /api/documents/<id>/status/`
- `GET /api/documents/<id>/page-text/?page=<1-indexed>`
- `POST /api/documents/<id>/retry/`

Behavior:
- uploads create `Document` + `IngestionJob`
- listing returns both local and imported sources
- page text returns PDF text when available, otherwise metadata-only synthetic content

### 4.3 Ask / History APIs

- `POST /api/ask/`
- `GET /api/history/?session=<name>`

Behavior:
- `ask` orchestrates QA, compare, literature review, and no-context discovery
- `history` reconstructs user/assistant turns from `Question` and `Answer`

### 4.4 External Search / Import APIs

- `GET /api/search/external/?q=...&source=...`
- `POST /api/import/external/`
- `GET /api/papers/related/`

Behavior:
- `search/external` performs direct provider search
- `import/external` queues provider-specific or generic remote import jobs
- `papers/related` returns citation-graph or fallback discovery output for a source

### 4.5 Highlight APIs

- `GET|POST /api/highlights/`
- `DELETE /api/highlights/<id>/`
- `GET /api/highlights/search/?session=...&q=...`

### 4.6 Metrics API

- `GET /api/metrics/summary/?since=<days>`

## 5. Ingestion and Import Pipeline

Primary modules:
- `backend/rag/services/ingestion.py`
- `backend/rag/services/ingestion_jobs.py`
- `backend/rag/services/import_utils.py`

### 5.1 Local PDF Ingestion

`IngestionService.ingest_document(...)`:
1. load PDF with `PyPDFLoader`
2. extract title/abstract heuristically from first page
3. tag each page with source metadata
4. split into chunks with `RecursiveCharacterTextSplitter`
5. embed and store in session Chroma
6. mark `Document` as `INDEXED`

Failure:
- mark `Document` as `FAILED`
- store the error message

### 5.2 Metadata-only Ingestion

`IngestionService.ingest_metadata_only(...)` creates a virtual document from:
- title
- authors
- abstract

The resulting text is indexed into Chroma as a synthetic page-0 document.

The document is marked:
- `INDEXED`
- with `error_message = "Note: Full PDF was unavailable. Summary-only mode."`

### 5.3 Remote Import Queueing

`queue_remote_import(...)`:
- normalizes provider metadata
- creates or updates the `Document`
- creates or updates the `PaperSource`
- chooses filename suffix:
  - `.pdf` only if the URL looks like a direct PDF
  - `_abstract.txt` otherwise
- queues a `REMOTE_PDF_IMPORT` job

### 5.4 Remote PDF Import Execution

`IngestionJobRunner._run_remote_pdf_import(...)`:
- downloads the remote URL if present
- verifies that the URL looks like a PDF
- verifies that the response is actually a PDF via:
  - `Content-Type`
  - `Content-Disposition`
  - PDF magic bytes (`%PDF-`)
- if validation passes:
  - ingest as a real PDF
- if validation fails:
  - fall back to metadata-only ingestion

This is intentionally conservative:
- landing pages are not treated as PDFs
- HTML masquerading as PDF is rejected

### 5.5 Worker Execution Model

`python manage.py process_ingestion_jobs` runs the job worker.

Behavior:
- claims the next queued job
- marks it `RUNNING`
- executes the handler
- marks `SUCCEEDED` or requeues / fails with backoff

Important operational note:
- the job queue is durable because it is database-backed
- the worker is not automatic; it must be running as a separate process

## 6. Retrieval and QA Pipeline

Primary modules:
- `backend/rag/query.py`
- `backend/rag/services/retrieval.py`
- `backend/rag/views.py`

### 6.1 RetrievalService

Supports:
- Chroma vector retrieval
- optional BM25 lexical retrieval
- reciprocal-rank fusion
- optional multi-query expansion
- optional reranking
- source filtering

Returned objects are wrapped in `ScoredDocument`, which standardizes:
- score
- chunk identity
- citation serialization
- snippet extraction

### 6.2 Default QA Flow

When selected sources are present:
1. retrieve chunks from the selected source subset
2. build a grounded prompt
3. generate an answer from retrieved evidence
4. attach chunk citations
5. compute confidence / refusal metadata
6. persist `Question`, `Answer`, and `RunLog`

### 6.3 Specialized QA Shortcuts

Before default retrieval, `views.ask_question` checks for specialized intents:
- title questions
- page-count questions
- about-paper questions

About-paper behavior:
- for normal PDF-backed papers, retrieve overview chunks and run QA
- for summary-only papers, answer directly from stored metadata instead of abstaining

This is important because summary-only sources do not have full paper structure but still need to answer overview-style questions.

### 6.4 No-context QA Routing

When no sources are selected in `qa` mode:
- classify whether the question is scholarly and topic-oriented
- if yes:
  - use external discovery
  - synthesize an answer from discovered abstracts/metadata
  - return suggested sources
- if no:
  - abstain

The answer metadata stores:
- `discovery_mode`
- `source_basis`
- `suggested_sources`

## 7. Compare and Literature Review Modes

Implemented in `views.ask_question` and `services/synthesis.py`.

### 7.1 Compare Mode

Behavior:
- requires at least 2 distinct selected sources
- performs balanced per-source retrieval
- avoids source imbalance by retrieving from each selected paper independently first
- synthesizes structured claims and stances

If retrieved evidence does not cover at least 2 papers:
- returns an explicit insufficiency result

### 7.2 Literature Review Mode

Behavior:
- requires at least 2 selected papers
- retrieves balanced evidence across papers
- synthesizes:
  - scope
  - paper-by-paper summaries
  - common approaches
  - differences
  - methodological patterns
  - open problems
  - practical takeaways

## 8. Discovery Architecture

Primary modules:
- `backend/rag/services/discovery.py`
- `backend/rag/services/openalex_service.py`
- `backend/rag/services/europepmc_service.py`
- `backend/rag/services/arxiv_service.py`
- `backend/rag/views_discovery.py`

### 8.1 Discovery Provider Strategy

The discovery layer is not single-provider.

Current strategy:
- `OpenAlex`
  - primary discovery provider
  - graph traversal provider
- `Europe PMC`
  - biomedical-first discovery provider
- `arXiv`
  - AI / LLM / RAG / transformer-first discovery provider

Provider order depends on the query:
- AI-topic queries prefer `arxiv -> openalex -> europepmc`
- biomedical queries prefer `europepmc -> openalex`
- generic scholarly queries use the default order

### 8.2 Query Normalization and Ranking

`DiscoveryService`:
- normalizes scholarly queries
- builds query variants
- searches providers with caching
- merges candidates
- ranks them by token overlap and recency heuristics

The goal is:
- better discovery answers
- better suggested papers
- reduced dependence on any one provider

### 8.3 Related-paper Discovery

`GET /api/papers/related/` behaves as follows:

1. If the current source is already an OpenAlex paper:
   - fetch OpenAlex graph:
     - references
     - citations
     - related works

2. If the current source is not OpenAlex but has enough metadata:
   - try to resolve it to an OpenAlex seed using:
     - title
     - arXiv ID
     - DOI

3. If OpenAlex graph seeding fails:
   - fall back to multi-provider discovery using the same discovery stack as no-context QA

This is why `Discover` can now work for:
- OpenAlex imports
- arXiv imports
- some DOI-backed / manually imported papers

### 8.4 Related-item Importability

Graph items preserve import hints:
- if an OpenAlex work exposes an `arxiv_id`, related items are emitted as:
  - `provider = arxiv`
  - `id = <arxiv_id>`
- otherwise the provider remains OpenAlex

This matters because:
- importing an AI paper through arXiv is usually better for full-text availability than importing the same paper through pure OpenAlex metadata

## 9. External Import Strategy

### 9.1 Discovery vs Full-text Acquisition

The system separates:
- paper discovery
- full-text acquisition

Discovery can succeed while full-text acquisition fails.

### 9.2 Full-text Resolution Order

For OpenAlex-driven imports, the resolver attempts:
1. OpenAlex content API
2. arXiv PDF if an arXiv ID exists
3. CORE full-text lookup
4. DOI OA resolution via Crossref / Unpaywall
5. provider-native PDF URL
6. metadata-only fallback

### 9.3 Europe PMC Imports

Europe PMC imports attempt:
1. CORE
2. DOI OA resolution
3. provider-native PDF URL
4. metadata-only fallback

### 9.4 arXiv Imports

arXiv imports:
- use the arXiv API directly
- download the paper PDF
- ingest it as a real PDF

### 9.5 Why Summary-only Still Exists

Summary-only mode still appears in cases where:
- no legal/open PDF is available
- provider content is incomplete
- a landing page exists but no direct PDF exists
- the retrieved full-text URL is invalid or not actually a PDF

This is an unavoidable licensing and availability constraint, not just an implementation choice.

## 10. Provider Services

### 10.1 OpenAlexService

Responsibilities:
- search
- work metadata fetch
- citation graph fetch
- OpenAlex seed resolution for non-OpenAlex papers
- full-text resolution using OpenAlex content API + fallbacks

Important behaviors:
- prefers `has_content.pdf:true` searches when possible
- reconstructs abstract text from OpenAlex inverted-index format
- preserves `arxiv_id` if available

### 10.2 EuropePmcService

Responsibilities:
- biomedical search
- metadata fetch
- PDF resolution
- import queueing

### 10.3 ArxivService

Responsibilities:
- arXiv search
- metadata fetch
- direct PDF import

Important behavior:
- arXiv metadata now includes:
  - `external_id`
  - `source_type = arxiv`

This prevents arXiv suggestions from being mis-imported through OpenAlex routes.

### 10.4 CoreService

Responsibilities:
- search for open-access full-text candidates via CORE
- return PDF-capable hits where available

Requires:
- `CORE_API_KEY`

### 10.5 DoiLocatorService

Responsibilities:
- Crossref metadata / link lookup
- Unpaywall OA lookup

Requires:
- `UNPAYWALL_EMAIL` for Unpaywall

## 11. Resilience and Failure Handling

Primary module:
- `backend/rag/services/resilience.py`

Features:
- bounded retries
- exponential backoff
- in-memory per-provider circuit breakers

Applied to:
- OpenAlex
- Europe PMC
- arXiv
- CORE
- Crossref
- Unpaywall
- older Semantic Scholar paths

Config:
- `EXTERNAL_API_RETRIES`
- `EXTERNAL_API_RETRY_BACKOFF_SECONDS`
- `EXTERNAL_API_CIRCUIT_FAILURE_THRESHOLD`
- `EXTERNAL_API_CIRCUIT_OPEN_SECONDS`

## 12. Highlight Pipeline

Primary modules:
- `views_highlights.py`
- `services/highlight_service.py`

Behavior:
- create highlight
- optionally index highlight into vector search
- search highlights semantically first
- lexical fallback on text, note, and tags

Highlights remain stored even if embedding/indexing fails.

## 13. Metrics and Monitoring

Primary module:
- `services/metrics.py`

Each ask request logs:
- latency
- retrieval time
- generation time
- selected sources
- retrieved chunks
- refusal and evidence flags
- confidence score
- errors

The frontend `monitoring` mode displays aggregate summaries.

## 14. Frontend Behavior

Primary file:
- `frontend/src/App.js`

### 14.1 Main UI Areas

- session sidebar
- source list
- external search panel
- related papers panel
- chat area
- citation / PDF drawer
- highlight UI
- monitoring dashboard

### 14.2 Import Buttons

The frontend import buttons depend on provider metadata in the payload.

This is why preserving the correct provider is critical:
- `arxiv` suggestions must import through arXiv
- OpenAlex-only IDs must import through OpenAlex

### 14.3 Citation Drawer

If the source is PDF-backed:
- open PDF.js viewer

If the source is summary-only:
- show text preview with title/authors/abstract/source URL

## 15. Environment and Operational Configuration

Primary config file:
- `backend/config/settings.py`

Important discovery/import variables:
- `OPENALEX_MAILTO`
- `OPENALEX_API_KEY`
- `CORE_API_KEY`
- `UNPAYWALL_EMAIL`

Operational importance:
- without `OPENALEX_API_KEY`, OpenAlex content API downloads are unavailable
- without `CORE_API_KEY`, CORE full-text enrichment is disabled
- without `UNPAYWALL_EMAIL`, Unpaywall cannot be used for DOI-based OA lookup

## 16. Testing Coverage

Backend tests cover:
- upload/list/delete flows
- ask flows
- citation alignment
- resilience behavior
- discovery provider ordering
- arXiv provider preservation
- OpenAlex seed resolution
- summary-only overview behavior
- remote PDF validation and fallback behavior

Command:

```bash
cd backend
python manage.py test rag -v 2
```

## 17. Limitations and Engineering Debt

### 17.1 Full-text Availability Is Still the Hardest Constraint

Even with improved routing, some papers still resolve only to metadata because:
- the paper is not openly accessible
- no legal direct PDF is discoverable
- the provider only exposes metadata

### 17.2 Discover UX Still Has Room to Improve

Current backend behavior is stronger than the current related-paper panel presentation.

Still missing:
- explicit per-item `PDF-likely` vs `metadata-only likely`
- provider badges in the related panel
- importability-aware ranking in the UI

### 17.3 Worker Deployment

The ingestion job model is durable, but the worker is still a manually run long-lived process rather than a distributed queue system like Celery or RQ.

### 17.4 Historical Chat Payloads

Older persisted answers may contain stale suggestion-provider metadata from before recent fixes. New requests produce the corrected payloads.

## 18. Recommended Next Extensions

If the goal is stronger full-text scientific workflows, the most useful next engineering steps are:
1. add importability scoring to discovery results
2. expose provider and full-text likelihood in the UI
3. add ACL-native full-text routing for NLP papers
4. add repair tooling for older mislabeled imported sources
5. capture import provenance in the UI so users know whether a source is:
   - full PDF
   - verified OA PDF
   - metadata-only fallback

---

This document reflects the repository state after the current discovery/import architecture updates and is intended to match the backend/frontend codepaths now present in the repository.
