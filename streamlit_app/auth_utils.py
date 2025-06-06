# auth_utils.py
import streamlit as st
import jwt
from datetime import datetime, timezone, timedelta
import os
import firebase_admin
from firebase_admin import auth as firebase_auth
import firebase_utils # Firebase初期化と許可メールリスト取得のため

USER_INFO_KEY = "user_info"
AUTH_ERROR_KEY = "auth_error_message"

# JWT関連の設定値は環境変数またはst.secretsから取得
JWT_SECRET_KEY = os.environ.get("STREAMLIT_JWT_SECRET_KEY") or st.secrets.get("STREAMLIT_JWT_SECRET_KEY")
EXPECTED_ISSUER = os.environ.get("STREAMLIT_EXPECTED_ISSUER") or st.secrets.get("STREAMLIT_EXPECTED_ISSUER")
EXPECTED_AUDIENCE = os.environ.get("STREAMLIT_EXPECTED_AUDIENCE") or st.secrets.get("STREAMLIT_EXPECTED_AUDIENCE")
AUTH_LOGIN_URL = os.environ.get("STREAMLIT_AUTH_LOGIN_URL") or st.secrets.get("STREAMLIT_AUTH_LOGIN_URL")

_allowed_emails_cache = None # 許可メールリストのキャッシュ

def get_allowed_emails():
    global _allowed_emails_cache
    if _allowed_emails_cache is None: # まだ読み込んでいなければ
        _allowed_emails_cache = firebase_utils.get_allowed_emails_from_secret_manager()
        if not _allowed_emails_cache: # Secret Managerから取得失敗した場合のフォールバック (任意)
            print("[DEBUG auth_utils] Warning: No allowed emails from Secret Manager, using fallback if defined.")
            # _allowed_emails_cache = ["your_fallback_email@example.com"] # 必要ならフォールバック
    
    # ★★★ デバッグ用: 取得した許可メールリストを画面に表示 ★★★
    # この st.sidebar.expander は、ログインページが表示されているタイミングで実行されることを想定。
    # 実際の運用では削除してください。
    if st.sidebar.checkbox("デバッグ: 許可メールリスト表示", key="debug_show_allowed_emails_auth"):
        st.sidebar.write("取得された許可メールリスト:")
        if _allowed_emails_cache:
            st.sidebar.json(_allowed_emails_cache)
        else:
            st.sidebar.warning("許可メールリストは空または取得できませんでした。")
    return _allowed_emails_cache

def verify_jwt_token(token_string):
    print(f"[DEBUG auth_utils] Verifying JWT token: {token_string[:30]}...") # トークンの一部を表示
    if not JWT_SECRET_KEY or not EXPECTED_AUDIENCE or not EXPECTED_ISSUER:
        st.session_state[AUTH_ERROR_KEY] = "認証設定に問題があります。管理者に連絡してください。" # 具体的なメッセージ
        print(f"[DEBUG auth_utils] JWT settings missing: KEY_SET={not not JWT_SECRET_KEY}, AUD_EXPECTED='{EXPECTED_AUDIENCE}', ISS_EXPECTED='{EXPECTED_ISSUER}'")
        return None
    try:
        payload = jwt.decode(token_string, JWT_SECRET_KEY, algorithms=["HS256"], audience=EXPECTED_AUDIENCE, issuer=EXPECTED_ISSUER, leeway=timedelta(seconds=30))
        print(f"[DEBUG auth_utils] JWT token successfully verified. Payload: {payload}")
        # 検証成功時は、念のため既存のエラーメッセージをクリア
        if AUTH_ERROR_KEY in st.session_state:
            del st.session_state[AUTH_ERROR_KEY]
        return payload
    except jwt.ExpiredSignatureError:
        print("[DEBUG auth_utils] JWT token expired.")
        st.session_state[AUTH_ERROR_KEY] = "認証トークンの発行者が無効です。"
    except jwt.InvalidAudienceError as e:
        print(f"[DEBUG auth_utils] JWT token invalid audience: {e}. Expected: '{EXPECTED_AUDIENCE}'")
        st.session_state[AUTH_ERROR_KEY] = "認証トークンの対象者が無効です。"
    except jwt.InvalidIssuerError as e:
        print(f"[DEBUG auth_utils] JWT token invalid issuer: {e}. Expected: '{EXPECTED_ISSUER}'")
        st.session_state[AUTH_ERROR_KEY] = "認証トークンの発行者が無効です。"
    except jwt.InvalidTokenError as e: # より具体的なJWT関連エラー
        print(f"[DEBUG auth_utils] JWT InvalidTokenError: {e}") # サーバーログには詳細
        st.session_state[AUTH_ERROR_KEY] = "認証トークンが無効です。再度ログインしてください。"
    except Exception as e:
        print(f"[DEBUG auth_utils] JWT Token Verification Error: {e}") # サーバーログには詳細
        st.session_state[AUTH_ERROR_KEY] = "認証トークンの検証中に予期せぬエラーが発生しました。" # 一般的なエラー
    return None

def logout():
    keys_to_delete = [USER_INFO_KEY, AUTH_ERROR_KEY, 'firebase_auth_uid', 'selected_room_id', 'selected_room_name']
    for k in keys_to_delete: st.session_state.pop(k, None)
    try: st.query_params.clear()
    except AttributeError: pass
    st.rerun()

def get_query_param(name):
    try: return st.query_params.get(name)
    except AttributeError: return st.experimental_get_query_params().get(name, [None])[0] if hasattr(st, 'experimental_get_query_params') else None

def clear_auth_query_params():
    try:
        if hasattr(st, 'query_params'):
            current_params = st.query_params.to_dict()
            keys_to_remove = ["auth_token", "auth_error", "code", "state", "scope"]
            cleaned_params = {k: v for k, v in current_params.items() if k not in keys_to_remove}
            if cleaned_params != current_params:
                st.query_params.clear()
                if cleaned_params: st.query_params.from_dict(cleaned_params)
    except AttributeError: pass

def process_user_login_and_approval(jwt_payload):
    # ★★★ Firebase初期化の確実なチェック ★★★
    if not firebase_utils.ensure_firebase_initialized():
        error_msg = "Firebaseサービスへの接続に失敗しました。管理者に連絡してください。"
        st.session_state[AUTH_ERROR_KEY] = error_msg
        # st.error(error_msg) # firebase_utils 側でも表示される可能性があるので重複を避けるか、ここで明確に表示
        print(f"[DEBUG auth_utils] Firebase not initialized in process_user_login_and_approval. Aborting.")
        # st.error("Firebase接続エラー。ユーザー処理を続行できません。") # firebase_utils側で表示
        return False, None

    email = jwt_payload.get("email")
    print(f"[DEBUG auth_utils] Processing login for email: {email}")
    uid_from_jwt = jwt_payload.get("sub") # IdPが発行する一意なID
    display_name = jwt_payload.get("name", email)

    if not email or not uid_from_jwt:
        st.session_state[AUTH_ERROR_KEY] = "認証情報からメールまたはユーザーIDを取得できませんでした。"
        return False, None

    allowed_emails = get_allowed_emails()
    print(f"[DEBUG auth_utils] Allowed emails from get_allowed_emails(): {allowed_emails}")
    
    # ★★★ デバッグ用: メールアドレスと許可リストを画面に表示 ★★★
    if st.sidebar.checkbox("デバッグ: メール照合情報表示", key="debug_show_email_check"):
        st.sidebar.write(f"検証中のメール: {email.lower()}")
        st.sidebar.write(f"許可リスト: {allowed_emails}")
        st.sidebar.write(f"照合結果 (email.lower() in allowed_emails): {email.lower() in allowed_emails}")

    print(f"[DEBUG auth_utils] Allowed emails: {allowed_emails}")
    if not allowed_emails or email.lower() not in allowed_emails: # allowed_emailsが空の場合も考慮
        print(f"[DEBUG auth_utils] Email '{email}' not in allowed list.")
        st.session_state[AUTH_ERROR_KEY] = f"このメールアドレス ({email}) は利用許可されていません。"
        return False, uid_from_jwt # uid_from_jwt は返す（Firebase Authに存在しない可能性）

    try:
        # ... (以降のFirebase Authユーザー作成/更新、カスタムクレーム設定処理は変更なし) ...
        print(f"[DEBUG auth_utils] Attempting to get/create Firebase user with UID: {uid_from_jwt}")
        try:
            firebase_user = firebase_auth.get_user(uid_from_jwt)
            print(f"[DEBUG auth_utils] Found existing Firebase user: {firebase_user.uid}, Email: {firebase_user.email}")
            if firebase_user.email != email or firebase_user.display_name != display_name:
                 firebase_auth.update_user(uid_from_jwt, email=email, display_name=display_name)
                 print(f"[DEBUG auth_utils] Firebase Auth user {uid_from_jwt} updated with new email/name.")
        except firebase_auth.UserNotFoundError:
            print(f"[DEBUG auth_utils] Firebase user not found for UID: {uid_from_jwt}. Creating new user.")
            firebase_user = firebase_auth.create_user(uid=uid_from_jwt, email=email, display_name=display_name, email_verified=True)
            print(f"[DEBUG auth_utils] New Firebase Auth user created: {firebase_user.uid}")

        existing_claims = firebase_user.custom_claims or {}
        print(f"[DEBUG auth_utils] Existing custom claims for {uid_from_jwt}: {existing_claims}")
        if not existing_claims.get('approvedUser'):
            firebase_auth.set_custom_user_claims(uid_from_jwt, {'approvedUser': True})
            print(f"[DEBUG auth_utils] Custom claim 'approvedUser:true' set for {uid_from_jwt}.")
        # ユーザー処理成功時はエラーを消す
        if AUTH_ERROR_KEY in st.session_state:
            del st.session_state[AUTH_ERROR_KEY]
        return True, uid_from_jwt
    except Exception as e:
        st.session_state[AUTH_ERROR_KEY] = "ユーザー情報の処理中にエラーが発生しました。"
        print(f"[DEBUG auth_utils] Error processing Firebase Auth user {uid_from_jwt}: {e}")
        return False, uid_from_jwt # エラー時もuid_from_jwtを返す

def is_user_approved_in_firebase_auth(uid):
    if not uid or not firebase_utils.ensure_firebase_initialized(): return False
    try:
        user = firebase_auth.get_user(uid)
        return user.custom_claims is not None and user.custom_claims.get('approvedUser') is True
    except Exception as e:
        # is_user_approved_in_firebase_auth はエラーメッセージをセットする責任はないが、
        # 呼び出し側でエラーハンドリングが必要な場合は考慮
        print(f"[DEBUG auth_utils] Error checking Firebase Auth user approval for {uid}: {e}")
        return False