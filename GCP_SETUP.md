# GCP デプロイ手順

以下ではリージョンを東京の `asia-northeast1` とします。Cloud Run、Cloud SQL、Cloud Storage は同一リージョンに揃えてください。

## 1. プロジェクトと API

Cloud Shell でプロジェクトを選択し、必要な API を有効化します。

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com sqladmin.googleapis.com storage.googleapis.com pubsub.googleapis.com vision.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
export REGION=asia-northeast1
export PROJECT_ID=$(gcloud config get-value project)
```

## 2. サービスアカウントとバケット

```bash
gcloud iam service-accounts create palette-runtime --display-name="Palette runtime"
export SA=palette-runtime@${PROJECT_ID}.iam.gserviceaccount.com
gcloud storage buckets create gs://${PROJECT_ID}-palette-media --location=${REGION}
gcloud storage buckets add-iam-policy-binding gs://${PROJECT_ID}-palette-media --member=serviceAccount:${SA} --role=roles/storage.objectAdmin
gcloud storage buckets add-iam-policy-binding gs://${PROJECT_ID}-palette-media --member=allUsers --role=roles/storage.objectViewer
gcloud projects add-iam-policy-binding ${PROJECT_ID} --member=serviceAccount:${SA} --role=roles/cloudsql.client
gcloud projects add-iam-policy-binding ${PROJECT_ID} --member=serviceAccount:${SA} --role=roles/pubsub.publisher
gcloud projects add-iam-policy-binding ${PROJECT_ID} --member=serviceAccount:${SA} --role=roles/serviceusage.serviceUsageConsumer
```

Vision API の利用権限は、組織の IAM ポリシーにより追加設定が必要な場合があります。まず最小構成で動かし、`vision.images.annotate` の権限エラーが出たらプロジェクト管理者へ Vision 利用を依頼してください。

## 3. Cloud SQL（PostgreSQL）

本番では Cloud SQL Auth Proxy 接続を使います。コンソールから PostgreSQL インスタンス（例: `palette-db`）を作成後、DB とユーザーを作ります。

```bash
gcloud sql databases create palette --instance=palette-db
gcloud sql users create palette_user --instance=palette-db --password='十分に長いランダムなパスワード'
export INSTANCE_CONNECTION_NAME=$(gcloud sql instances describe palette-db --format='value(connectionName)')
```

以下のシークレットを作成します。値を画面・Git・コマンド履歴に残さない運用にしてください。

```bash
printf '%s' 'DjangoのランダムなSECRET_KEY' | gcloud secrets create django-secret-key --data-file=-
printf '%s' 'Cloud SQLのパスワード' | gcloud secrets create db-password --data-file=-
for SECRET in django-secret-key db-password; do gcloud secrets add-iam-policy-binding $SECRET --member=serviceAccount:${SA} --role=roles/secretmanager.secretAccessor; done
```

## 4. Artifact Registry と Pub/Sub

```bash
gcloud artifacts repositories create palette --repository-format=docker --location=${REGION}
gcloud pubsub topics create palette-image-processing
gcloud iam service-accounts create palette-pubsub --display-name="Palette PubSub invoker"
export PUBSUB_SA=palette-pubsub@${PROJECT_ID}.iam.gserviceaccount.com
```

## 5. ビルドと Web サービスのデプロイ

```bash
gcloud builds submit --config cloudbuild.yaml --substitutions=_REGION=${REGION},_TAG=v1
export IMAGE=${REGION}-docker.pkg.dev/${PROJECT_ID}/palette/palette:v1
gcloud run deploy palette-web --image=${IMAGE} --region=${REGION} --allow-unauthenticated --service-account=${SA} --add-cloudsql-instances=${INSTANCE_CONNECTION_NAME} --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GS_BUCKET_NAME=${PROJECT_ID}-palette-media,DB_NAME=palette,DB_USER=palette_user,DB_HOST=/cloudsql/${INSTANCE_CONNECTION_NAME},IMAGE_PROCESSING_TOPIC=palette-image-processing,DEBUG=false,SECURE_SSL_REDIRECT=true" --set-secrets="DJANGO_SECRET_KEY=django-secret-key:latest,DB_PASSWORD=db-password:latest"
```

Cloud Run のサービス URL を取得し、`ALLOWED_HOSTS` にそのホスト名を設定して再デプロイします。独自ドメインを付ける場合は、そのドメインも追加します。

```bash
export WEB_HOST=$(gcloud run services describe palette-web --region=${REGION} --format='value(status.url)' | sed 's#https://##')
gcloud run services update palette-web --region=${REGION} --set-env-vars="ALLOWED_HOSTS=${WEB_HOST}"
```

## 6. DB マイグレーション

ローカルで `makemigrations` 済みのマイグレーションファイルを Git に含めた上で、同じイメージを Cloud Run Job として実行します。

```bash
gcloud run jobs create palette-migrate --image=${IMAGE} --region=${REGION} --service-account=${SA} --add-cloudsql-instances=${INSTANCE_CONNECTION_NAME} --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GS_BUCKET_NAME=${PROJECT_ID}-palette-media,DB_NAME=palette,DB_USER=palette_user,DB_HOST=/cloudsql/${INSTANCE_CONNECTION_NAME},DEBUG=false" --set-secrets="DJANGO_SECRET_KEY=django-secret-key:latest,DB_PASSWORD=db-password:latest" --command=python --args=manage.py,migrate
gcloud run jobs execute palette-migrate --region=${REGION} --wait
```

## 7. Worker と Pub/Sub サブスクリプション

同一イメージを、内部専用 Worker としてもう一つデプロイします。

```bash
gcloud run deploy palette-worker --image=${IMAGE} --region=${REGION} --no-allow-unauthenticated --service-account=${SA} --add-cloudsql-instances=${INSTANCE_CONNECTION_NAME} --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GS_BUCKET_NAME=${PROJECT_ID}-palette-media,DB_NAME=palette,DB_USER=palette_user,DB_HOST=/cloudsql/${INSTANCE_CONNECTION_NAME},DEBUG=false" --set-secrets="DJANGO_SECRET_KEY=django-secret-key:latest,DB_PASSWORD=db-password:latest"
gcloud run services add-iam-policy-binding palette-worker --region=${REGION} --member=serviceAccount:${PUBSUB_SA} --role=roles/run.invoker
gcloud pubsub subscriptions create palette-worker-sub --topic=palette-image-processing --push-endpoint="$(gcloud run services describe palette-worker --region=${REGION} --format='value(status.url)')/internal/process-image/" --push-auth-service-account=${PUBSUB_SA}
```

これで Web 側は投稿受付だけを行い、Worker がリサイズと Vision API 分析を行います。Worker でエラーが返ると Pub/Sub が再試行します。Cloud Logging で `palette-worker` のログを確認してください。

## 8. デプロイ後の確認

- Cloud Run の `palette-web` URL を開き、アカウントを登録する。
- 画像を投稿し、数秒後に一覧表示されることを確認する。
- 色ボタンでフィルタできること、投稿者以外が削除できないことを確認する。
- Cloud Logging で Worker の成功・失敗ログを確認する。

## 注意

この最小構成では表示画像を Cloud Storage から直接参照します。バケットは画像の閲覧を許可する公開用メディアとして扱ってください。画像を非公開にしたい場合は、アプリが署名付き URL を発行する方式へ変更します。
