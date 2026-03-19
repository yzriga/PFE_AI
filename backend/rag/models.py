from django.conf import settings
from django.db import models


class Session(models.Model):
    name = models.CharField(max_length=255, unique=True)
    pinned = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Document(models.Model):
    STATUS_CHOICES = [
        ('QUEUED', 'Queued'),
        ('UPLOADED', 'Uploaded'),
        ('PROCESSING', 'Processing'),
        ('INDEXED', 'Indexed'),
        ('FAILED', 'Failed'),
    ]

    filename = models.CharField(max_length=255)
    storage_path = models.CharField(max_length=500, null=True, blank=True)
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    # Metadata extracted from PDF
    title = models.TextField(null=True, blank=True)
    abstract = models.TextField(null=True, blank=True)
    page_count = models.IntegerField(null=True, blank=True)

    # Processing status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='UPLOADED')
    processing_started_at = models.DateTimeField(null=True, blank=True)
    processing_completed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ("filename", "session")

    @property
    def resolved_storage_path(self):
        return self.storage_path or f"pdfs/{self.filename}"

    @property
    def file_url(self):
        return f"{settings.MEDIA_URL}{self.resolved_storage_path}"

    def __str__(self):
        return f"{self.filename} ({self.session.name}) - {self.status}"


class PaperSource(models.Model):
    """
    External paper metadata from sources like arXiv, PubMed, DOI, etc.
    Links to a Document after successful import.
    """
    SOURCE_TYPES = [
        ('arxiv', 'arXiv'),
        ('pubmed', 'PubMed'),
        ('doi', 'DOI'),
        ('openalex', 'OpenAlex'),
        ('europepmc', 'Europe PMC'),
        ('core', 'CORE'),
        ('manual', 'Manual Upload'),
        ('acl', 'ACL Anthology'),
        ('medrxiv', 'medRxiv'),
    ]


    document = models.OneToOneField(
        Document,
        on_delete=models.CASCADE,
        related_name='paper_source',
        null=True,
        blank=True,
        help_text="Linked document after successful import"
    )

    # Source metadata
    source_type = models.CharField(max_length=20, choices=SOURCE_TYPES)
    external_id = models.CharField(
        max_length=255,
        help_text="arXiv ID (e.g., 2411.04920v4), PubMed ID, DOI, etc."
    )

    # Paper metadata
    title = models.TextField()
    authors = models.TextField(help_text="Comma-separated author names")
    abstract = models.TextField(blank=True)
    published_date = models.DateField(null=True, blank=True)

    # URLs
    pdf_url = models.URLField(max_length=500, blank=True)
    entry_url = models.URLField(
        max_length=500,
        blank=True,
        help_text="Link to paper page (arXiv abstract, PubMed entry, etc.)"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    imported = models.BooleanField(
        default=False,
        help_text="Whether the PDF was successfully imported as a Document"
    )

    class Meta:
        unique_together = ('source_type', 'external_id')
        indexes = [
            models.Index(fields=['source_type', 'external_id']),
            models.Index(fields=['imported']),
        ]

    def __str__(self):
        status = "✓ Imported" if self.imported else "⊗ Not imported"
        return f"[{self.source_type.upper()}] {self.title[:50]}... {status}"


class IngestionJob(models.Model):
    STATUS_CHOICES = [
        ("QUEUED", "Queued"),
        ("RUNNING", "Running"),
        ("SUCCEEDED", "Succeeded"),
        ("FAILED", "Failed"),
    ]

    JOB_TYPE_CHOICES = [
        ("DOCUMENT_INGEST", "Document Ingest"),
        ("ARXIV_IMPORT", "arXiv Import"),
        ("PUBMED_IMPORT", "PubMed Import"),
        ("SEMANTIC_SCHOLAR_IMPORT", "Semantic Scholar Import"),
        ("REMOTE_PDF_IMPORT", "Remote PDF Import"),
    ]

    job_type = models.CharField(max_length=40, choices=JOB_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="QUEUED")
    payload = models.JSONField(default=dict, blank=True)
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name="ingestion_jobs",
        null=True,
        blank=True,
    )
    paper_source = models.ForeignKey(
        PaperSource,
        on_delete=models.CASCADE,
        related_name="ingestion_jobs",
        null=True,
        blank=True,
    )
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="ingestion_jobs",
        null=True,
        blank=True,
    )
    attempts = models.PositiveIntegerField(default=0)
    max_attempts = models.PositiveIntegerField(default=3)
    available_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    worker_id = models.CharField(max_length=255, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "available_at"]),
            models.Index(fields=["job_type", "status"]),
            models.Index(fields=["document", "status"]),
        ]

    def __str__(self):
        target = self.document_id or self.paper_source_id or "n/a"
        return f"{self.job_type}#{self.id} [{self.status}] target={target}"


class Question(models.Model):
    text = models.TextField()
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="questions",
        null=True,          #  TEMPORARY
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.text[:50]


class Answer(models.Model):
    question = models.OneToOneField(
        Question,
        on_delete=models.CASCADE,
        related_name="answer"
    )
    text = models.TextField()
    citations = models.JSONField()
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


    def __str__(self):
        return f"Answer to: {self.question.text[:30]}"


class Highlight(models.Model):
    """
    User annotations/highlights on document pages.
    """
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='highlights',
        help_text="Document being annotated"
    )

    # Location information
    page = models.IntegerField(help_text="Page number (1-indexed)")
    start_offset = models.IntegerField(
        help_text="Start character offset in page text"
    )
    end_offset = models.IntegerField(
        help_text="End character offset in page text"
    )

    # Content
    text = models.TextField(help_text="Highlighted text from document")
    note = models.TextField(
        blank=True,
        help_text="User's personal note on this highlight"
    )
    tags = models.JSONField(
        default=list,
        help_text="List of string tags for categorization"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['document', 'page', 'start_offset']
        indexes = [
            models.Index(fields=['document', 'page']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        preview = self.text[:50] + "..." if len(self.text) > 50 else self.text
        return f"Highlight on {self.document.filename} p.{self.page}: {preview}"


class HighlightEmbedding(models.Model):
    """
    Vector embeddings for highlights to enable semantic search.
    """
    highlight = models.OneToOneField(
        Highlight,
        on_delete=models.CASCADE,
        related_name='embedding',
        help_text="Highlight that was embedded"
    )

    embedding_id = models.CharField(
        max_length=255,
        unique=True,
        help_text="ChromaDB document ID for this highlight's embedding"
    )

    embedded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['embedding_id']),
        ]

    def __str__(self):
        return f"Embedding for highlight {self.highlight.id} ({self.embedding_id})"


class RunLog(models.Model):
    """
    Logs for every RAG query execution.
    """
    MODE_CHOICES = [
        ('qa', 'Question Answering'),
        ('compare', 'Compare Papers'),
        ('lit_review', 'Literature Review'),
    ]

    # Query context
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name='run_logs',
        help_text="Session in which query was executed"
    )
    question = models.ForeignKey(
        Question,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='run_logs',
        help_text="Question model if created (nullable for eval runs)"
    )
    question_text = models.TextField(
        help_text="Question text (denormalized for query even if Question deleted)"
    )
    mode = models.CharField(
        max_length=20,
        choices=MODE_CHOICES,
        default='qa',
        help_text="RAG mode used for this query"
    )
    sources = models.JSONField(
        default=list,
        help_text="List of document filenames used as filters (empty = all docs)"
    )

    # Performance metrics
    latency_ms = models.IntegerField(
        help_text="End-to-end query latency in milliseconds"
    )
    retrieval_ms = models.IntegerField(
        null=True,
        blank=True,
        help_text="Retrieval stage latency in milliseconds (if tracked)"
    )
    generation_ms = models.IntegerField(
        null=True,
        blank=True,
        help_text="Generation/synthesis stage latency in milliseconds (if tracked)"
    )
    retrieved_chunks = models.JSONField(
        help_text="List of retrieved chunks with metadata: [{doc, page, chunk_id, score, text_preview}]"
    )
    prompt_tokens = models.IntegerField(
        null=True,
        blank=True,
        help_text="Number of tokens in prompt (if tracked)"
    )
    completion_tokens = models.IntegerField(
        null=True,
        blank=True,
        help_text="Number of tokens in completion (if tracked)"
    )

    # Error tracking
    error_type = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="Error class name if query failed"
    )
    error_message = models.TextField(
        null=True,
        blank=True,
        help_text="Full error message/traceback"
    )

    # Grounding / refusal tracking
    is_refusal = models.BooleanField(
        default=False,
        help_text="Whether the LLM response was a refusal (no relevant info found)"
    )
    is_insufficient_evidence = models.BooleanField(
        default=False,
        help_text="Whether the LLM flagged insufficient evidence"
    )
    retrieved_chunks_count = models.IntegerField(
        default=0,
        help_text="Number of chunks retrieved for this query"
    )
    confidence_score = models.FloatField(
        null=True,
        blank=True,
        help_text="Average retrieval confidence score (0-1)"
    )

    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session', 'created_at']),
            models.Index(fields=['mode']),
            models.Index(fields=['is_refusal']),
        ]
