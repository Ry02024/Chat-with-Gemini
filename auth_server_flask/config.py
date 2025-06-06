import os
from dotenv import load_dotenv

# Load .env file at the very beginning if it exists
load_dotenv()
print("DEBUG config.py: dotenv loaded (if .env exists)")
import json # ★ json モジュールをインポート ★

# --- グローバル設定値 (configモジュールの属性として管理) ---
GCP_PROJECT_ID = None
GOOGLE_CLIENT_ID = None
GOOGLE_CLIENT_SECRET = None
JWT_SECRET_KEY = None
STREAMLIT_APP_URL = None
FUNCTION_BASE_URL = None # このサービス自身のベースURL
REDIRECT_URI = None      # FUNCTION_BASE_URL から構築
ALLOWED_USERS_LIST = []
ENV_TYPE = os.environ.get("ENV", "prod").lower() # 初期値。initialize_app_configsで上書き可能性あり
secret_manager_client = None # SecretManagerServiceクライアント

# アプリケーション初期化済みフラグ
_app_configs_initialized = False

print(f"DEBUG config.py: Initial ENV_TYPE: {ENV_TYPE}")
print(f"DEBUG config.py: Initial GCP_PROJECT_ID from env: {os.environ.get('GCP_PROJECT')}")

# --- ヘルパー関数: Secret Managerから値を取得 ---
def get_secret_from_sm(secret_name_on_sm):
    global GCP_PROJECT_ID, secret_manager_client # これらは initialize_app_configs で設定される
    if not secret_name_on_sm:
        print(f"DEBUG get_secret_from_sm: Secret name not provided for SM access.")
        return None
    if not GCP_PROJECT_ID:
        print(f"エラー (get_secret_from_sm): GCP_PROJECT_ID is not set. Cannot fetch '{secret_name_on_sm}'.")
        return None
    if not secret_manager_client:
        # 通常、initialize_app_configs でクライアントは初期化されているはず
        # ここで再度初期化を試みるか、エラーとするかは設計次第
        # 今回はエラーとして、呼び出し元で適切に処理することを期待
        print(f"エラー (get_secret_from_sm): Secret Manager client not initialized. Cannot fetch '{secret_name_on_sm}'.")
        return None
    try:
        name = f"projects/{GCP_PROJECT_ID}/secrets/{secret_name_on_sm}/versions/latest"
        response = secret_manager_client.access_secret_version(request={"name": name})
        value = response.payload.data.decode("UTF-8").strip()
        print(f"DEBUG: Secret Managerから '{secret_name_on_sm}' を取得成功。")
        return value
    except Exception as e:
        print(f"SMからの取得失敗 ('{secret_name_on_sm}'): {e}")
        return None

# 設定値のサマリーをログ出力するヘルパー関数
def print_config_summary(stage_name=""):
    print(f"--- Config Summary ({stage_name}) ---")
    print(f"  ENV_TYPE: {ENV_TYPE}")
    print(f"  GCP_PROJECT_ID: {GCP_PROJECT_ID}")
    print(f"  GOOGLE_CLIENT_ID: {'Set' if GOOGLE_CLIENT_ID else 'Not Set'}")
    print(f"  FUNCTION_BASE_URL: {FUNCTION_BASE_URL}")
    print(f"  REDIRECT_URI: {REDIRECT_URI}")
    print(f"  STREAMLIT_APP_URL: {STREAMLIT_APP_URL}")
    print(f"  ALLOWED_USERS_LIST: {ALLOWED_USERS_LIST}") # allowed_users_list_str ではなく ALLOWED_USERS_LIST
    print(f"---------------------------------")
# --- 設定値の初期化関数 ---
def initialize_app_configs(mode_from_arg=None):
    global GCP_PROJECT_ID, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, JWT_SECRET_KEY
    global STREAMLIT_APP_URL, FUNCTION_BASE_URL, REDIRECT_URI, ALLOWED_USERS_LIST
    global secret_manager_client, ENV_TYPE
    global _app_configs_initialized

    # allowed_users_list_json_str を関数の最初で初期化
    allowed_users_list_json_str = None # ★ 変数名を json_str に変更して区別しやすくする ★

    if _app_configs_initialized and not mode_from_arg: # 既に初期化済みで、強制的なモード指定がない場合はスキップ
        print("DEBUG initialize_app_configs: Already initialized. Skipping.")
        return

    print("DEBUG: initialize_app_configs CALLED")

    # mode_from_arg があれば ENV_TYPE を上書き
    # os.environ.get("ENV_ARG") はローカル実行時の引数から来る想定
    if mode_from_arg:
        ENV_TYPE = mode_from_arg.lower()
    else:
        ENV_TYPE = os.environ.get("ENV", "prod").lower() # デフォルトは 'prod'

    GCP_PROJECT_ID = os.environ.get('GCP_PROJECT')

    print(f"DEBUG initialize_app_configs: Effective ENV_TYPE = {ENV_TYPE}")
    print(f"DEBUG initialize_app_configs: Effective GCP_PROJECT_ID = {GCP_PROJECT_ID}")

    if ENV_TYPE == 'local_direct':
        print("DEBUG: 'local_direct' モード: .env から直接値を読み込みます。")
        GOOGLE_CLIENT_ID = os.environ.get("DIRECT_GOOGLE_CLIENT_ID")
        GOOGLE_CLIENT_SECRET = os.environ.get("DIRECT_GOOGLE_CLIENT_SECRET")
        JWT_SECRET_KEY = os.environ.get("DIRECT_JWT_SECRET_KEY")
        STREAMLIT_APP_URL = os.environ.get("DIRECT_STREAMLIT_APP_URL")
        FUNCTION_BASE_URL = os.environ.get("DIRECT_FUNCTION_BASE_URL")
        allowed_users_list_json_str = os.environ.get("DIRECT_ALLOWED_USERS_LIST_JSON_STR") # ★ _JSON_STR を付けるなどして区別 ★
    elif ENV_TYPE == 'local_sm_test' or ENV_TYPE == 'prod':
        print(f"DEBUG: '{ENV_TYPE}' モード: Secret Manager を利用します。")
        if not GCP_PROJECT_ID:
            raise ValueError(f"'{ENV_TYPE}' モードではGCP_PROJECT環境変数の設定が必須です。")

        # Secret Managerクライアントの初期化 (必要な場合のみ)
        if not secret_manager_client:
            try:
                from google.cloud import secretmanager
                secret_manager_client = secretmanager.SecretManagerServiceClient()
                print("DEBUG: Secret Managerクライアントを初期化しました。")
            except ImportError:
                raise RuntimeError("google-cloud-secret-managerライブラリが見つかりません。pip install google-cloud-secret-manager を実行してください。")
            except Exception as e:
                raise RuntimeError(f"Secret Managerクライアントの初期化に失敗: {e}")
        else:
            print("DEBUG: Secret Managerクライアントは既に初期化済みです。")

        # SM上のシークレット名を取得するための環境変数キーのプレフィックス
        sm_prefix = "SM_NAME_FOR_"

        # 各設定値に対応するSM名を環境変数から取得、なければデフォルト値を使用
        # (デフォルト値は本番用とローカルテスト用で分岐)
        default_suffix = "_PROD_SM"

        sm_gcid = os.environ.get(f"{sm_prefix}GOOGLE_CLIENT_ID", f"GOOGLE_CLIENT_ID{default_suffix}")
        sm_gc_secret = os.environ.get(f"{sm_prefix}GOOGLE_CLIENT_SECRET", f"GOOGLE_CLIENT_SECRET{default_suffix}")
        sm_jwt_key = os.environ.get(f"{sm_prefix}JWT_SECRET_KEY", f"JWT_SECRET_KEY{default_suffix}")
        sm_allowed_list = os.environ.get(f"{sm_prefix}ALLOWED_USERS_LIST", f"ALLOWED_USERS_LIST{default_suffix}")
        sm_streamlit_url = os.environ.get(f"{sm_prefix}STREAMLIT_APP_URL", f"STREAMLIT_APP_URL{default_suffix}")
        sm_function_base_url = os.environ.get(f"{sm_prefix}FUNCTION_BASE_URL", f"FUNCTION_BASE_URL{default_suffix}")
        # CALLBACK_URI は FUNCTION_BASE_URL から動的に生成するため、専用のSM名は不要

        print(f"DEBUG: SM名解決: GCID='{sm_gcid}', SECRET='{sm_gc_secret}', JWT='{sm_jwt_key}', ALLOWED='{sm_allowed_list}', S_URL='{sm_streamlit_url}', F_URL='{sm_function_base_url}'")

        # Secret Managerから実際の値を取得
        GOOGLE_CLIENT_ID = get_secret_from_sm(sm_gcid)
        GOOGLE_CLIENT_SECRET = get_secret_from_sm(sm_gc_secret)
        JWT_SECRET_KEY = get_secret_from_sm(sm_jwt_key)
        STREAMLIT_APP_URL = get_secret_from_sm(sm_streamlit_url)
        FUNCTION_BASE_URL = get_secret_from_sm(sm_function_base_url)
        allowed_users_list_json_str = get_secret_from_sm(sm_allowed_list)

        # local_sm_test モードの場合のローカル用URL上書き
        if ENV_TYPE == 'local_sm_test':
            print("DEBUG: local_sm_test mode. Overriding URLs for local testing.")
            FUNCTION_BASE_URL = "http://localhost:8080"
            # REDIRECT_URI はこの後の FUNCTION_BASE_URL からの生成に任せる
            STREAMLIT_APP_URL = "http://localhost:8501"
            # ALLOWED_USERS_LIST はSMから読み込んだものを使うか、ここで上書きも可能
            # allowed_users_list_json_str がSMから読み込めなかった場合は None のまま
    else:
        raise ValueError(f"無効なENVタイプが指定されました: '{ENV_TYPE}'。'local_direct', 'local_sm_test', 'prod' のいずれかである必要があります。")

    # REDIRECT_URI の設定
    if FUNCTION_BASE_URL:
        REDIRECT_URI = f"{FUNCTION_BASE_URL.rstrip('/')}/auth_callback"
    else:
        REDIRECT_URI = None # FUNCTION_BASE_URLがない場合はNone

    # ★★★ ALLOWED_USERS_LIST の設定部分を修正 ★★★
    if allowed_users_list_json_str:
        try:
            parsed_list = json.loads(allowed_users_list_json_str) # JSONとしてパース
            if isinstance(parsed_list, list):
                # 各要素が文字列であることを期待し、前後の空白を除去し、小文字に統一
                ALLOWED_USERS_LIST = [
                    str(email).strip().lower() 
                    for email in parsed_list 
                    if isinstance(email, str) and str(email).strip()
                ]
                print(f"DEBUG initialize_app_configs: Successfully parsed ALLOWED_USERS_LIST: {ALLOWED_USERS_LIST}")
            else:
                print(f"警告: Secret Managerから取得した許可ユーザーリストがJSON配列ではありません。値: {parsed_list}")
                ALLOWED_USERS_LIST = [] # パース失敗時は空リスト
        except json.JSONDecodeError as e:
            print(f"警告: Secret Managerからの許可ユーザーリストのJSONパースに失敗しました: {e}。取得した文字列: '{allowed_users_list_json_str}'")
            ALLOWED_USERS_LIST = [] # パース失敗時は空リスト
    else:
        ALLOWED_USERS_LIST = [] # デフォルトは空リスト
        print(f"警告: 許可ユーザーリストの元となる文字列(allowed_users_list_json_str)が設定/取得されていません。ALLOWED_USERS_LISTは空になります。")

    # 必須設定値のチェック
    required_vars = {
        "GOOGLE_CLIENT_ID": GOOGLE_CLIENT_ID,
        "GOOGLE_CLIENT_SECRET": GOOGLE_CLIENT_SECRET,
        "JWT_SECRET_KEY": JWT_SECRET_KEY,
        "STREAMLIT_APP_URL": STREAMLIT_APP_URL,
        "FUNCTION_BASE_URL": FUNCTION_BASE_URL,
        "REDIRECT_URI": REDIRECT_URI, # FUNCTION_BASE_URLから生成されるが、これも必須
    }
    missing = [k for k, v in required_vars.items() if not v]
    if missing:
        raise ValueError(f"必須設定値が不足しています: {', '.join(missing)}。 (現在のENV_TYPE: '{ENV_TYPE}')")

    print_config_summary("final values after initialize_app_configs")
    _app_configs_initialized = True
    print("DEBUG: initialize_app_configs COMPLETE")

def are_configs_initialized():
    """設定が初期化されたかどうかを確認する"""
    return _app_configs_initialized
# --- モジュールロード時の初期化試行 ---
# Cloud Functionsのような環境では、モジュールがロードされた時点で初期化が必要
# ただし、ローカル実行時 (`if __name__ == '__main__':`) は引数でモードを指定できるため、
# ここでの呼び出しはデフォルトのENVを参照する。
# initialize_app_configs の中で、引数なしで呼び出された場合の ENV_TYPE の解決ロジックに依存。
# try:
#     print("DEBUG config.py: Attempting initial configuration load (module scope)...")
#     initialize_app_configs() # ← これをコメントアウトまたは削除
# except Exception as e:
#     print(f"CRITICAL (config.py module scope init): 設定の初期読み込みに失敗しました: {e}")