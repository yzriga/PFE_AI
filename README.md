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

###  Robust PDF ingestion
- PDFs are split into semantic chunks
- Each chunk is enriched with:
  - `source` (filename)
  - `page` number
- Stored in a **session-scoped Chroma vector store**

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
### Upload PDFs
```
POST /api/upload/
```

Form-data:
- file: PDF
- session: Session name

### List PDFs in a session
```
GET /api/pdfs/?session=SessionA
```

### Ask a question
```
POST /api/ask/
```
```
{
  "question": "What is this paper about?",
  "session": "SessionA",
  "sources": ["paper1.pdf"]
}
```

⚠️ Known Design Choice

- Metadata-level questions (e.g. title, authors) are not guaranteed
unless explicitly present in retrieved text.

- This is intentional to avoid hallucinations.