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
