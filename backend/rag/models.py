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
