import io
import math
from pathlib import Path
from django import forms
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps


def optimize_upload(image, max_bytes=settings.MAX_UPLOAD_BYTES, max_pixels=settings.MAX_IMAGE_PIXELS):
    """JPEG化し、画質・解像度を順に調整して指定容量以下へ変換する。"""
    image.seek(0)
    with Image.open(image) as opened:
        normalized = ImageOps.exif_transpose(opened).copy()
    if normalized.mode in ("RGBA", "LA"):
        # 透明 PNG は白背景に合成して JPEG 化する。
        background = Image.new("RGB", normalized.size, "white")
        background.paste(normalized, mask=normalized.getchannel("A"))
        normalized = background
    else:
        normalized = normalized.convert("RGB")

    # 極端に高解像度な画像も、メモリと後段 Worker を守るため先に縮小する。
    if normalized.width * normalized.height > max_pixels:
        ratio = math.sqrt(max_pixels / (normalized.width * normalized.height))
        normalized = normalized.resize(
            (int(normalized.width * ratio), int(normalized.height * ratio)), Image.Resampling.LANCZOS
        )

    quality = 90
    while True:
        output = io.BytesIO()
        normalized.save(output, format="JPEG", quality=quality, optimize=True)
        if output.tell() <= max_bytes:
            return SimpleUploadedFile(
                f"{Path(image.name).stem}.jpg", output.getvalue(), content_type="image/jpeg"
            )
        if quality > 60:
            quality -= 10
            continue
        width, height = normalized.size
        if min(width, height) <= 320:
            # 無限ループ防止の安全弁。通常の写真ではここまで到達しない。
            raise ValidationError("画像を10MB以下に変換できませんでした。")
        normalized = normalized.resize(
            (int(width * 0.8), int(height * 0.8)), Image.Resampling.LANCZOS
        )
        quality = 85


class PhotoUploadForm(forms.Form):
    image = forms.ImageField(label="写真を選択")

    def clean_image(self):
        image = self.cleaned_data["image"]
        try:
            with Image.open(image) as opened:
                opened.verify()
            image.seek(0)
            with Image.open(image) as opened:
                width, height = opened.size
        except (OSError, ValueError) as error:
            raise ValidationError("有効な画像ファイルを選択してください。") from error
        # 10MB超の画像も拒否せず、アップロード前に縮小してから保存する。
        if image.size > settings.MAX_UPLOAD_BYTES or width * height > settings.MAX_IMAGE_PIXELS:
            return optimize_upload(image)
        image.seek(0)
        return image
