from django.db import models


class Session(models.Model):
    name = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Document(models.Model):
    filename = models.CharField(max_length=255)
    session = models.ForeignKey(
        Session,
        on_delete=models.CASCADE,
        related_name="documents",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    title = models.TextField(null=True, blank=True)
    abstract = models.TextField(null=True, blank=True)

    class Meta:
        unique_together = ("filename", "session")

    def __str__(self):
        return f"{self.filename} ({self.session.name})"


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
