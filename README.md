# Chat-with-Gemini[Google認証付き Streamlitチャットアプリケーション (GCPサーバーレス版)]

このプロジェクトは、Googleアカウントによる認証機能を備えたStreamlit製のチャットアプリケーションを、Google Cloud Functions (認証バックエンド) および Cloud Run (Streamlitフロントエンド) 上にデプロイするサンプルアプリケーションです。

## 概要

ユーザーは自身のGoogleアカウントでログインし、許可されたユーザーのみがチャット機能を利用できます。認証処理はFlaskベースのバックエンドで行い、カスタムJWTを発行します。フロントエンドはStreamlitで構築され、リアルタイムに近いチャット体験を提供することを目指しています（現在の実装ではメッセージ送信時に更新）。

## アーキテクチャ

*   **フロントエンド:** Streamlit (Python) - Cloud Runにデプロイ
*   **認証バックエンド:** Flask (Python) - Cloud Functions (第2世代) にデプロイ
*   **認証プロバイダ:** Google (OAuth 2.0 / OpenID Connect)
*   **セッショントークン:** カスタムJWT (JSON Web Token)
*   **データベース (チャット履歴):** Firestore (NoSQLドキュメントデータベース)
*   **機密情報管理:** Google Cloud Secret Manager
*   **CI/CD (デプロイ):** Google Cloud Build

**(ここにシンプルなアーキテクチャ図を挿入することを推奨します)**
例:


[ユーザー (ブラウザ)] <=> [Streamlit on Cloud Run]
^ | (JWT検証, Firestoreアクセス)
| (ログイン/JWT) |
+-----> [Flask on Cloud Functions] <-----> [Google Auth]
(OAuth, JWT発行)
^ ^
| (Secrets)| (Chat Data)
+--------> [Secret Manager]
+--------> [Firestore]

## 主な機能

*   Googleアカウントによるログイン・ログアウト機能
*   許可されたユーザーのみがアクセス可能なチャットルーム
*   リアルタイムに近いメッセージ送受信 (現在は送信時に更新)
*   CSRF対策を施した認証フロー
*   カスタムJWTによるセッション管理

## ディレクトリ構造

.
├── auth_server_flask/ # Flask認証バックエンド
│ ├── main.py # Flaskアプリ起動, CFエントリーポイント
│ ├── config.py # 設定管理
│ ├── auth_handlers.py # ルート処理ロジック
│ ├── auth_utils.py # 認証ユーティリティ
│ ├── requirements.txt
│ └── .env.example # ローカル用環境変数テンプレート
│
├── streamlit_app/ # Streamlitフロントエンド
│ ├── app.py # Streamlitアプリ本体
│ ├── ui_components.py # UIコンポーネント (ログイン画面、チャット画面)
│ ├── firebase_utils.py # Firestore連携、SM連携(許可リスト)
│ ├── auth_utils.py # JWT検証、ユーザー処理など
│ ├── requirements.txt
│ ├── Dockerfile
│ └── .streamlit/
│ └── secrets.toml.example # ローカル用Streamlitシークレットテンプレート
│
├── cloudbuild_auth.yaml # Cloud Functionsデプロイ用Cloud Build設定
├── cloudbuild_streamlit.yaml # Streamlitアプリデプロイ用Cloud Build設定
├── .gitignore
├── .gcloudignore # Cloud Buildアップロード除外設定
└── README.md

## セットアップと実行

### 前提条件

*   Google Cloud SDK (gcloud CLI) がインストールされ、設定済みであること。
*   Python 3.10以上がインストールされていること。
*   Dockerがインストールされていること (Streamlitアプリのローカルビルドやデプロイに必要)。
*   Gitがインストールされていること。
*   GCPプロジェクトが作成済みで、以下のAPIが有効になっていること:
    *   Cloud Functions API
    *   Cloud Run Admin API
    *   Cloud Build API
    *   Secret Manager API
    *   Identity and Access Management (IAM) API
    *   Artifact Registry API
    *   Firestore API (もし使用する場合)
*   Google OAuth 2.0 クライアントIDとクライアントシークレットが取得済みであること。
*   Firebaseプロジェクトがセットアップされ、Firestoreデータベースが有効になっていること (もし使用する場合)。
*   必要なサービスアカウントが作成され、適切な権限が付与されていること (詳細は各YAMLファイル参照)。

### ローカル開発環境セットアップ

1.  **リポジトリのクローン:**
    ```bash
    git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY_NAME.git
    cd YOUR_REPOSITORY_NAME
    ```

2.  **Flask認証サーバーのセットアップ (`auth_server_flask`):**
    *   `cd auth_server_flask`
    *   Python仮想環境の作成と有効化:
        ```bash
        python -m venv venv
        source venv/bin/activate # Linux/macOS
        # venv\Scripts\activate # Windows
        ```
    *   依存ライブラリのインストール:
        ```bash
        pip install -r requirements.txt
        ```
    *   `.env.example` をコピーして `.env` ファイルを作成し、ローカル用の設定値を記述します (特に `DIRECT_...` で始まる変数)。
        *   `DIRECT_GOOGLE_CLIENT_ID`
        *   `DIRECT_GOOGLE_CLIENT_SECRET`
        *   `DIRECT_JWT_SECRET_KEY` (強力なランダム文字列)
        *   `DIRECT_ALLOWED_USERS_LIST_JSON_STR` (例: `'["user1@example.com"]'`)
        *   `GCP_PROJECT` (実際のGCPプロジェクトID)
    *   Google OAuthクライアント設定で、「承認済みのリダイレクト URI」に `http://localhost:8080/auth_callback` を追加します。

3.  **Streamlitアプリのセットアップ (`streamlit_app`):**
    *   `cd streamlit_app`
    *   Python仮想環境の作成と有効化 (Flask側と別でも可):
        ```bash
        python -m venv venv_streamlit_local # 別の名前で作成
        source venv_streamlit_local/bin/activate # Linux/macOS
        # venv_streamlit_local\Scripts\activate # Windows
        ```
    *   依存ライブラリのインストール:
        ```bash
        pip install -r requirements.txt
        ```
    *   `.streamlit/secrets.toml.example` をコピーして `.streamlit/secrets.toml` を作成し、ローカル用の設定値を記述します。
        *   `STREAMLIT_JWT_SECRET_KEY` (Flask側の `.env` の `DIRECT_JWT_SECRET_KEY` と同じ値)
        *   `STREAMLIT_AUTH_LOGIN_URL = "http://localhost:8080/auth_login"`
        *   `STREAMLIT_EXPECTED_ISSUER = "http://localhost:8080"`
        *   `STREAMLIT_EXPECTED_AUDIENCE = "http://localhost:8501"`
        *   `FIREBASE_SERVICE_ACCOUNT_JSON_STR` (ローカルテスト用のサービスアカウントキーのJSON文字列。または `serviceAccountKey.json` を配置し、`firebase_utils.py` がそれを読み込むようにする)
        *   `GCP_PROJECT_ID` (実際のGCPプロジェクトID)
        *   `SECRET_ID_ALLOWED_EMAILS` (ローカルテストでSMを参照する場合のシークレットID、またはダミー)
    *   もし `serviceAccountKey.json` を使う場合は、`streamlit_app` ディレクトリ直下に配置し、`.gitignore` と `.gcloudignore` に追加します。

### ローカルでの実行

1.  **Flask認証サーバーの起動:**
    ```bash
    cd auth_server_flask
    python main.py --mode local_direct # または --mode local_sm_test
    ```
    (サーバーは `http://localhost:8080` で起動します)

2.  **Streamlitアプリの起動:**
    別のターミナルを開き、
    ```bash
    cd streamlit_app
    streamlit run app.py
    ```
    (アプリは通常 `http://localhost:8501` で起動します)

3.  ブラウザで `http://localhost:8501` にアクセスします。

### クラウドへのデプロイ (GCP)

1.  **Secret Managerの設定:**
    GCPコンソールでSecret Managerに必要なシークレット（`GOOGLE_CLIENT_ID_PROD_SM`, `GOOGLE_CLIENT_SECRET_PROD_SM`, `JWT_SECRET_KEY_PROD_SM`, `ALLOWED_USERS_LIST_PROD_SM` (JSON配列形式), `FUNCTION_BASE_URL_PROD_SM` (初回はダミー), `STREAMLIT_APP_URL_PROD_SM` (初回はダミー), `streamlit-firebase-sa-key` (Firebase SAキーのJSON文字列)）を登録します。

2.  **`cloudbuild_auth.yaml` の設定:**
    *   `substitutions` セクションの `_CF_SERVICE_ACCOUNT_EMAIL` や `_SM_NAME_...` の各値を実際の環境に合わせて設定します。

3.  **Cloud Functions (認証サーバー) のデプロイ:**
    ```bash
    gcloud builds submit --config cloudbuild_auth.yaml .
    ```
    デプロイ後、出力されたCloud FunctionsのURL (`auth-service URI`) を確認し、Secret Managerの `FUNCTION_BASE_URL_PROD_SM` とGoogle OAuthクライアントの「承認済みのリダイレクト URI」 (`<CFのURL>/auth_callback`) を更新します。その後、再度このCloud Buildを実行して設定を反映させます（またはCloud Functionsサービスを再起動）。

4.  **`cloudbuild_streamlit.yaml` の設定:**
    *   `substitutions` セクションの `_CF_AUTH_SERVICE_BASE_URL` に手順3で確定したCloud FunctionsのURLを設定します。
    *   `_STREAMLIT_APP_PUBLIC_URL` には、これからデプロイするStreamlitアプリの想定される公開URL（または初回はプレースホルダー）を設定します。
    *   他の `_SM_NAME_...` や `_STREAMLIT_SERVICE_ACCOUNT_EMAIL` も実際の環境に合わせます。

5.  **Streamlitアプリ (Cloud Run) のデプロイ:**
    ```bash
    gcloud builds submit --config cloudbuild_streamlit.yaml .
    ```
    デプロイ後、出力されたStreamlitアプリのURL (`Deployed Streamlit App URL`) を確認します。

6.  **最終設定更新と再デプロイ:**
    *   **Cloud Run:** 環境変数 `STREAMLIT_EXPECTED_AUDIENCE` を、手順5で確認したStreamlitアプリの実際の公開URLに更新し、新しいリビジョンをデプロイします。
    *   **Secret Manager:** `STREAMLIT_APP_URL_PROD_SM` の値を、手順5で確認したStreamlitアプリの実際の公開URLに更新します。
    *   **Cloud Functions:** 手順4のCloud Buildを再度実行し、更新された `STREAMLIT_APP_URL_PROD_SM` をCloud Functionsが読み込むようにします。

7.  デプロイされたStreamlitアプリのURLにアクセスし、動作を確認します。

## 今後の課題・改善点

*   チャットのリアルタイム性のさらなる向上 (WebSocketやFirestoreリスナーのより高度な活用)。
*   エラーハンドリングのUI/UX改善。
*   リフレッシュトークンの実装によるセッション持続性の向上。
*   テストコードの拡充。
*   CI/CDパイプラインの完全自動化。

## ライセンス

(もしあればライセンス情報を記述)

## 貢献

(もしあれば貢献方法を記述)
