# Scientific Research Navigator

Scientific Research Navigator is a session-scoped research workspace for scientific papers.

## Quick Start For Demo / Delivery

This repository is now set up so the application can be launched with a single command using Docker Compose.

### Recommended launch path

Windows PowerShell:

```powershell
.\start-demo.ps1
```

Linux / WSL / macOS:

```bash
./start-demo.sh
```

What this does:
- starts Postgres, Ollama, backend, worker, and frontend
- automatically pulls the required Ollama models on first run:
  - `mistral`
  - `nomic-embed-text`
- waits for the backend to become reachable

Application URLs:
- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`

To stop the stack:

Windows PowerShell:

```powershell
.\stop-demo.ps1
```

Linux / WSL / macOS:

```bash
./stop-demo.sh
```

### Prerequisites

Only these are required for the default delivery path:
- Docker Desktop (or Docker Engine + Compose)
- Internet access on first run to pull container images and Ollama models

### First-run note

The first launch can take several minutes because it may need to:
- build the backend and frontend images
- initialize Postgres
- pull Ollama models

Subsequent launches are much faster because Docker volumes persist:
- database data
- uploaded media
- Chroma indexes
- Ollama models

### Presentation-safe startup checklist

Before the final demo, run this once and verify:
- `docker compose ps`
- frontend loads on `http://localhost:3000`
- backend responds on `http://localhost:8000/api/sessions/`
- Ollama models are present:

```bash
docker compose exec ollama ollama list
```

It combines:
- A Django + DRF backend for ingestion, retrieval, synthesis, discovery, and persistence
- Session-scoped Chroma vector indexes for paper and highlight search
- Ollama-hosted local embedding and generation models
- A React frontend for document management, grounded QA, comparison, literature review, discovery, and annotation

The application is designed around a practical research workflow:
1. Create a session
2. Upload or import papers
3. Ask grounded questions over selected sources
4. Discover related papers and import them
5. Compare papers or generate literature reviews
6. Save highlights and inspect citations in context

## Current Product Capabilities

### Session Workspace
- Create, list, switch, and delete sessions
- Session isolation for:
  - source list
  - vector index
  - chat history
  - highlights
  - run logs / metrics

### Source Management
- Upload local PDFs
- Import papers from external providers
- Poll ingestion status
- Retry failed ingestion/import jobs
- Delete sources and clean up vector data
- Filter and search sources in the sidebar

### QA and Synthesis Modes
- `qa`
  - grounded question answering over selected papers
  - citations at chunk level
  - no-context scholarly discovery mode when no local source is selected
- `compare`
  - balanced cross-paper retrieval
  - structured claim/stance output across selected papers
- `lit_review`
  - multi-paper structured review generation
- `monitoring`
  - aggregated system metrics from run logs

### Discovery and Import
- No-source question routing:
  - if a question is topic-oriented and scholarly, the system performs external discovery and answers from discovered paper metadata
  - if a question is too broad and generic, the system abstains
- Related-paper discovery:
  - OpenAlex citation graph when the source can be resolved to an OpenAlex work
  - multi-provider fallback discovery when graph seeding is unavailable
- Import strategy:
  - OpenAlex for discovery and graph traversal
  - Europe PMC preferred for biomedical discovery
  - arXiv preferred for AI / LLM / RAG / transformer-style topics
  - CORE, OpenAlex content API, DOI-based OA resolution, and provider-native PDFs used to obtain full text where possible
  - metadata-only ingestion used only when a real PDF cannot be verified and downloaded

### Citation and Evidence UX
- Retrieved citations include:
  - `source`
  - `page`
  - `chunk_id`
  - `snippet`
  - `score`
- PDF.js viewer opens to the cited page with a best-effort search phrase
- Metadata-only sources open in a text preview drawer instead of a PDF viewer
- Citation snippets can be turned into highlights

### Highlights
- Create highlights from citation snippets
- Add free-text notes and tags
- Search highlights semantically with lexical fallback
- View highlights per document or across the session

### Observability
- Query run logging
- Latency metrics
- Error tracking
- Grounding and refusal indicators
- Mode-level monitoring in the frontend dashboard

## How the Application Behaves

### 1. Asking Questions With Selected Sources

When one or more indexed sources are selected in `qa` mode:
- the backend retrieves relevant chunks from the session's Chroma index
- optional lexical retrieval and fusion can be used
- the LLM answers only from retrieved evidence
- chunk-level citations are returned

Specialized QA shortcuts exist for selected single-source questions such as:
- title lookup
- page count lookup
- "what is this paper about?" style overview questions

If the source is summary-only:
- the paper-overview path uses metadata directly
- the answer is still useful, but explicitly limited to metadata/abstract content

### 2. Asking Questions With No Selected Sources

When no source is selected in `qa` mode:
- the backend classifies the question
- if it looks like a topic-oriented scholarly query, it triggers external discovery
- if it is too broad or generic, it abstains

Examples that should trigger discovery:
- `Explain transformer architecture`
- `What do recent papers say about retrieval-augmented generation for clinical decision support?`
- `How are diffusion transformers used in vision?`

Examples that should abstain:
- `What is intelligence?`
- `Tell me about life`

Discovery answers:
- are based on provider metadata and abstracts unless full papers are later imported
- include suggested papers with provider-aware import buttons
- may use arXiv first for AI topics and Europe PMC first for biomedical topics

### 3. Importing External Papers

Import behavior is intentionally conservative:
- only verified direct PDFs are treated as PDFs
- landing pages are not treated as PDFs
- downloaded responses are checked to ensure they actually contain PDF content
- if full text cannot be verified, the paper is ingested in summary-only mode

This avoids fake `.pdf` entries that actually contain HTML or landing-page content.

### 4. Discovering Related Papers

The `Discover` action on a paper does the following:
- if the paper maps cleanly to OpenAlex, the app fetches:
  - references
  - citations
  - related works
- if the paper cannot be seeded into OpenAlex, the app falls back to multi-provider discovery based on title and metadata

For related items:
- the backend tries to preserve the most useful import provider
- if a related item has an arXiv ID, the import route prefers `arxiv`
- otherwise OpenAlex or provider-native import paths are used

### 5. Summary-only Sources

Summary-only sources are a fallback, not the preferred path.

They are created when:
- no verified PDF is available
- the provider only exposes metadata/abstract content
- DOI / OA resolution fails
- PDF download succeeds in URL form but is not actually a PDF

Summary-only sources still support:
- retrieval
- metadata-based "what is this paper about?" answers
- citation drawer text preview
- highlighting from retrieved snippets

They do not support:
- true full-page PDF navigation
- robust deep questions that require methods/results/discussion sections

## Retrieval and Generation Stack

### Local Retrieval
- Chroma vector similarity retrieval
- Optional BM25 lexical retrieval
- Reciprocal Rank Fusion for hybrid merge
- Optional reranking by overlap heuristics
- Session-level and source-level filtering

### Generation
- Ollama local LLM for:
  - grounded QA
  - paper comparison
  - literature review synthesis
  - discovery-answer synthesis from metadata

### Confidence / Grounding Signals
- refusal detection
- insufficient-evidence detection
- retrieved chunk counts
- simple confidence scoring
- retrieval and generation timing

## External Provider Strategy

### Discovery Providers
- `OpenAlex`
  - primary discovery provider
  - citation graph source
  - related paper traversal
- `Europe PMC`
  - biomedical-first discovery provider
- `arXiv`
  - preferred for AI / LLM / RAG / transformer topics

### Full-text Resolution Strategy
For candidate papers, the importer attempts full text in roughly this order:
- OpenAlex content API when available
- arXiv PDF if an arXiv ID is known
- CORE full-text lookup
- DOI-based OA lookup via Crossref / Unpaywall
- provider-native PDF URLs

If none of those yield a verified PDF:
- the source is ingested as summary-only metadata

## Repository Layout

```text
.
+-- backend/
|   +-- config/                      # Django settings and URL root
|   +-- rag/                         # Models, views, services, tests
|   +-- requirements.txt
|   +-- Dockerfile
+-- frontend/
|   +-- src/App.js                   # Main application UI
|   +-- src/api.js                   # Frontend API client
|   +-- src/App.css                  # UI styling
|   +-- Dockerfile
+-- docker-compose.yml
+-- docker-compose.gpu.yml
+-- README.md
+-- TECHNICAL_DOCUMENTATION.md
```

## Backend API

Base prefix: `/api/`

Core routes:
- `POST /ask/`
- `POST /upload/`
- `GET /pdfs/`
- `DELETE /delete/`
- `GET /history/`
- `POST /session/`
- `GET /sessions/`
- `DELETE /session/<session_name>/`
- `GET /metrics/summary/`

Document routes:
- `GET /documents/<id>/status/`
- `GET /documents/<id>/page-text/?page=<1-indexed>`
- `POST /documents/<id>/retry/`

Highlight routes:
- `GET|POST /highlights/`
- `DELETE /highlights/<highlight_id>/`
- `GET /highlights/search/`

Discovery / import routes:
- `GET /search/external/`
- `POST /import/external/`
- `GET /papers/related/`

Legacy routes still present:
- `GET /arxiv/search/`
- `POST /arxiv/import/`

## Data Model

Main tables:
- `Session`
- `Document`
- `PaperSource`
- `IngestionJob`
- `Question`
- `Answer`
- `RunLog`
- `Highlight`
- `HighlightEmbedding`

## Manual Local Setup

### 1. Start Ollama and Pull Models

```bash
ollama pull mistral
ollama pull nomic-embed-text
```

### 2. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: .\\venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env      # Windows: copy .env.example .env
python manage.py migrate
python manage.py runserver
```

Backend runs on `http://127.0.0.1:8000`

### 2b. Ingestion Worker

Run the worker in a second shell:

```bash
cd backend
source venv/bin/activate
python manage.py process_ingestion_jobs
```

This worker processes:
- local PDF ingestion jobs
- external import jobs
- retry jobs

### 3. Frontend

```bash
cd frontend
npm install
npm start
```

Frontend runs on `http://localhost:3000`

Optional frontend API override:
- `REACT_APP_API_BASE_URL=http://127.0.0.1:8000`

## Docker Setup

```bash
docker compose up --build
```

Services:
- `postgres`
- `ollama`
- `ollama-init`
- `backend`
- `backend-worker`
- `frontend`

Optional GPU pass-through:
- `docker-compose.gpu.yml`

## Environment Variables

Important backend settings from `backend/.env.example`:

### Core
- `SECRET_KEY`
- `DEBUG`
- `ALLOWED_HOSTS`
- `CORS_ALLOW_ALL`

### Database
- `DB_ENGINE`
- `DB_NAME`
- `DB_USER`
- `DB_PASSWORD`
- `DB_HOST`
- `DB_PORT`

### Local Model / Retrieval
- `OLLAMA_BASE_URL`
- `CHROMA_PERSIST_DIR`
- `RAG_QA_USE_HYBRID`
- `RAG_QA_USE_MULTI_QUERY`
- `RAG_QA_USE_RERANKING`
- `RAG_QA_TOP_K`
- `RAG_LLM_MODEL`
- `RAG_LLM_NUM_PREDICT`
- `RAG_LLM_TEMPERATURE`
- `RAG_LLM_NUM_CTX`
- `RAG_LLM_KEEP_ALIVE`

### External Provider Resilience
- `EXTERNAL_API_RETRIES`
- `EXTERNAL_API_RETRY_BACKOFF_SECONDS`
- `EXTERNAL_API_CIRCUIT_FAILURE_THRESHOLD`
- `EXTERNAL_API_CIRCUIT_OPEN_SECONDS`

### External Provider Credentials / Contact
- `OPENALEX_MAILTO`
- `OPENALEX_API_KEY`
- `CORE_API_KEY`
- `UNPAYWALL_EMAIL`

These materially affect import quality:
- without `OPENALEX_API_KEY`, OpenAlex content API downloads are unavailable
- without `CORE_API_KEY`, CORE full-text lookup is disabled
- without `UNPAYWALL_EMAIL`, Unpaywall DOI OA resolution is disabled

## Testing

Run the backend tests:

```bash
cd backend
python manage.py test rag -v 2
```

Notable suites:
- `rag.test_api_flows`
- `rag.test_citations_and_alignment`
- `rag.test_resilience`
- `rag.tests`

## Operational Notes and Caveats

- The ingestion/import worker is durable and DB-backed, but it is still a separate long-running process that must be started.
- External provider coverage varies by field and licensing constraints.
- Full-text import is best-effort and legally conservative.
- Summary-only mode is still unavoidable for some papers.
- Citation pages are stored zero-indexed in retrieval metadata and displayed one-indexed in the UI.
- Existing historical chat suggestions may contain stale provider metadata from older runs until regenerated.

## Best Current Use Cases

This system works best for:
- scientific PDF QA with explicit evidence
- paper-to-paper comparison
- literature review drafting
- LLM / RAG / NLP / transformer-topic exploration with arXiv-first discovery
- biomedical discovery with Europe PMC-first routing
- annotation and citation-driven reading workflows

## License

No explicit license file is currently present in the repository.
