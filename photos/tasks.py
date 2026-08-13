import base64
import json
from django.conf import settings
from google.cloud import pubsub_v1
from .services import process_photo


def enqueue_processing(photo):
    # 開発時は同期実行、本番は HTTP 応答を待たせない Pub/Sub 経由にする。
    if settings.SYNCHRONOUS_IMAGE_PROCESSING:
        return process_photo(photo.pk)
    if not settings.IMAGE_PROCESSING_TOPIC or not settings.GCP_PROJECT_ID:
        raise RuntimeError("IMAGE_PROCESSING_TOPIC と GOOGLE_CLOUD_PROJECT を設定してください。")
    publisher = pubsub_v1.PublisherClient()
    topic = publisher.topic_path(settings.GCP_PROJECT_ID, settings.IMAGE_PROCESSING_TOPIC)
    publisher.publish(topic, json.dumps({"photo_id": str(photo.pk)}).encode()).result()


def process_pubsub_body(body):
    # Pub/Sub の push メッセージから写真IDだけを取り出し、冪等な処理へ渡す。
    encoded = body["message"]["data"]
    payload = json.loads(base64.b64decode(encoded).decode())
    return process_photo(payload["photo_id"])
