from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rag", "0012_ingestionjob"),
    ]

    operations = [
        migrations.AddField(
            model_name="session",
            name="pinned",
            field=models.BooleanField(default=False),
        ),
    ]
