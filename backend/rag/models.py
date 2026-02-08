from django.db import models


class Session(models.Model):
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Document(models.Model):
    STATUS_CHOICES = [
        ('UPLOADED', 'Uploaded'),
        ('PROCESSING', 'Processing'),
        ('INDEXED', 'Indexed'),
        ('FAILED', 'Failed'),
    ]
    
    filename = models.CharField(max_length=255)
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
        ('manual', 'Manual Upload'),
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


class Question(models.Model):
    text = models.TextField()
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="questions",
        null=True,          # 👈 TEMPORARY
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
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Answer to: {self.question.text[:30]}"


class Highlight(models.Model):
    """
    User annotations/highlights on document pages.
    
    Supports:
    - Text selection with page + character offsets
    - User notes and tags
    - Semantic retrieval via HighlightEmbedding
    """
    document = models.ForeignKey(
        Document,
        on_delete=models.CASCADE,
        related_name='highlights',
        help_text="Document being annotated"
    )
    
    # TODO: Add user FK when auth is implemented
    # user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='highlights')
    
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
    
    Links a Highlight to its embedding stored in ChromaDB.
    Allows retrieval of user notes during RAG queries.
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
    Enables monitoring, debugging, and evaluation of system performance.
    
    Tracks:
    - Query parameters (question, mode, sources)
    - Performance metrics (latency, tokens)
    - Retrieved context (chunks with scores)
    - Errors if any
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
        help_text="Error class name if query failed (e.g., 'ChromaConnectionError')"
    )
    error_message = models.TextField(
        null=True,
        blank=True,
        help_text="Full error message/traceback"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['session', 'created_at']),
            models.Index(fields=['mode']),
            models.Index(fields=['error_type']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        status = f"ERROR: {self.error_type}" if self.error_type else f"{self.latency_ms}ms"
        return f"[{self.mode.upper()}] {self.question_text[:40]}... ({status})"
