# app.py (モジュール分割後のメインファイル)
import streamlit as st
import os # GCP_PROJECT_IDなど環境変数を読むため
import json # FirebaseサービスアカウントキーをJSON文字列として環境変数で渡す場合

# --- 定数 ---
USER_INFO_KEY = "user_info" # auth_utils, ui_components でもこのキー名を参照
AUTH_ERROR_KEY = "auth_error_message" # auth_utils, ui_components でもこのキー名を参照

# --- ヘルパー関数 (st.secrets と環境変数のフォールバック) ---
def get_config_value(key_name, default_value=None):
    """
    環境変数を優先し、なければ st.secrets (もしあれば) から値を取得。
    両方になければデフォルト値を返す。
    キー名は環境変数と st.secrets で共通とすることを想定。
    """
    value = os.environ.get(key_name)
    if value is not None:
        return value
    if hasattr(st, 'secrets') and st.secrets is not None and key_name in st.secrets:
        return st.secrets[key_name]
    return default_value

# --- 設定値の読み込み ---
# Cloud Runデプロイ時は、これらのキー名で環境変数が設定されていることを期待
# ローカル開発時は .streamlit/secrets.toml からも読み込める
JWT_SECRET_KEY = get_config_value("STREAMLIT_JWT_SECRET_KEY")
AUTH_LOGIN_URL = get_config_value("STREAMLIT_AUTH_LOGIN_URL")
EXPECTED_ISSUER = "https://auth-service-agtqjunobq-an.a.run.app" # get_config_value("STREAMLIT_EXPECTED_ISSUER")
EXPECTED_AUDIENCE = get_config_value("STREAMLIT_EXPECTED_AUDIENCE")

# Firebase関連の設定
FIREBASE_SERVICE_ACCOUNT_JSON_STR = get_config_value("FIREBASE_SERVICE_ACCOUNT_JSON_STR")

# GCPプロジェクトIDと許可ユーザーリストのシークレットID (これらも環境変数/secrets.tomlから取得)
GCP_PROJECT_ID = get_config_value("GCP_PROJECT_ID")
SECRET_ID_ALLOWED_EMAILS = get_config_value("SECRET_ID_ALLOWED_EMAILS")

# カスタムモジュールをインポート
import firebase_utils  # Firebase関連処理
import auth_utils      # 認証関連処理
import ui_components   # UI描画関連の関数

# --- ページ設定 (最初のStreamlitコマンドである必要あり) ---
st.set_page_config(page_title="チャットアプリ (モジュール版)", layout="wide")

# --- 必須設定値のチェック ---
missing_configs = []
if not JWT_SECRET_KEY: missing_configs.append("STREAMLIT_JWT_SECRET_KEY (Secret Manager経由で設定)")
if not AUTH_LOGIN_URL: missing_configs.append("STREAMLIT_AUTH_LOGIN_URL")
if not EXPECTED_ISSUER: missing_configs.append("STREAMLIT_EXPECTED_ISSUER")
if not EXPECTED_AUDIENCE: missing_configs.append("STREAMLIT_EXPECTED_AUDIENCE")
if not FIREBASE_SERVICE_ACCOUNT_JSON_STR: missing_configs.append("FIREBASE_SERVICE_ACCOUNT_JSON_STR (Secret Manager経由で設定)")
if not GCP_PROJECT_ID: missing_configs.append("GCP_PROJECT_ID (firebase_utils用)")
if not SECRET_ID_ALLOWED_EMAILS: missing_configs.append("SECRET_ID_ALLOWED_EMAILS (firebase_utils用)")

if missing_configs:
    st.error(f"アプリケーションの起動に必要な設定が不足しています: {', '.join(missing_configs)}。\n"
             "Cloud Runサービスの環境変数またはローカルの.streamlit/secrets.tomlを確認してください。")
    st.stop()

# --- firebase_utils.py など他のモジュールが環境変数を参照できるように設定 ---
# get_config_value で読み込んだ値を os.environ に設定し直すことで、
# 他のモジュールが os.environ.get() で一貫して値を取得できるようにする。
# (ただし、他のモジュールも get_config_value を使うように統一する方がより望ましい)
if GCP_PROJECT_ID: os.environ["GCP_PROJECT_ID"] = GCP_PROJECT_ID
if SECRET_ID_ALLOWED_EMAILS: os.environ["SECRET_ID_ALLOWED_EMAILS"] = SECRET_ID_ALLOWED_EMAILS
if FIREBASE_SERVICE_ACCOUNT_JSON_STR: os.environ["FIREBASE_SERVICE_ACCOUNT_JSON_STR"] = FIREBASE_SERVICE_ACCOUNT_JSON_STR

# --- アプリケーションのメインロジック ---

# 1. Firebase Admin SDKの初期化を試みる (アプリ起動時に一度だけ実行されるようにする)
#    firebase_utils内でst.session_stateを使って初期化済みか管理される
if not firebase_utils.ensure_firebase_initialized():
    # firebase_utils内でst.error()により詳細エラーが表示される想定なので、ここでは簡潔に
    st.error("データベースサービスへの接続に失敗しました。詳細はログを確認してください。")
    print("[DEBUG app.py] Firebase initialization FAILED in app.py. Stopping.") # デバッグログ追加
    st.stop() # 致命的なエラーとしてアプリケーションを停止
print("[DEBUG app.py] Firebase initialization check PASSED in app.py.") # デバッグログ追加

# 2. URLから認証情報を取得 (IdPからのコールバック処理のため)
print("[DEBUG app.py] Attempting to get query params...") # デバッグログ追加
auth_token = auth_utils.get_query_param("auth_token")
auth_error_from_url = auth_utils.get_query_param("auth_error") # IdPからの直接エラー
print(f"[DEBUG app.py] auth_token: {auth_token}, auth_error_from_url: {auth_error_from_url}") # デバッグログ追加

# 3. IdP (認証サーバー) からのエラーコールバック処理
if auth_error_from_url and USER_INFO_KEY not in st.session_state:
    # IdPからのエラーは直接表示し、URLパラメータをクリア
    ui_components.display_auth_error(f"認証サーバーからのエラー: {auth_error_from_url}")
    auth_utils.clear_auth_query_params() # URLから不要なクエリパラメータを削除
    # この後、下のifブロックでログインページが表示される


# 4. ログイン状態の判定とページの表示制御
if USER_INFO_KEY not in st.session_state: # セッションにユーザー情報がない場合（未ログイン状態）
    # 未ログイン時にセッションに認証エラーが残っていれば表示 (トークン検証失敗など)
    # show_login_page 内で AUTH_ERROR_KEY を参照して表示しクリアする
    # なので、ここでは敢えて表示処理を入れなくても良い。

    if auth_token: # IdPからのコールバックでURLにトークンがある場合
        user_payload_from_idp = auth_utils.verify_jwt_token(auth_token) # JWTトークンを検証

        if user_payload_from_idp: # トークン検証成功 or 失敗(エラーはセッションにセットされる)
            # メールアドレス検証とFirebase Authへの登録/カスタムクレーム設定
            is_approved, firebase_uid_or_jwt_sub = auth_utils.process_user_login_and_approval(user_payload_from_idp)

            if is_approved and firebase_uid_or_jwt_sub: # firebase_uid_or_jwt_sub には成功時UIDが入る
                # 承認され、Firebase AuthのUIDも取得できた場合
                st.session_state[USER_INFO_KEY] = user_payload_from_idp # IdPからのペイロードを保存
                st.session_state['firebase_auth_uid'] = firebase_uid_or_jwt_sub # 確実にUID
                auth_utils.clear_auth_query_params() # URLクリーンアップ
                st.rerun() # ログイン成功、チャットページへ (app.pyのelseブロックが処理)
            else:
                # 承認されなかった場合、またはFirebase Auth処理でエラーがあった場合
                # エラーメッセージはセッションにセット済みのはず
                auth_utils.clear_auth_query_params() # エラーでもURLはクリーンアップ
                
                # ★★★ ループを防ぐための修正 ★★★
                # st.rerun() をコメントアウトし、エラーメッセージを表示して停止する
                # auth_utils.logout() # ログアウトするとエラーが見えなくなるので、ここではしない
                
                st.error("ユーザー承認に失敗しました。許可メールリストを確認してください。")
                if AUTH_ERROR_KEY in st.session_state and st.session_state[AUTH_ERROR_KEY]:
                    st.error(f"詳細: {st.session_state[AUTH_ERROR_KEY]}")
                    # del st.session_state[AUTH_ERROR_KEY] # 必要ならエラー表示後にクリア
                
                # ログインページに戻るためのボタンや案内を表示しても良い
                ui_components.show_login_page() # エラーを表示しつつログインページを再表示
                st.stop() # ★★★ スクリプトの実行をここで明示的に停止 ★★★
        else: # トークン検証失敗
            # エラーは verify_jwt_token 内でセッションにセットされているはずなので、
            # ここではURLクリーンアップと再描画のみ行う
            auth_utils.clear_auth_query_params() # 不正なトークンはURLから消す
            st.rerun() # エラーメッセージ表示のために再描画 -> show_login_pageへ (ui_components.show_login_page()がエラー表示)
    else: # 通常の未ログインアクセス (トークンなし)
        ui_components.show_login_page() # ログインページ表示 (内部でエラーも表示)

else: # セッションにユーザー情報がある場合（ログイン済み）
    user_info_data = st.session_state[USER_INFO_KEY]
    firebase_auth_uid = st.session_state.get('firebase_auth_uid')

    # Firebase Authでユーザーが承認済みか最終確認 (カスタムクレームを見る)
    if auth_utils.is_user_approved_in_firebase_auth(firebase_auth_uid):
        ui_components.show_chat_page(user_info_data)
    else:
        # 承認済みでない場合のエラー表示
        ui_components.display_auth_error("チャット機能へのアクセスが承認されていません。")
        if st.button("ログアウト", key="logout_not_approved"): # ログアウトボタンをシンプルに
            auth_utils.logout()

# フッター (共通部分としてapp.pyに記述)
st.markdown("---")
st.markdown("<div style='text-align: center; color: grey; font-size: 0.9em;'>Powered by Streamlit</div>", unsafe_allow_html=True)