from io import BytesIO
import os
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from .models import Photo
from .forms import PhotoUploadForm, optimize_upload
from .services import classify_rgb


def image_file(color=(220, 30, 30)):
    content = BytesIO()
    Image.new("RGB", (40, 40), color).save(content, "JPEG")
    return SimpleUploadedFile("test.jpg", content.getvalue(), content_type="image/jpeg")


class PhotoTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password="safe-password-123")
        self.other = User.objects.create_user("other", password="safe-password-123")

    def test_color_classification(self):
        self.assertEqual(classify_rgb(220, 30, 30), Photo.Color.RED)
        self.assertEqual(classify_rgb(130, 130, 130), Photo.Color.GRAY)

    def test_optimizer_reduces_large_image_to_byte_limit(self):
        # 写真に近いノイズ画像で、容量を超えた場合の縮小ループを検証する。
        source = Image.frombytes("RGB", (800, 800), os.urandom(800 * 800 * 3))
        buffer = BytesIO()
        source.save(buffer, "JPEG", quality=100)
        upload = SimpleUploadedFile("large.jpg", buffer.getvalue(), content_type="image/jpeg")
        optimized = optimize_upload(upload, max_bytes=50 * 1024)
        self.assertLessEqual(optimized.size, 50 * 1024)
        self.assertEqual(optimized.content_type, "image/jpeg")

    @override_settings(SYNCHRONOUS_IMAGE_PROCESSING=True)
    def test_upload_processes_and_filters_photo(self):
        self.client.login(username="owner", password="safe-password-123")
        response = self.client.post(reverse("upload"), {"image": image_file()})
        self.assertRedirects(response, reverse("photo_list"))
        photo = Photo.objects.get()
        self.assertEqual(photo.status, Photo.Status.READY)
        response = self.client.get(reverse("photo_list"), {"color": "red"})
        self.assertContains(response, "owner")

    def test_non_owner_cannot_delete(self):
        photo = Photo.objects.create(owner=self.owner, original=image_file())
        self.client.login(username="other", password="safe-password-123")
        response = self.client.post(reverse("delete_photo", args=[photo.id]))
        self.assertEqual(response.status_code, 404)

    @override_settings(RATE_LIMIT_LOGIN_ATTEMPTS=1, RATE_LIMIT_LOGIN_WINDOW_SECONDS=3600)
    def test_login_is_limited_after_failed_attempt(self):
        # 最初の失敗は通常の認証エラー、次の試行は429で拒否される。
        response = self.client.post(reverse("login"), {"username": "owner", "password": "wrong-password"})
        self.assertEqual(response.status_code, 200)
        response = self.client.post(reverse("login"), {"username": "owner", "password": "wrong-password"})
        self.assertEqual(response.status_code, 429)

    @override_settings(
        RATE_LIMIT_UPLOAD_ATTEMPTS=1,
        RATE_LIMIT_UPLOAD_WINDOW_SECONDS=3600,
        SYNCHRONOUS_IMAGE_PROCESSING=True,
    )
    def test_upload_is_limited_per_account(self):
        self.client.login(username="owner", password="safe-password-123")
        response = self.client.post(reverse("upload"), {"image": image_file()})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(reverse("upload"), {"image": image_file()})
        self.assertEqual(response.status_code, 429)

    @override_settings(MAX_RECEIVED_UPLOAD_BYTES=100)
    def test_upload_rejects_file_larger_than_received_limit(self):
        # Pillowで開く前に止めるため、画像として不正な内容でもサイズ超過を検出できる。
        oversized = SimpleUploadedFile("large.bin", b"x" * 101, content_type="application/octet-stream")
        form = PhotoUploadForm(files={"image": oversized})
        self.assertFalse(form.is_valid())
        self.assertIn("30MB以下", form.errors["image"][0])
