from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0009_runlog_confidence_score_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="runlog",
            name="generation_ms",
            field=models.IntegerField(
                blank=True,
                help_text="Generation/synthesis stage latency in milliseconds (if tracked)",
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="runlog",
            name="retrieval_ms",
            field=models.IntegerField(
                blank=True,
                help_text="Retrieval stage latency in milliseconds (if tracked)",
                null=True,
            ),
        ),
    ]
