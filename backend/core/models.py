from django.db import models

class Document(models.Model):
    title = models.CharField(max_length=255)
    filename = models.CharField(max_length=255)
    uploaded_at = models.DateTimeField(auto_now_add=True)

class Query(models.Model):
    question = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)