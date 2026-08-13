import uuid
from django.conf import settings
from django.db import models


class Photo(models.Model):
    # UI と検索条件で共通利用するため、色タグは自由入力ではなく固定値にする。
    class Color(models.TextChoices):
        RED = "red", "赤"
        ORANGE = "orange", "オレンジ"
        YELLOW = "yellow", "黄"
        GREEN = "green", "緑"
        BLUE = "blue", "青"
        GRAY = "gray", "グレー"
        OTHER = "other", "その他"

    class Status(models.TextChoices):
        PENDING = "pending", "待機中"
        PROCESSING = "processing", "処理中"
        READY = "ready", "公開中"
        FAILED = "failed", "失敗"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="photos")
    # 原本・一覧用・拡大表示用を分け、画面に必要なサイズだけを配信する。
    original = models.ImageField(upload_to="original/%Y/%m/%d/")
    display = models.ImageField(upload_to="display/%Y/%m/%d/", blank=True)
    thumbnail = models.ImageField(upload_to="thumb/%Y/%m/%d/", blank=True)
    color_tag = models.CharField(max_length=10, choices=Color.choices, blank=True)
    color_confidence = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "color_tag", "-created_at"])]

    def __str__(self):
        return f"{self.owner} / {self.id}"
