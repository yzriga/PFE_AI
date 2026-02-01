from pathlib import Path
from rag.ingest import ingest_pdf

if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent.parent
    pdf_path = BASE_DIR / "data" / "pdfs" / "2017-SECRYPT-DR-Tcloseness.pdf"

    ingest_pdf(str(pdf_path))
    print("PDF successfully ingested")
