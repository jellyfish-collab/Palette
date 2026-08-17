# Cloud Run の全インスタンスで共有するレート制限カウンター。

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("photos", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="RateLimitBucket",
            fields=[
                ("key", models.CharField(max_length=64, primary_key=True, serialize=False)),
                ("window_started_at", models.DateTimeField()),
                ("count", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
