from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0011_document_storage_path"),
    ]

    operations = [
        migrations.CreateModel(
            name="IngestionJob",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("job_type", models.CharField(choices=[("DOCUMENT_INGEST", "Document Ingest"), ("ARXIV_IMPORT", "arXiv Import"), ("PUBMED_IMPORT", "PubMed Import"), ("SEMANTIC_SCHOLAR_IMPORT", "Semantic Scholar Import")], max_length=40)),
                ("status", models.CharField(choices=[("QUEUED", "Queued"), ("RUNNING", "Running"), ("SUCCEEDED", "Succeeded"), ("FAILED", "Failed")], default="QUEUED", max_length=20)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("max_attempts", models.PositiveIntegerField(default=3)),
                ("available_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("last_error", models.TextField(blank=True, default="")),
                ("worker_id", models.CharField(blank=True, default="", max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("document", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="ingestion_jobs", to="rag.document")),
                ("paper_source", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="ingestion_jobs", to="rag.papersource")),
                ("session", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="ingestion_jobs", to="rag.session")),
            ],
            options={"ordering": ["created_at"]},
        ),
        migrations.AddIndex(
            model_name="ingestionjob",
            index=models.Index(fields=["status", "available_at"], name="rag_ingestj_status_84db5d_idx"),
        ),
        migrations.AddIndex(
            model_name="ingestionjob",
            index=models.Index(fields=["job_type", "status"], name="rag_ingestj_job_typ_8fe3ff_idx"),
        ),
        migrations.AddIndex(
            model_name="ingestionjob",
            index=models.Index(fields=["document", "status"], name="rag_ingestj_documen_26bf6f_idx"),
        ),
    ]
