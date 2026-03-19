from django.db import migrations, models


def backfill_storage_path(apps, schema_editor):
    Document = apps.get_model("rag", "Document")
    for document in Document.objects.filter(storage_path__isnull=True).exclude(filename=""):
        document.storage_path = f"pdfs/{document.filename}"
        document.save(update_fields=["storage_path"])


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0010_runlog_stage_timings"),
    ]

    operations = [
        migrations.AddField(
            model_name="document",
            name="storage_path",
            field=models.CharField(blank=True, max_length=500, null=True),
        ),
        migrations.RunPython(backfill_storage_path, migrations.RunPython.noop),
    ]
