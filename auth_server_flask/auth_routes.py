# auth_server_flask/auth_routes.py

from flask import Blueprint, redirect, request, make_response, url_for # url_for を先頭に追加
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request as GoogleAuthRequest

# 同じディレクトリ内のモジュールをインポート (相対インポート推奨)
import config
import auth_utils

# Blueprintオブジェクトを作成
auth_bp = Blueprint('auth', __name__, url_prefix='/auth') # Blueprint名を 'auth' に変更

# 定数
SCOPES = ['openid', 'https://www.googleapis.com/auth/userinfo.email', 'https://www.googleapis.com/auth/userinfo.profile']
STATE_COOKIE_NAME = "myappstate"

# --- ルートパス '/' のハンドラは main.py に残すか、別のBlueprintにするのが一般的 ---
# もしこのファイルで /auth/ というパスのルートを作りたいなら以下のようにする
# @auth_bp.route('/')
# def auth_index():
#     login_url = url_for('auth.login') # 'auth.login' を使用
#     return f'This is the /auth/ index. Go to <a href="{login_url}">Login</a>.'

@auth_bp.route('/login', methods=['GET'])
def login(): # 関数名
    print("\n--- /auth/login accessed (via auth_routes.py) ---")
    # ... (以降の login 関数の内容は変更なし) ...
    if not all([config.GOOGLE_CLIENT_ID, config.GOOGLE_CLIENT_SECRET, config.REDIRECT_URI, SCOPES]):
        print("エラー: OAuth設定不完全(login)。 configの値を確認してください。")
        return "サーバー設定エラー (OAuth設定不備)", 500
    client_config_dict = {
        "web": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "project_id": config.GCP_PROJECT_ID,
            "redirect_uris": [config.REDIRECT_URI]
        }
    }
    try:
        flow = Flow.from_client_config(
            client_config=client_config_dict,
            scopes=SCOPES,
            redirect_uri=config.REDIRECT_URI
        )
    except Exception as e:
        print(f"Flowオブジェクトの初期化に失敗: {e}")
        return "OAuthフロー設定エラー", 500
    oauth_state_param = auth_utils.generate_oauth_state_parameter()
    print(f"DEBUG auth_routes/login: Generated OAuth state: {oauth_state_param}")
    try:
        authorization_url, state_passed_to_google = flow.authorization_url(
            access_type='offline',
            state=oauth_state_param,
            prompt='consent'
        )
    except Exception as e:
        print(f"認証URLの生成に失敗: {e}")
        return "認証URL生成エラー", 500
    print(f"DEBUG auth_routes/login: REDIRECT_URI configured for Google: {config.REDIRECT_URI}")
    print(f"DEBUG auth_routes/login: Authorization URL (first 100 chars): {authorization_url[:100]}")
    response = make_response(redirect(authorization_url))
    is_secure_cookie = (config.ENV_TYPE == 'prod')
    cookie_path = '/'
    response.set_cookie(
        STATE_COOKIE_NAME,
        oauth_state_param,
        max_age=600,
        httponly=True,
        secure=is_secure_cookie,
        samesite='Lax',
        path=cookie_path
    )
    print(f"DEBUG auth_routes/login: State '{oauth_state_param}' set to Cookie '{STATE_COOKIE_NAME}' (secure={is_secure_cookie}, path='{cookie_path}'). Redirecting to Google.")
    return response


@auth_bp.route('/callback', methods=['GET'])
def callback():
    print("\n--- /auth/callback accessed (via auth_routes.py) ---")
    # ... (以降の callback 関数の内容は変更なし、ただし user_email, user_name のスコープに注意) ...
    # (前の回答で示した callback 関数の全コードをここに配置)
    print(f"Callback: Query Args: {request.args.to_dict()}")
    returned_state = request.args.get('state')
    code = request.args.get('code')
    error = request.args.get('error')
    is_secure_cookie = (config.ENV_TYPE == 'prod')
    if error:
        print(f"Callback Error from Google: {error}")
        return f"Google認証エラー: {error}", 400
    if not code:
        print("Callback Error: No authorization code provided by Google.")
        return "Googleから認証コードが提供されませんでした。", 400
    original_state = request.cookies.get(STATE_COOKIE_NAME)
    if not original_state:
        print("Callback Error: State Cookie not found. Session might be invalid or expired.")
        return "セッション情報が無効です (State Cookie が見つかりません)。", 400
    if returned_state != original_state:
        print("Callback Error: State mismatch. Possible CSRF attack.")
        response_csrf_error = make_response("不正なリクエストです (CSRFの可能性)。", 400)
        response_csrf_error.delete_cookie(STATE_COOKIE_NAME, path='/', secure=is_secure_cookie, httponly=True, samesite='Lax')
        return response_csrf_error
    print("Callback: State validation successful.")
    client_config_dict_cb = {
        "web": {
            "client_id": config.GOOGLE_CLIENT_ID,
            "client_secret": config.GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "project_id": config.GCP_PROJECT_ID,
            "redirect_uris": [config.REDIRECT_URI]
        }
    }
    try:
        flow = Flow.from_client_config(
            client_config=client_config_dict_cb,
            scopes=SCOPES,
            state=returned_state
        )
        flow.redirect_uri = config.REDIRECT_URI
        flow.fetch_token(code=code)
        credentials = flow.credentials
        if not credentials or not credentials.id_token:
            print("Callback Error: Failed to obtain ID token from credentials.")
            raise Exception("IDトークンが取得できませんでした。")
        print(f"Callback: Token fetch successful. ID Token (first 30 chars): {credentials.id_token[:30]}...")
    except Exception as e:
        print(f"Callback Error: Token fetch failed: {e}")
        response_token_error = make_response(f"トークンの取得に失敗しました: {e}", 500)
        response_token_error.delete_cookie(STATE_COOKIE_NAME, path='/', secure=is_secure_cookie, httponly=True, samesite='Lax')
        return response_token_error
    try:
        id_info = id_token.verify_oauth2_token(
            credentials.id_token,
            GoogleAuthRequest(),
            config.GOOGLE_CLIENT_ID
        )
        user_email = id_info.get("email") # この変数は try ブロック内でのみ有効
        user_name = id_info.get("name", user_email) # この変数も try ブロック内でのみ有効
        print(f"Callback: ID token verification successful. Email:'{user_email}', Name:'{user_name}'")
        if config.ALLOWED_USERS_LIST and user_email not in config.ALLOWED_USERS_LIST:
            print(f"Callback Warn: User '{user_email}' is not in ALLOWED_USERS_LIST.")
            error_redirect_url = f"{config.STREAMLIT_APP_URL}?auth_error=unauthorized_user&email={user_email}"
            response_unauthorized = make_response(redirect(error_redirect_url))
            response_unauthorized.delete_cookie(STATE_COOKIE_NAME, path='/', secure=is_secure_cookie, httponly=True, samesite='Lax')
            return response_unauthorized
        print(f"Callback Info: User '{user_email}' is allowed. Generating custom JWT.")
        # user_email と user_name はこの try ブロックのスコープなので、JWT生成もここで行う
        try:
            jwt_token = auth_utils.create_custom_jwt(
                user_email=user_email,
                user_name=user_name,
                issuer_url=config.FUNCTION_BASE_URL,
                audience_url=config.STREAMLIT_APP_URL,
                jwt_secret_key=config.JWT_SECRET_KEY
            )
        except Exception as e_jwt: # 別の変数名でエラーをキャッチ
            print(f"Callback Error: Custom JWT generation failed: {e_jwt}")
            response_jwt_error = make_response(f"セッショントークンの生成に失敗しました: {e_jwt}", 500)
            response_jwt_error.delete_cookie(STATE_COOKIE_NAME, path='/', secure=is_secure_cookie, httponly=True, samesite='Lax')
            return response_jwt_error
    except Exception as e_id_verify: # 別の変数名でエラーをキャッチ
        print(f"Callback Error: ID token verification or access control failed: {e_id_verify}")
        response_id_error = make_response(f"ユーザー情報の検証に失敗しました: {e_id_verify}", 500)
        response_id_error.delete_cookie(STATE_COOKIE_NAME, path='/', secure=is_secure_cookie, httponly=True, samesite='Lax')
        return response_id_error

    # jwt_token が try ブロック内で定義されるため、スコープ外に出すか、リダイレクト処理も try ブロック内に移動
    # ここでは JWT 生成が成功した場合のみリダイレクトに進むように try ブロック内に含める
    # (上記の try ブロックの最後の方に JWT 生成とリダイレクトを配置済みなので、このコメントは整理用)

    target_url_with_token = f"{config.STREAMLIT_APP_URL}?auth_token={jwt_token}" # jwt_token は上の try ブロック内で定義されている
    response_final = make_response(redirect(target_url_with_token))
    response_final.delete_cookie(STATE_COOKIE_NAME, path='/', secure=is_secure_cookie, httponly=True, samesite='Lax')
    print(f"DEBUG auth_routes/callback: Redirecting to Streamlit App with auth_token ...")
    return response_final