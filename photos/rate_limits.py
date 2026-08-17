"""Cloud Run の複数インスタンスでも共有できる、簡易的な固定時間枠レート制限。"""

import hashlib
import math
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .models import RateLimitBucket


def _key(scope, identifier):
    """識別子をハッシュ化し、ユーザー名やIPアドレスを平文で保存しない。"""
    value = f"{scope}:{identifier}".encode("utf-8")
    return hashlib.sha256(value).hexdigest()


def client_ip(request):
    """Cloud Run から渡される先頭の転送元IPを、登録制限の識別子として使う。"""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return forwarded.split(",")[0].strip() if forwarded else request.META.get("REMOTE_ADDR", "")


def is_limited(scope, identifier, limit, window_seconds):
    """重い処理の前に確認するための簡易チェック。最終判定は consume で行う。"""
    bucket = RateLimitBucket.objects.filter(key=_key(scope, identifier)).first()
    if not bucket:
        return False, 0
    elapsed = timezone.now() - bucket.window_started_at
    if elapsed >= timedelta(seconds=window_seconds) or bucket.count < limit:
        return False, 0
    return True, max(1, math.ceil(window_seconds - elapsed.total_seconds()))


def consume(scope, identifier, limit, window_seconds):
    """1回分を消費し、並行リクエストでも上限を超えないよう行ロックを使う。"""
    now = timezone.now()
    key = _key(scope, identifier)
    with transaction.atomic():
        bucket, created = RateLimitBucket.objects.select_for_update().get_or_create(
            key=key,
            defaults={"window_started_at": now, "count": 0},
        )
        elapsed = now - bucket.window_started_at
        if not created and elapsed >= timedelta(seconds=window_seconds):
            bucket.window_started_at = now
            bucket.count = 0
        if bucket.count >= limit:
            retry_after = max(1, math.ceil(window_seconds - elapsed.total_seconds()))
            return False, retry_after
        bucket.count += 1
        bucket.save(update_fields=["window_started_at", "count", "updated_at"])
    return True, 0


def clear(scope, identifier):
    """ログイン成功後は失敗試行の記録を削除し、通常利用者を不要に制限しない。"""
    RateLimitBucket.objects.filter(key=_key(scope, identifier)).delete()
