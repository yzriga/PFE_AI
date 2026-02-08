# Scientific Research Navigator - Architecture & Audit

**Date**: 2026-02-08  
**Status**: Foundation Phase - Preparing for NotebookLM-like Evolution  
**Author**: System Architecture Review

---

## 🎯 Executive Summary

Current state: **Working single/multi-PDF RAG system** with session management, strict grounding, and citation support.

**What works well:**
- ✅ Session-isolated vector stores (Chroma)
- ✅ RAG pipeline with strict grounding (no hallucinations)
- ✅ Citation extraction (source + page + count)
- ✅ Metadata extraction (title, abstract, page count)
- ✅ Multi-document Q&A
- ✅ React frontend with chat interface

**What's missing (NotebookLM goals):**
- ❌ arXiv / PubMed connectors
- ❌ Multi-doc comparison mode
- ❌ Literature review generator
- ❌ Notes & highlights system
- ❌ Background job processing
- ❌ Run logging & metrics
- ❌ Evaluation framework
- ❌ MLOps dashboard

---

## 📐 Current Architecture

### **Tech Stack**

| Layer | Technologies |
|-------|-------------|
| **Backend** | Django 6.0.1, DRF 3.16.1, Python 3.10+ |
| **Database** | SQLite (dev), ready for PostgreSQL |
| **Vector DB** | ChromaDB 1.4.1 (session-scoped) |
| **LLM** | Mistral via Ollama (local) |
| **Embeddings** | nomic-embed-text (Ollama) |
| **Frontend** | React 19.2.4, react-scripts 5.0.1 |
| **PDF Processing** | PyPDF 6.6.1 |
| **RAG Framework** | LangChain 1.2.7 |

---

## 🗄️ Database Models (Current)

### **Session**
```python
- name: CharField(255, unique=True)
- created_at: DateTimeField(auto_now_add=True)
```
**Relations**: `documents`, `questions`

### **Document**
```python
- filename: CharField(255)
- session: ForeignKey(Session)
- uploaded_at: DateTimeField(auto_now_add=True)
- title: TextField(null=True)          # Extracted from PDF
- abstract: TextField(null=True)       # Extracted from PDF
- page_count: IntegerField(null=True)  # Extracted from PDF
```
**Unique Together**: (`filename`, `session`)

### **Question**
```python
- text: TextField()
- session: ForeignKey(Session, null=True)
- created_at: DateTimeField(auto_now_add=True)
```
**Relations**: `answer` (OneToOne)

### **Answer**
```python
- question: OneToOneField(Question)
- text: TextField()
- citations: JSONField()  # [{source, page, count}]
- created_at: DateTimeField(auto_now_add=True)
```

---

## 🔌 API Endpoints (Current)

### **Sessions**
- `GET /api/sessions/` - List all sessions
- `POST /api/session/` - Create new session
  - Body: `{name: str}`
- `DELETE /api/session/<name>/` - Delete session + cleanup

### **Documents**
- `POST /api/upload/` - Upload PDF
  - Form-data: `file`, `session`
  - **Triggers synchronous ingestion** ⚠️
- `GET /api/pdfs/?session=<name>` - List documents in session
  - Returns: `[{filename, title, abstract}]`
- `DELETE /api/delete/` - Remove document from session
  - Body: `{session, filename}`

### **Query**
- `POST /api/ask/` - RAG query
  - Body: `{question, session, sources?: [str]}`
  - Response: `{answer, citations: [{source, page, count}]}`
  - **Modes**: Intelligent routing (metadata vs content)

---

## 🔄 Data Flow (Current)

### **Ingestion Pipeline** (Synchronous ⚠️)

```
1. Upload PDF → /media/pdfs/
2. Create Document record (UPLOADED state implicit)
3. ingest_pdf() called synchronously:
   a. PyPDFLoader extracts pages
   b. extract_title_and_abstract() from first page
   c. RecursiveCharacterTextSplitter (chunk_size=1000, overlap=200)
   d. OllamaEmbeddings generates vectors
   e. Chroma.add_documents() persists to data/chroma/<session>/
   f. Document.save(title, abstract, page_count)
4. Return 201 Created
```

**Issues:**
- ❌ Blocking request (30s+ for large PDFs)
- ❌ No status tracking (PROCESSING/INDEXED/FAILED)
- ❌ No error recovery
- ❌ No retry mechanism

### **Query Pipeline**

```
1. Receive question
2. Router checks question type:
   - is_title_question() → DB lookup
   - is_page_count_question() → DB lookup
   - is_about_paper_question() → Retrieve abstract + body
   - Default → Full RAG
3. Chroma.similarity_search(k=5, filter={sources})
4. Build strict prompt: "Answer ONLY from context"
5. Ollama/Mistral generates response
6. Extract citations (Counter by source+page)
7. Save Question + Answer to DB
8. Return response
```

**Features:**
- ✅ Strict grounding (refuses if not in context)
- ✅ Source filtering
- ✅ Citation deduplication
- ⚠️ No cross-document analysis

---

## 📁 File Structure

```
backend/
├── config/                   # Django settings
│   ├── settings.py          # SQLite, CORS, apps
│   ├── urls.py              # Root URL config
│   └── wsgi.py
├── rag/                      # Main RAG module
│   ├── models.py            # Session, Document, Question, Answer
│   ├── views.py             # All API endpoints
│   ├── urls.py              # RAG routes
│   ├── ingest.py            # PDF processing & Chroma indexing
│   ├── query.py             # RAG retrieval + LLM
│   ├── router.py            # Question intent detection
│   ├── metadata.py          # Title/abstract extraction
│   └── utils.py             # Helpers (session paths, normalization)
├── data/
│   └── chroma/              # Vector stores (per session)
│       └── <session_name>/
├── media/
│   └── pdfs/                # Uploaded PDF files
├── db.sqlite3               # Relational data
└── manage.py

frontend/
├── src/
│   ├── App.js               # Main React app
│   ├── App.css              # Styling
│   └── index.js
├── public/
└── package.json
```

---

## 🧠 RAG Components

### **Ingestion (`ingest.py`)**

**Function**: `ingest_pdf(path, session_name, document)`

**Steps**:
1. Load PDF pages (PyPDFLoader)
2. Extract metadata from page 0
3. Tag pages: `section: "abstract" | "body"`
4. Split into chunks (RecursiveCharacterTextSplitter)
5. Embed with nomic-embed-text
6. Store in session-scoped Chroma

**Metadata attached to chunks**:
```python
{
  "source": filename,
  "page": int,
  "section": "abstract" | "body"
}
```

### **Retrieval (`query.py`)**

**Function**: `ask_with_citations(question, session_name, sources, k=5)`

**Modes**:
- `sources=None`: Global search across all docs in session
- `sources=[...]`: Filter by specific filenames

**Features**:
- Semantic search via Chroma
- Citation counting with `Counter`
- Refusal if context empty

**Function**: `retrieve_paper_overview(question, session_name, source)`
- Retrieves abstract chunks (section="abstract")
- Retrieves top-k body chunks semantically
- Used for "What is this paper about?" questions

### **Router (`router.py`)**

**Pattern matching**:
- `is_title_question()`: "title", "paper title"
- `is_about_paper_question()`: "what is this paper about", "summarize"
- `is_page_count_question()`: "how many pages"

**Actions**:
- Metadata questions → DB query
- Overview questions → Abstract + body retrieval
- Default → Full RAG

---

## 🎨 Frontend (React)

### **Components**

**App.js** (main component):
- Session management (sidebar)
- Document upload (file input)
- Source selection (checkboxes)
- Chat interface (messages)
- Citation display

**Features**:
- ✅ Session switching (resets chat)
- ✅ Real-time status updates
- ✅ Citation click (shows source + page)
- ✅ Loading states
- ⚠️ No PDF viewer
- ⚠️ No highlighting
- ⚠️ No dashboard

**API Integration**:
- `/api/sessions/` → Sidebar
- `/api/pdfs/?session=` → Source list
- `/api/upload/` → Upload button
- `/api/ask/` → Chat submit

---

## ⚠️ Critical Gaps for NotebookLM Evolution

### **1. Ingestion Issues**
| Problem | Impact | Priority |
|---------|--------|----------|
| Synchronous processing | Request timeouts (30-60s) | 🔴 Critical |
| No status tracking | User doesn't see progress | 🔴 Critical |
| No error handling | Silent failures | 🟡 High |
| No job queue | Can't parallelize | 🟡 High |

### **2. Missing Data Sources**
| Source | Status | Needed For |
|--------|--------|-----------|
| arXiv | ❌ Not implemented | Paper import |
| PubMed | ❌ Not implemented | Medical papers |
| PMC | ❌ Not implemented | Full-text access |

### **3. Missing Functionality**
| Feature | Status | Needed For |
|---------|--------|-----------|
| Multi-doc comparison | ❌ Not implemented | Cross-reference |
| Literature review gen | ❌ Not implemented | Synthesis |
| Notes & highlights | ❌ Not implemented | User memory |
| Run logging | ❌ Not implemented | MLOps |
| Metrics dashboard | ❌ Not implemented | Monitoring |

### **4. Database Gaps**
| Model | Missing Fields | Purpose |
|-------|---------------|---------|
| Document | `source_type` | "upload" / "arxiv" / "pubmed" |
| Document | `external_id` | arXiv ID, PMID, DOI |
| Document | `authors` | Citation formatting |
| Document | `published_date` | Temporal analysis |
| Document | `status` | UPLOADED/PROCESSING/INDEXED/FAILED |
| Document | `error_message` | Debug failed ingestions |
| - | `Note` model | User highlights/annotations |
| - | `RunLog` model | Query tracking |
| - | `Metric` model | Dashboard data |

### **5. Infrastructure**
| Component | Status | Needed |
|-----------|--------|--------|
| PostgreSQL | ⚠️ Configured but not used | Production DB |
| Redis | ❌ Not configured | Job queue + cache |
| Celery | ❌ Not implemented | Background tasks |
| Docker Compose | ✅ Exists but incomplete | Full stack |
| CI/CD | ❌ Not implemented | Testing + deployment |

---

## 📊 Code Quality Assessment

### **✅ Strengths**
1. **Clean separation**: Views, models, services well separated
2. **Type safety**: Consistent use of Django ORM
3. **Error handling**: JSON error responses standardized
4. **Modularity**: `router.py`, `metadata.py`, `utils.py` are reusable
5. **Session isolation**: Chroma collections properly scoped

### **⚠️ Technical Debt**
1. **Synchronous ingestion**: Blocks API requests
2. **No logging**: Print statements only
3. **No tests**: Zero coverage
4. **Hard-coded configs**: Embedding model, chunk size, k, etc.
5. **No validation**: Missing Pydantic schemas
6. **Duplicate logic**: File cleanup in multiple views

### **🐛 Known Issues**
1. Question.session nullable → orphaned questions possible
2. ChromaDB not cleaned on document delete (partial)
3. No checksum verification → duplicate uploads possible
4. No rate limiting
5. CORS allow all → security risk in production

---

## 🚀 Implementation Plan

### **Phase 0: Foundation Hardening** (D1)
**Goal**: Make current system production-ready

**Tasks**:
1. Add `status` and metadata fields to Document model
2. Implement background job queue (Celery + Redis)
3. Create `RunLog` model for query tracking
4. Add logging (structlog)
5. Write unit tests for ingestion + retrieval
6. Refactor: extract `IngestionService` class

**Files to modify**:
- `models.py`: Add fields
- `views.py`: Make upload_pdf async
- Create `services/ingestion.py`
- Create `tasks.py` (Celery)
- `settings.py`: Add Celery config
- Create `tests/test_ingestion.py`

**Endpoints unchanged**: All existing endpoints keep same signature

---

### **Phase 1: External Data Sources** (D2, D3)
**Goal**: Import from arXiv and PubMed

**New endpoints**:
```python
GET  /api/arxiv/search?q=transformer&max_results=10
POST /api/arxiv/import {arxiv_id, session}

GET  /api/pubmed/search?q=cancer&retmax=20
POST /api/pubmed/import {pmid, session}
```

**New models**:
```python
class PaperSource(models.Model):
    document = OneToOneField(Document)
    source_type: "arxiv" | "pubmed" | "upload"
    external_id: str (arxiv_id / pmid)
    doi: str
    authors: JSONField
    published_date: DateField
```

**Files to create**:
- `services/arxiv_service.py`
- `services/pubmed_service.py`
- `views_external.py`

---

### **Phase 2: Advanced RAG Modes** (D4)
**Goal**: Multi-doc comparison + literature review

**Modified endpoint**:
```python
POST /api/ask/
Body: {
  question: str,
  session: str,
  sources?: [str],
  mode: "qa" | "compare" | "lit_review"  # NEW
}

# mode=compare response:
{
  topic: str,
  claims: [{
    claim: str,
    papers: [{
      paper_id: str,
      stance: "supports" | "contradicts" | "neutral",
      evidence: [{page, excerpt, chunk_id}]
    }]
  }]
}

# mode=lit_review response:
{
  title: str,
  outline: [str],
  sections: [{
    heading: str,
    paragraphs: [{
      text: str,
      citations: [{paper, page, excerpt_id}]
    }]
  }]
}
```

**New service**:
- `services/synthesis.py`: Multi-doc analysis
- `prompts/compare.txt`: Compare prompt template
- `prompts/lit_review.txt`: Review generator template

---

### **Phase 3: Notes & Highlights** (D5)
**Goal**: User can annotate and retrieve from notes

**New models**:
```python
class Highlight(models.Model):
    document: FK(Document)
    user: FK(User)  # Add auth later
    page: int
    start_offset: int
    end_offset: int
    text: TextField
    note: TextField
    tags: JSONField
    created_at: DateTimeField

class HighlightEmbedding(models.Model):
    highlight: FK(Highlight)
    embedding_id: str  # Chroma ID
```

**New endpoints**:
```python
POST /api/highlights/ {document_id, page, start, end, text, note, tags}
GET  /api/highlights/?document_id=&tag=
PUT  /api/highlights/<id>/ {note, tags}
DELETE /api/highlights/<id>/
```

**Query modification**:
- Retrieve highlights first (priority retrieval)
- Inject into context with `[USER NOTE]` tag

---

### **Phase 4: MLOps Foundation** (D6)
**Goal**: Monitoring, evaluation, dashboard

**New models**:
```python
class RunLog(models.Model):
    session: FK(Session)
    question: FK(Question)
    mode: str
    sources: JSONField
    latency_ms: int
    retrieved_chunks: JSONField  # [{doc, page, chunk_id, score}]
    prompt_tokens: int
    completion_tokens: int
    error_type: str
    created_at: DateTimeField
```

**Evaluation script**:
```bash
python manage.py run_eval --topic "transformers" --n_papers 15 --n_questions 40
```
- Fetches papers from arXiv
- Generates evaluation questions
- Runs queries and logs metrics

**Dashboard endpoint**:
```python
GET /api/metrics/summary?since=7d
Response: {
  ingestion: {success_rate, avg_time, errors},
  queries: {count, latency_p50, latency_p95},
  citations: {coverage_rate},
  top_errors: [{type, count}]
}
```

---

### **Phase 5: Frontend Evolution** (D7)
**Goal**: UI for all new features

**New components**:
- `ArxivImport.js`: Search + import panel
- `PubMedImport.js`: Search + import panel
- `ModeSelector.js`: Switch between Ask/Compare/LitReview
- `CitationViewer.js`: Modal showing full excerpt
- `HighlightPanel.js`: Sidebar for notes
- `Dashboard.js`: Metrics visualization

**Enhanced App.js**:
- Mode state management
- Structured output rendering (tables for Compare, sections for LitReview)
- Highlight UI (PDF.js or custom viewer)

---

## 🎯 Deliverables Mapping

| Phase | Deliverable | Complexity | Days | Status |
|-------|------------|------------|------|--------|
| 0 | D0: Architecture doc | Low | 0.5 | ✅ DONE |
| 0 | D1: Unified ingestion | Medium | 2 | 🔵 NEXT |
| 1 | D2: arXiv connector | Medium | 2 | ⚪ TODO |
| 1 | D3: PubMed connector | Medium | 2 | ⚪ TODO |
| 2 | D4: Multi-doc modes | High | 4 | ⚪ TODO |
| 3 | D5: Notes/highlights | Medium | 3 | ⚪ TODO |
| 4 | D6: Eval + MLOps | Medium | 3 | ⚪ TODO |
| 5 | D7: Frontend | High | 4 | ⚪ TODO |

**Total estimate**: ~20 days of focused development

---

## 🔧 Next Steps

### **Immediate (D1 - Unified Ingestion)**

**Branch**: `feature/unified-ingestion`

**Changes**:
1. Add Document fields: `status`, `error_message`, `processing_started_at`, `processing_completed_at`
2. Create `IngestionService` class
3. Setup Celery + Redis
4. Create `tasks.py` with `@shared_task def ingest_document_task(doc_id)`
5. Modify `upload_pdf()` to trigger async task
6. Add `GET /api/documents/<id>/status` endpoint
7. Frontend polling for status updates
8. Write tests

**Success criteria**:
- ✅ Upload returns immediately with 202 Accepted
- ✅ Status transitions: UPLOADED → PROCESSING → INDEXED
- ✅ Error cases logged to `error_message`
- ✅ Frontend shows progress
- ✅ Tests pass

---

## 📝 Configuration Recommendations

### **Environment Variables** (create `.env`)
```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost:5432/navigator

# Redis
REDIS_URL=redis://localhost:6379/0

# Ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_LLM_MODEL=mistral
OLLAMA_EMBED_MODEL=nomic-embed-text

# RAG Config
RAG_CHUNK_SIZE=1000
RAG_CHUNK_OVERLAP=200
RAG_TOP_K=5

# External APIs
ARXIV_BASE_URL=http://export.arxiv.org/api/query
PUBMED_EMAIL=your@email.com  # Required by NCBI

# Monitoring
SENTRY_DSN=  # Optional
```

### **Docker Compose** (update)
```yaml
services:
  db:
    image: postgres:15
  redis:
    image: redis:7-alpine
  backend:
    build: ./backend
    depends_on: [db, redis]
  celery:
    build: ./backend
    command: celery -A config worker -l info
  frontend:
    build: ./frontend
  ollama:
    image: ollama/ollama
```

---

## 📚 References

**Current codebase**:
- Models: `/backend/rag/models.py`
- Views: `/backend/rag/views.py`
- Ingestion: `/backend/rag/ingest.py`
- Query: `/backend/rag/query.py`

**External APIs**:
- arXiv: https://arxiv.org/help/api
- PubMed: https://www.ncbi.nlm.nih.gov/books/NBK25501/
- PMC: https://www.ncbi.nlm.nih.gov/pmc/tools/oa-service/

**NotebookLM inspiration**:
- https://notebooklm.google/

---

**END OF ARCHITECTURE AUDIT**
