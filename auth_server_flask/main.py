# auth_server_flask/main.py

import os
import argparse
from flask import Flask, make_response, request, redirect, url_for # ★ make_response を追加 ★
# request, make_response, redirect は auth_handlers で使うので main.py からは不要になることが多い

# ★★★ functions_framework を再度インポート ★★★
import functions_framework

# 設定モジュールと新しいハンドラモジュールをインポート
# (相対インポートがエラーになる場合は、 import config のようにする)
import config
import auth_handlers

# Flaskアプリケーションインスタンス
app = Flask(__name__)

# --- Flaskルート定義 ---
@app.route('/')
def root_path_handler():
    print("--- / (root) accessed ---")
    # ログインページへのリンク (今回は /auth_login を直接指定、または url_for を使う)
    # from flask import url_for
    # login_url = url_for('auth_login_route') # 関数名を指定
    # return f'Authentication Service. Please go to <a href="{login_url}">Login</a> to start.', 200
    return 'Authentication Service. Please go to <a href="/auth_login">Login</a> to start.', 200

@app.route('/auth_login', methods=['GET'])
def auth_login_route():
    return auth_handlers.handle_auth_login()

@app.route('/auth_callback', methods=['GET'])
def auth_callback_route():
    return auth_handlers.handle_auth_callback()

TEST_COOKIE_NAME_SIMPLE = "SimpleTestCookie"

@app.route('/simple_set')
def simple_set_cookie_route():
# main.py の simple_set_cookie_route 関数内
# main.py の simple_set_cookie_route 関数内
    cookie_value_partitioned = "PartitionedNoneSecureValueABC"  # 値を変更
    resp = make_response(f"PartitionedNoneSecureCookie set. Go to /simple_get (or check SimpleTestCookie in dev tools with Partitioned)")
    
    print(f"DEBUG /simple_set: Setting cookie 'SimpleTestCookie' with value '{cookie_value_partitioned}', Secure=True, SameSite='None', Partitioned=True")
    resp.set_cookie(
        "SimpleTestCookie", # Cookie名は同じでも良い
        cookie_value_partitioned,
        path='/',
        secure=True,
        samesite='None',
        partitioned=True  # ★ Partitioned=True を追加 ★
    )
    print(f"DEBUG /simple_set: Response headers for PartitionedNoneSecureCookie: {resp.headers.getlist('Set-Cookie')}")
    return resp

@app.route('/simple_get')
def simple_get_cookie_route():
    cookie_value = request.cookies.get(TEST_COOKIE_NAME_SIMPLE)
    print(f"DEBUG /simple_get: All Cookies received: {request.cookies}")
    if cookie_value:
        print(f"DEBUG /simple_get: SUCCESS! Cookie '{TEST_COOKIE_NAME_SIMPLE}' received with value: '{cookie_value}'")
        return f"SUCCESS! Cookie '{TEST_COOKIE_NAME_SIMPLE}' received: {cookie_value}", 200
    else:
        print(f"ERROR /simple_get: Cookie '{TEST_COOKIE_NAME_SIMPLE}' NOT received.")
        return f"ERROR! Cookie '{TEST_COOKIE_NAME_SIMPLE}' NOT received.", 400

# ★★★ Cloud Functionsエントリーポイントを元に戻す ★★★
@functions_framework.http
def auth_http(request_cf):
    """ HTTP Cloud Function.
    Args:
        request_cf (flask.Request): The request object.
        <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>
    Returns:
        The response text, or any set of values URL_PATH can return,
        <https://flask.palletsprojects.com/en/1.1.x/api/#response-objects>
    """
    # Cloud Functions インスタンス起動時/リクエスト処理前に必ず設定を初期化
    try:
        print("DEBUG (auth_http entry): Ensuring configs are initialized for Cloud Function.")
        current_env_mode = os.environ.get("ENV", "prod") # デフォルトは prod
        
        # config.py が os.environ.get('GCP_PROJECT') を読むので、
        # GCP_PROJECT 環境変数はCloud Buildの --set-env-vars で設定されているはず
        config.initialize_app_configs(mode_from_arg=current_env_mode)

        # 必須設定値の簡単なチェック
        if not all([config.GOOGLE_CLIENT_ID, config.REDIRECT_URI]): # 最低限のチェック
            print("CRITICAL (auth_http): Core configurations are missing after init attempt.")
            # エラーレスポンスを返すか、ログに詳細を残してFlaskに処理を任せる
            # ここでエラーを返すと、Flaskのルート処理に進まない
            return "Server configuration error: Core configurations missing.", 500

    except Exception as e:
        print(f"CRITICAL (auth_http entry): Failed to initialize configs: {e}")
        return "Server configuration error during request processing.", 500

    with app.request_context(request_cf.environ):
        return app.full_dispatch_request()
    
# --- スクリプトとして直接実行された場合の処理 (ローカル開発用) ---
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Flask OAuth Authentication Server (Local)")
    parser.add_argument(
        "--mode",
        type=str,
        choices=['local_direct', 'local_sm_test', 'prod'], # prod はローカルでは通常使わない
        default=os.environ.get("ENV_ARG", os.environ.get("ENV", "local_direct")).lower(),
        help="動作モード (例: local_direct, local_sm_test)"
    )
    args = parser.parse_args()

    try:
        print(f"DEBUG __main__: Initializing configs with mode: {args.mode}")
        config.initialize_app_configs(args.mode)
    except ValueError as e:
        print(f"設定エラー: {e}")
        exit(1)
    except RuntimeError as e:
        print(f"ランタイムエラー: {e}")
        exit(1)
    except Exception as e:
        print(f"予期せぬ初期化エラー: {e}")
        exit(1)

    # 起動前チェック
    if not all([config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET, config.JWT_SECRET_KEY,
                config.STREAMLIT_APP_URL, config.FUNCTION_BASE_URL, config.REDIRECT_URI]):
        print("エラー: Flaskアプリの起動に必要な設定が完了していません。")
        exit(1)
    else:
        print(f"\n--- Local server starting (Mode: {config.ENV_TYPE}) ---")
        print(f"Auth Login URL: http://localhost:8080/auth_login")
        print(f"Callback URL configured for Google (REDIRECT_URI): {config.REDIRECT_URI}")
        print(f"Streamlit App URL (STREAMLIT_APP_URL for JWT 'aud'): {config.STREAMLIT_APP_URL}")
        print(f"Function Base URL (FUNCTION_BASE_URL for JWT 'iss'): {config.FUNCTION_BASE_URL}")
        app.run(host='0.0.0.0', port=8080, debug=True, use_reloader=False)