# Generated manually for the initial Palette schema.
import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations = [
        migrations.CreateModel(
            name="Photo",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("original", models.ImageField(upload_to="original/%Y/%m/%d/")),
                ("display", models.ImageField(blank=True, upload_to="display/%Y/%m/%d/")),
                ("thumbnail", models.ImageField(blank=True, upload_to="thumb/%Y/%m/%d/")),
                ("color_tag", models.CharField(blank=True, choices=[("red", "赤"), ("orange", "オレンジ"), ("yellow", "黄"), ("green", "緑"), ("blue", "青"), ("gray", "グレー"), ("other", "その他")], max_length=10)),
                ("color_confidence", models.FloatField(blank=True, null=True)),
                ("status", models.CharField(choices=[("pending", "待機中"), ("processing", "処理中"), ("ready", "公開中"), ("failed", "失敗")], default="pending", max_length=12)),
                ("width", models.PositiveIntegerField(blank=True, null=True)),
                ("height", models.PositiveIntegerField(blank=True, null=True)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="photos", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.AddIndex(model_name="photo", index=models.Index(fields=["status", "color_tag", "-created_at"], name="photos_phot_status_c3fb5d_idx")),
    ]
