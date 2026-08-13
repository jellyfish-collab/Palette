# GCP デプロイ手順とコマンド解説

Palette を Cloud Run、Cloud SQL、Cloud Storage、Pub/Sub、Vision API で動かすための手順です。すべて `Cloud Shell` で実行します。リージョンは東京の `asia-northeast1` に統一します。

> `export` は、現在開いているシェルだけで使える環境変数を設定する Bash の組み込みコマンドです。Cloud Shell を再起動した場合は、必要な `export` を再実行してください。

## 1. プロジェクトと API

```bash
gcloud config set project YOUR_PROJECT_ID
gcloud services enable run.googleapis.com sqladmin.googleapis.com storage.googleapis.com pubsub.googleapis.com vision.googleapis.com secretmanager.googleapis.com artifactregistry.googleapis.com cloudbuild.googleapis.com
export REGION=asia-northeast1
export PROJECT_ID=$(gcloud config get-value project)
export PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
```

- `gcloud config set project`: 以降の `gcloud` コマンドの対象 GCP プロジェクトを指定します。`YOUR_PROJECT_ID` はプロジェクト番号ではなく、例: `palette-505406` のようなプロジェクト ID です。
- `gcloud services enable`: 指定した API を有効化します。`run` は Cloud Run、`sqladmin` は Cloud SQL、`storage` は Cloud Storage、`pubsub` はキュー、`vision` は色彩分析、`secretmanager` は秘密情報、`artifactregistry` はコンテナ保存先、`cloudbuild` はコンテナビルドに対応します。
- `export REGION=...`: デプロイ先リージョンを変数化します。同じリージョンに置くと遅延とリージョン間通信を抑えられます。
- `$(...)`: コマンドの出力を変数へ入れる Bash の記法です。`PROJECT_ID` と `PROJECT_NUMBER` は IAM 設定などで使います。

## 2. 実行用サービスアカウントと画像バケット

```bash
gcloud iam service-accounts create palette-runtime --display-name="Palette runtime"
export SA="palette-runtime@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud storage buckets create "gs://${PROJECT_ID}-palette-media" --location="$REGION"

gcloud storage buckets add-iam-policy-binding "gs://${PROJECT_ID}-palette-media" \
  --member="serviceAccount:${SA}" \
  --role="roles/storage.objectAdmin"

gcloud storage buckets add-iam-policy-binding "gs://${PROJECT_ID}-palette-media" \
  --member="allUsers" \
  --role="roles/storage.objectViewer"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" \
  --role="roles/cloudsql.client"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" \
  --role="roles/pubsub.publisher"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SA}" \
  --role="roles/serviceusage.serviceUsageConsumer"
```

- `gcloud iam service-accounts create`: Cloud Run が Google Cloud のサービスへアクセスするときの「アプリ用 ID」を作ります。人間の Google アカウントとは別です。
- `--display-name`: コンソールに表示する分かりやすい名前です。権限には影響しません。
- `gcloud storage buckets create`: `gs://` で始まる Cloud Storage バケットを作ります。バケット名は全世界で重複不可です。
- `--location`: バケットを保存するリージョンです。
- `add-iam-policy-binding`: 指定した対象に、誰が（`--member`）どの権限を持つか（`--role`）を追加します。
- `roles/storage.objectAdmin`: アプリが画像の作成・読み取り・削除を行う権限です。
- `allUsers` + `roles/storage.objectViewer`: 表示用画像を URL から閲覧可能にします。画像を非公開にしたい場合は、この行を実行せず、将来は署名付き URL を実装します。
- `roles/cloudsql.client`: Cloud Run から Cloud SQL Auth Proxy 接続を行う権限です。
- `roles/pubsub.publisher`: Web サービスが「画像を処理して」というメッセージを Pub/Sub へ送る権限です。
- `roles/serviceusage.serviceUsageConsumer`: Vision API など、Google API の利用に必要になることがあるサービス利用権限です。

## 3. Cloud SQL（PostgreSQL）とシークレット

コンソールで Cloud SQL の **PostgreSQL / Enterprise / Sandbox / Single zone** として `palette-db` を作成します。Marketplace の Click to Deploy PostgreSQL（VM）は使用しません。

```bash
export INSTANCE=palette-db
export INSTANCE_CONNECTION_NAME=$(gcloud sql instances describe "$INSTANCE" --format='value(connectionName)')

gcloud sql databases create palette --instance="$INSTANCE"

read -s -p "palette_user 用DBパスワードを入力: " DB_PASSWORD
echo
gcloud sql users create palette_user \
  --instance="$INSTANCE" \
  --password="$DB_PASSWORD"
```

- `gcloud sql instances describe`: 既存インスタンスの情報を取得します。
- `--format='value(connectionName)'`: 出力を `プロジェクト:リージョン:インスタンス名` の接続名だけに絞ります。Cloud Run が Cloud SQL を指定する際に使います。
- `gcloud sql databases create palette`: PostgreSQL インスタンス内に Django 用データベースを作成します。
- `--instance`: 対象の Cloud SQL インスタンス ID です。
- `read -s`: パスワードを画面に表示せずに入力し、`DB_PASSWORD` 変数へ入れます。パスワードをコマンド行へ直接書かないでください。
- `gcloud sql users create`: Django 専用の DB ユーザーを作成します。`postgres` 管理ユーザーをアプリで使わないための分離です。

```bash
export DJANGO_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
printf '%s' "$DJANGO_SECRET_KEY" | gcloud secrets create django-secret-key --data-file=-
printf '%s' "$DB_PASSWORD" | gcloud secrets create db-password --data-file=-

for SECRET in django-secret-key db-password; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${SA}" \
    --role="roles/secretmanager.secretAccessor"
done
```

- `python3 -c`: 短い Python コードを実行し、Django の署名用ランダムキーを生成します。
- `printf ... |`: 左の値を右のコマンドへ安全に標準入力として渡します。
- `gcloud secrets create`: Secret Manager に秘密情報を保存します。
- `--data-file=-`: `-` は「ファイルではなく標準入力から値を読む」という意味です。シークレット値を履歴に残しにくくします。
- `for ... do ... done`: 2個のシークレットへ同じ権限を繰り返し付与する Bash ループです。
- `roles/secretmanager.secretAccessor`: Cloud Run の実行用サービスアカウントが値を読むための最小権限です。

## 4. Artifact Registry と Pub/Sub

```bash
gcloud artifacts repositories create palette \
  --repository-format=docker \
  --location="$REGION"

gcloud pubsub topics create palette-image-processing

export CLOUD_BUILD_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${CLOUD_BUILD_SA}" \
  --role="roles/artifactregistry.writer"
```

- `gcloud artifacts repositories create`: コンテナイメージを保存する Artifact Registry リポジトリを作成します。
- `--repository-format=docker`: Docker / OCI コンテナイメージ用であることを指定します。
- `gcloud pubsub topics create`: Web と Worker の間で使う、画像処理メッセージの送信先（Topic）を作成します。
- `CLOUD_BUILD_SA`: Cloud Build が使うサービスアカウントのメールアドレスです。
- `roles/artifactregistry.writer`: Cloud Build がビルド済みコンテナを Registry へ push する権限です。

## 5. コンテナのビルドと Web サービスのデプロイ

```bash
gcloud builds submit \
  --config=cloudbuild.yaml \
  --substitutions=_REGION="${REGION}",_TAG=v2

export IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/palette/palette:v2"
```

- `gcloud builds submit`: 現在のディレクトリのソースを Cloud Build へ送信し、クラウド上で Docker build を実行します。
- `--config`: 使用するビルド定義ファイルです。Palette は `cloudbuild.yaml` を使います。
- `--substitutions`: YAML 内の `${_REGION}` と `${_TAG}` を置換します。コード更新ごとに `v3`、`v4` のようにタグを変えると、どのイメージをデプロイしたか追跡しやすくなります。
- `IMAGE`: Artifact Registry に作成されたコンテナイメージの完全名です。

```bash
gcloud run deploy palette-web \
  --image="$IMAGE" \
  --region="$REGION" \
  --allow-unauthenticated \
  --service-account="$SA" \
  --add-cloudsql-instances="$INSTANCE_CONNECTION_NAME" \
  --memory=1Gi \
  --concurrency=1 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GS_BUCKET_NAME=${PROJECT_ID}-palette-media,DB_NAME=palette,DB_USER=palette_user,DB_HOST=/cloudsql/${INSTANCE_CONNECTION_NAME},IMAGE_PROCESSING_TOPIC=palette-image-processing,DEBUG=false,SECURE_SSL_REDIRECT=true" \
  --set-secrets="DJANGO_SECRET_KEY=django-secret-key:latest,DB_PASSWORD=db-password:latest"
```

- `gcloud run deploy`: Cloud Run サービスを作成、または既存サービスを新リビジョンへ更新します。
- `--image`: 実行するコンテナイメージです。
- `--allow-unauthenticated`: 一般ユーザーのブラウザから Web アプリを開けるようにします。Worker には使用しません。
- `--service-account`: コンテナ内のアプリが利用する GCP の ID です。前章の `palette-runtime` を割り当てます。
- `--add-cloudsql-instances`: サービスに Cloud SQL Auth Proxy 接続を追加します。**Cloud Run サービス用**のオプションです。
- `--memory=1Gi`: 画像を Pillow で扱うため、メモリ上限を 1 GiB にします。512 MiB を超えるとインスタンスは終了します。
- `--concurrency=1`: 同時に1リクエストだけを処理します。画像の圧縮処理が重なってメモリ不足になるのを防ぎます。
- `--set-env-vars`: アプリの非秘密設定を環境変数で渡します。`DB_HOST=/cloudsql/...` は Cloud SQL Auth Proxy の Unix ソケットです。`DEBUG=false` は本番で必須です。
- `--set-secrets`: Secret Manager の値をコンテナ環境変数として渡します。`:latest` は最新バージョンを使う指定です。

```bash
export WEB_HOST=$(gcloud run services describe palette-web \
  --region="$REGION" \
  --format='value(status.url)' | sed 's#https://##')

gcloud run services update palette-web \
  --region="$REGION" \
  --set-env-vars="ALLOWED_HOSTS=${WEB_HOST}"
```

- `gcloud run services describe`: デプロイ済み Web サービスの情報を取得します。
- `status.url`: Cloud Run が発行した HTTPS URL です。`sed 's#https://##'` は Django の `ALLOWED_HOSTS` に必要なホスト名だけを取り出します。
- `gcloud run services update`: 既存 Web サービスの設定だけを更新し、新しいリビジョンを作ります。
- `ALLOWED_HOSTS`: Django が受け入れる Host ヘッダーの許可リストです。未設定だと本番で `400 Bad Request` になります。

## 6. DB マイグレーション Job

```bash
gcloud run jobs create palette-migrate \
  --image="$IMAGE" \
  --region="$REGION" \
  --service-account="$SA" \
  --set-cloudsql-instances="$INSTANCE_CONNECTION_NAME" \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GS_BUCKET_NAME=${PROJECT_ID}-palette-media,DB_NAME=palette,DB_USER=palette_user,DB_HOST=/cloudsql/${INSTANCE_CONNECTION_NAME},DEBUG=false" \
  --set-secrets="DJANGO_SECRET_KEY=django-secret-key:latest,DB_PASSWORD=db-password:latest" \
  --command=python \
  --args=manage.py,migrate

gcloud run jobs execute palette-migrate --region="$REGION" --wait
```

- `gcloud run jobs create`: HTTP サービスではなく、終了したら止まる一回限りの処理（Job）を作成します。
- `--set-cloudsql-instances`: Job に Cloud SQL 接続を設定します。Job では `--add-cloudsql-instances` ではなくこのオプションを使います。
- `--command=python`: Dockerfile の通常起動コマンド（Gunicorn）を上書きします。
- `--args=manage.py,migrate`: 上記 command に渡す引数です。最終的に `python manage.py migrate` が実行されます。
- `gcloud run jobs execute`: 作成した Job を一度実行します。
- `--wait`: Cloud Shell が完了まで待ち、成功・失敗を表示します。

コード更新後にマイグレーションが増えた場合は、`create` の代わりに `gcloud run jobs update ...` でイメージを更新してから、再度 `execute` します。

## 7. Worker と Pub/Sub サブスクリプション

```bash
gcloud run deploy palette-worker \
  --image="$IMAGE" \
  --region="$REGION" \
  --no-allow-unauthenticated \
  --service-account="$SA" \
  --add-cloudsql-instances="$INSTANCE_CONNECTION_NAME" \
  --memory=1Gi \
  --concurrency=1 \
  --set-env-vars="GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GS_BUCKET_NAME=${PROJECT_ID}-palette-media,DB_NAME=palette,DB_USER=palette_user,DB_HOST=/cloudsql/${INSTANCE_CONNECTION_NAME},DEBUG=false" \
  --set-secrets="DJANGO_SECRET_KEY=django-secret-key:latest,DB_PASSWORD=db-password:latest"

gcloud iam service-accounts create palette-pubsub \
  --display-name="Palette Pub/Sub invoker"
export PUBSUB_SA="palette-pubsub@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud run services add-iam-policy-binding palette-worker \
  --region="$REGION" \
  --member="serviceAccount:${PUBSUB_SA}" \
  --role="roles/run.invoker"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountTokenCreator"

export WORKER_URL=$(gcloud run services describe palette-worker \
  --region="$REGION" \
  --format='value(status.url)')
gcloud pubsub subscriptions create palette-worker-sub \
  --topic=palette-image-processing \
  --push-endpoint="${WORKER_URL}/internal/process-image/" \
  --push-auth-service-account="$PUBSUB_SA"
```

- `--no-allow-unauthenticated`: Worker を一般公開しません。Pub/Sub だけが認証付きで呼び出します。
- `palette-pubsub`: Pub/Sub が Worker 呼び出し時に名乗る専用サービスアカウントです。
- `roles/run.invoker`: このサービスアカウントにだけ、非公開 Worker を HTTP 呼び出しする権限を付与します。IAM 反映には数分かかる場合があります。
- `service-${PROJECT_NUMBER}@gcp-sa-pubsub...`: Google が管理する Pub/Sub のサービスエージェントです。
- `roles/iam.serviceAccountTokenCreator`: Pub/Sub が `palette-pubsub` として認証トークンを作るために必要です。
- `WORKER_URL`: Worker の非公開 Cloud Run URL を取得します。
- `gcloud pubsub subscriptions create`: Topic のメッセージを受け取る Subscription を作成します。
- `--topic`: 受信元 Topic です。
- `--push-endpoint`: Pub/Sub が HTTP POST する Worker の URL です。
- `--push-auth-service-account`: POST に付ける認証トークンの ID を指定します。

## 8. 確認とログ

```bash
echo "https://${WEB_HOST}"
gcloud run services logs read palette-web --region="$REGION" --limit=50
gcloud run services logs read palette-worker --region="$REGION" --limit=50
gcloud run jobs logs read palette-migrate --region="$REGION" --limit=100
```

- `echo`: URL を画面へ表示するだけです。
- `gcloud run services logs read`: Web または Worker の Cloud Logging を読みます。`--limit` は最大表示件数です。
- `gcloud run jobs logs read`: マイグレーション Job のログを読みます。`Applying ... OK` が並べば成功です。

ブラウザで、アカウント登録、画像投稿、数秒後の一覧表示、色フィルタ、投稿者本人による削除を確認してください。

## 9. 費用を抑えるための注意

Cloud Run は通常、リクエスト処理中だけが主な課金対象ですが、Cloud SQL はインスタンスが存在している間に料金がかかります。学習を終える際は、必要なデータをエクスポートしてから Cloud SQL インスタンスを削除してください。Cloud Storage の画像や Artifact Registry のコンテナも、残している限り少額の保存料金が発生します。
