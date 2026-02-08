# Scientific Research Navigator

A **session-based Retrieval-Augmented Generation (RAG)** system for exploring and querying scientific PDFs with strict grounding and citation support.

This project allows users to:
- Upload scientific papers (PDF)
- Organize them into **sessions**
- Ask questions grounded **only** in selected documents
- Prevent hallucinations via strict retrieval constraints
- View exact source citations (PDF + page)

---

##  Features Implemented

###  Session-based document management
- Each session has its own:
  - PDF list
  - Vector store (Chroma)
- No cross-session contamination

###  Asynchronous document processing ✨ NEW
- **Non-blocking uploads**: Upload returns `202 Accepted` immediately
- **Background ingestion**: PDF processing happens asynchronously in separate threads
- **Status tracking**: Real-time monitoring with status transitions:
  - `UPLOADED`: File received, queued for processing
  - `PROCESSING`: PDF being extracted, chunked, and indexed
  - `INDEXED`: Ready for querying
  - `FAILED`: Error occurred (with detailed error message)
- **Processing metrics**: Track processing start/end times and duration
- **Robust error handling**: Failed ingestions can be retried via `reingest_document()`

###  Robust PDF ingestion
- PDFs are split into semantic chunks
- Each chunk is enriched with:
  - `source` (filename)
  - `page` number
- Stored in a **session-scoped Chroma vector store**
- Comprehensive logging at each processing step

###  Strict RAG pipeline
- Semantic retrieval via `nomic-embed-text`
- LLM: `mistral` (via Ollama)
- **Hard grounding**:
  - If the answer is not in retrieved context → model refuses to answer
- Citations returned for every answer

###  Hallucination control
- No guessing
- No title or metadata hallucination
- Source filtering enforced

###  REST API (Django + DRF)
- Upload PDFs
- List session PDFs
- Ask session-scoped questions

---

##  Architecture Overview
```
Frontend
↓
Django REST API
↓
Session Resolver
↓
Chroma (per session)
↓
Retriever → Context
↓
LLM (Ollama)

```

---

##  Tech Stack

- **Backend**: Django, Django REST Framework
- **RAG**: LangChain, Chroma
- **Embeddings**: nomic-embed-text
- **LLM**: Mistral (via Ollama)
- **Frontend**: Simple web UI
- **Storage**:
  - PDFs: filesystem
  - Vectors: Chroma (per session)

---

##  Setup Instructions

###  Prerequisites

- Python 3.10+
- Ollama installed and running

Pull required models:
```bash
ollama pull mistral
ollama pull nomic-embed-text
```


### Clone the repository
```
git clone https://github.com/<username>/scientific-navigator.git
cd scientific-navigator
```

###  Create virtual environment
```
python -m venv venv
source venv/bin/activate
```

###  Install dependencies
```
pip install -r requirements.txt
```

###  Run database migrations
```
cd backend
python manage.py migrate
```

###  Start the backend
```
python manage.py runserver
```

Backend available at: http://127.0.0.1:8000

## API Usage

### Upload PDFs (Asynchronous)
```
POST /api/upload/
```

Form-data:
- `file`: PDF file
- `session`: Session name

**Response**: `202 Accepted`
```json
{
  "message": "PDF upload initiated. Processing in background.",
  "document_id": 1,
  "filename": "paper.pdf",
  "session": "SessionA",
  "status": "UPLOADED"
}
```

The document is processed asynchronously in the background. Status transitions: 
`UPLOADED` → `PROCESSING` → `INDEXED` (or `FAILED` on error)

### Check Document Processing Status
```
GET /api/documents/<document_id>/status/
```

**Response**:
```json
{
  "document_id": 1,
  "filename": "paper.pdf",
  "session": "SessionA",
  "status": "INDEXED",
  "uploaded_at": "2026-02-08T20:13:57Z",
  "processing_started_at": "2026-02-08T20:13:57Z",
  "processing_completed_at": "2026-02-08T20:13:58Z",
  "processing_time_seconds": 1.55,
  "error_message": null,
  "metadata": {
    "title": "...",
    "abstract": "...",
    "page_count": 14
  }
}
```

### List PDFs in a session
```
GET /api/pdfs/?session=SessionA
```

Returns all documents with their current status (`UPLOADED`, `PROCESSING`, `INDEXED`, `FAILED`)

### Ask a question
```
POST /api/ask/
```
```json
{
  "question": "What is this paper about?",
  "session": "SessionA",
  "sources": ["paper1.pdf"]
}
```

**Note**: Only documents with `status: INDEXED` can be queried.

⚠️ Known Design Choice

- Metadata-level questions (e.g. title, authors) are not guaranteed
unless explicitly present in retrieved text.

- This is intentional to avoid hallucinations.