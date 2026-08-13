# Palette

色彩で写真を巡る Django 製画像投稿アプリです。Cloud Run 上で Django を実行し、Cloud Storage、Cloud SQL、Pub/Sub、Cloud Vision API を組み合わせる構成です。

## ローカル起動

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

`http://127.0.0.1:8000/` を開き、登録後に画像を投稿します。ローカルでは Vision API を呼ばず、平均色を使ってタグ付けします。

GCP へのデプロイ手順は [GCP_SETUP.md](GCP_SETUP.md) を参照してください。
