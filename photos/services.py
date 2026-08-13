import io
import colorsys
from pathlib import Path
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps
from google.cloud import vision
from .models import Photo


def classify_rgb(red, green, blue):
    # Vision API の RGB 値を、Palette 固有の固定タグへ正規化する。
    hue, saturation, value = colorsys.rgb_to_hsv(red / 255, green / 255, blue / 255)
    if saturation < 0.18 or value < 0.12:
        return Photo.Color.GRAY
    degree = hue * 360
    if degree < 20 or degree >= 345:
        return Photo.Color.RED
    if degree < 50:
        return Photo.Color.ORANGE
    if degree < 75:
        return Photo.Color.YELLOW
    if degree < 170:
        return Photo.Color.GREEN
    if degree < 265:
        return Photo.Color.BLUE
    return Photo.Color.OTHER


def _dominant_color(photo, image):
    # 本番は Vision API、ローカルでは API コスト不要の平均色を使う。
    if settings.GCP_PROJECT_ID and settings.GS_BUCKET_NAME:
        client = vision.ImageAnnotatorClient()
        response = client.image_properties(image=vision.Image(source=vision.ImageSource(image_uri=f"gs://{settings.GS_BUCKET_NAME}/{photo.original.name}")))
        if response.error.message:
            raise RuntimeError(response.error.message)
        colors = response.image_properties_annotation.dominant_colors.colors
        if colors:
            dominant = max(colors, key=lambda color: color.pixel_fraction)
            rgb = dominant.color
            return classify_rgb(rgb.red, rgb.green, rgb.blue), dominant.pixel_fraction
    # ローカル開発では平均色で代替し、外部 API なしで試せるようにする。
    sample = image.convert("RGB").resize((1, 1))
    red, green, blue = sample.getpixel((0, 0))
    return classify_rgb(red, green, blue), 1.0


def _save_jpeg(field, filename, image, size):
    # 元画像をそのまま表示せず、用途別サイズへ変換して転送量を抑える。
    copy = image.copy()
    copy.thumbnail(size, Image.Resampling.LANCZOS)
    output = io.BytesIO()
    copy.save(output, format="JPEG", quality=88, optimize=True)
    field.save(filename, ContentFile(output.getvalue()), save=False)


def process_photo(photo_id):
    # Pub/Sub は少なくとも一回配送されうるため、完了済みの再実行は無視する。
    photo = Photo.objects.get(pk=photo_id)
    if photo.status == Photo.Status.READY:
        return photo
    photo.status = Photo.Status.PROCESSING
    photo.save(update_fields=["status"])
    try:
        with photo.original.open("rb") as source:
            image = ImageOps.exif_transpose(Image.open(source)).convert("RGB")
            image.load()
        if image.width * image.height > settings.MAX_IMAGE_PIXELS:
            raise ValueError("画像の解像度が大きすぎます。")
        color, confidence = _dominant_color(photo, image)
        stem = Path(photo.original.name).stem
        _save_jpeg(photo.display, f"display/{stem}.jpg", image, (1600, 1600))
        _save_jpeg(photo.thumbnail, f"thumb/{stem}.jpg", image, (500, 500))
        photo.width, photo.height = image.size
        photo.color_tag, photo.color_confidence = color, confidence
        photo.status, photo.error_message = Photo.Status.READY, ""
        photo.save()
    except Exception as error:
        photo.status, photo.error_message = Photo.Status.FAILED, str(error)[:1000]
        photo.save(update_fields=["status", "error_message"])
        raise
    return photo
