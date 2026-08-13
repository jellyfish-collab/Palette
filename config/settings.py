import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
# 本番では Secret Manager から渡し、開発時だけ既定値を使用する。
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "unsafe-local-development-key")
DEBUG = os.environ.get("DEBUG", "true").lower() == "true"
ALLOWED_HOSTS = [host for host in os.environ.get("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",") if host]

INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "storages", "photos",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware", "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware", "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "templates"], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request", "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
WSGI_APPLICATION = "config.wsgi.application"

# DB_NAME がある Cloud Run 環境では Cloud SQL（PostgreSQL）へ接続する。
if os.environ.get("DB_NAME"):
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql", "NAME": os.environ["DB_NAME"],
        "USER": os.environ["DB_USER"], "PASSWORD": os.environ["DB_PASSWORD"],
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"), "PORT": os.environ.get("DB_PORT", "5432"),
    }}
# ローカル開発は追加セットアップ不要な SQLite を使う。
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LANGUAGE_CODE = "ja"
TIME_ZONE = "Asia/Tokyo"
USE_I18N = True
USE_TZ = True
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# プロジェクト共通の CSS / JavaScript を Django の静的ファイル探索対象にする。
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage" if DEBUG else "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "photo_list"
LOGOUT_REDIRECT_URL = "photo_list"

# 原本も含め、Storage に保存する画像はこの上限以下に正規化する。
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
IMAGE_PROCESSING_TOPIC = os.environ.get("IMAGE_PROCESSING_TOPIC", "")
GCP_PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
GS_BUCKET_NAME = os.environ.get("GS_BUCKET_NAME", "")
SYNCHRONOUS_IMAGE_PROCESSING = os.environ.get("SYNCHRONOUS_IMAGE_PROCESSING", str(DEBUG)).lower() == "true"

# GCP ではメディアを Cloud Storage、ローカルでは media/ ディレクトリへ保存する。
if GS_BUCKET_NAME:
    STORAGES["default"] = {"BACKEND": "storages.backends.gcloud.GoogleCloudStorage"}
    GS_FILE_OVERWRITE = False
    GS_QUERYSTRING_AUTH = False
else:
    MEDIA_URL = "/media/"
    MEDIA_ROOT = BASE_DIR / "media"

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "false").lower() == "true"
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
