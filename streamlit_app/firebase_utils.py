# firebase_utils.py
import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
import os
import json
from google.cloud import secretmanager
from datetime import datetime, timezone, timedelta # timedelta を追加 (format_firestore_timestamp で使用)

# 定数
FIREBASE_INITIALIZED_KEY = "firebase_admin_initialized_utils"
CHAT_ROOM_COLLECTION = "chatRooms"
FIXED_ROOM_ID = "public_chat_room"
MESSAGES_SUBCOLLECTION = "messages"
SERVICE_ACCOUNT_FILE_PATH = "serviceAccountKey.json" # ローカルフォールバック用

import traceback # ★ traceback モジュールをインポート ★
_db = None

def _access_secret_version(project_id, secret_id, version_id="latest"):
    try:
        client = secretmanager.SecretManagerServiceClient()
        name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
        response = client.access_secret_version(request={"name": name})
        return response.payload.data.decode("UTF-8")
    except Exception as e:
        print(f"[DEBUG firebase_utils] Warning: Failed to access Secret Manager ({secret_id}): {e}")
        return None

def _get_service_account_info():
    # 1. 環境変数 FIREBASE_SERVICE_ACCOUNT_JSON_STR (Cloud Buildでセットされる想定)
    sa_json_str_from_env = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON_STR")
    if sa_json_str_from_env:
        print("[DEBUG firebase_utils] Attempting to initialize Firebase from FIREBASE_SERVICE_ACCOUNT_JSON_STR env var.")
        print(f"[DEBUG firebase_utils] Raw FIREBASE_SERVICE_ACCOUNT_JSON_STR (first 100 chars): {sa_json_str_from_env[:100]}")
        try:
            service_account_info = json.loads(sa_json_str_from_env)
            print("[DEBUG firebase_utils] Successfully parsed JSON string from env var.")
            return service_account_info
        except json.JSONDecodeError as e_json:
            print(f"[ERROR firebase_utils] JSONDecodeError in _get_service_account_info: {e_json}")
            print(f"[ERROR firebase_utils] Error details - Position: {e_json.pos}, Line: {e_json.lineno}, Column: {e_json.colno}")
            if sa_json_str_from_env: # エラーの原因となった文字列を出力（長すぎる場合は一部）
                context_start = max(0, e_json.pos - 20)
                context_end = min(len(sa_json_str_from_env), e_json.pos + 20)
                print(f"[ERROR firebase_utils] Problematic JSON context: '{sa_json_str_from_env[context_start:context_end]}'")
            return None
            
    # 2. アプリが直接Secret Managerにアクセス (環境変数でSecret IDを指定)
    gcp_project_id = os.environ.get("GCP_PROJECT_ID")
    secret_id_sa_key = os.environ.get("SECRET_ID_FIREBASE_SA_KEY") # 例: "streamlit-firebase-sa-key"
    if gcp_project_id and secret_id_sa_key:
        payload = _access_secret_version(gcp_project_id, secret_id_sa_key)
        if payload:
            print(f"[DEBUG firebase_utils] Initializing Firebase by directly accessing Secret Manager: {secret_id_sa_key}")
            return json.loads(payload) # `import json` が必要

    # 3. ローカルファイル (最終フォールバック)
    if os.path.exists(SERVICE_ACCOUNT_FILE_PATH):
        print(f"[DEBUG firebase_utils] Initializing Firebase from local file: {SERVICE_ACCOUNT_FILE_PATH}")
        try:
            with open(SERVICE_ACCOUNT_FILE_PATH, 'r', encoding='utf-8') as f: # encodingを明示
                file_content = f.read()
                print(f"--- Content of {SERVICE_ACCOUNT_FILE_PATH} (first 200 chars) ---")
                print(file_content[:200])
                print(f"--- Raw repr of content (first 200 chars) ---")
                print(repr(file_content[:200])) # repr() で特殊文字も表示
                print("--- End of content ---")
                f.seek(0) # ファイルポインタを先頭に戻す
                return json.load(f) # 元の json.load(f) を使う
        except Exception as e:
            print(f"[ERROR firebase_utils] Failed to read or parse local service account file {SERVICE_ACCOUNT_FILE_PATH}: {e}")
            return None
    print("[WARNING firebase_utils] No service account key found from any source.")
    return None

def _initialize_firebase_admin_internal():
    global _db
    # デフォルトアプリが既に存在するか確認
    if firebase_admin._apps and firebase_admin.get_app(): # デフォルトアプリが存在する場合
        if _db is None: # DBクライアントが未取得の場合のみ取得
            _db = firestore.client()
        st.session_state[FIREBASE_INITIALIZED_KEY] = True
        # print("[DEBUG firebase_utils] Firebase Admin SDKは既に初期化済みです。") # 既に初期化済みの場合はログ不要か、より目立たないレベルで
        return True

    # デフォルトアプリが存在しない場合のみ初期化処理を実行
    try:
        print("[DEBUG firebase_utils] Firebase Admin SDKを初期化します...")
        service_account_info = _get_service_account_info()
        if service_account_info:
            print("[DEBUG firebase_utils] Service account info obtained. Creating credential...")
            cred = credentials.Certificate(service_account_info)
            print("[DEBUG firebase_utils] Credential created. Initializing Firebase app...")
            firebase_admin.initialize_app(cred) # ここでエラーが発生する可能性
            _db = firestore.client()
            st.session_state[FIREBASE_INITIALIZED_KEY] = True
            print("[DEBUG firebase_utils] Firebase Admin SDK initialized by firebase_utils.")
            room_ref = _db.collection(CHAT_ROOM_COLLECTION).document(FIXED_ROOM_ID)
            if not room_ref.get().exists:
                room_ref.set({"name": "公開チャットルーム", "createdAt": firestore.SERVER_TIMESTAMP, "lastMessageAt": firestore.SERVER_TIMESTAMP}, merge=True)
                print(f"[DEBUG firebase_utils] Default chat room '{FIXED_ROOM_ID}' ensured by firebase_utils.")
            return True
        else:
            st.error("Firebaseサービスアカウントキー情報を取得できませんでした。")
            st.session_state[FIREBASE_INITIALIZED_KEY] = False # 初期化失敗時はフラグをFalseに
            _db = None
            return False
    except Exception as e:
        # firebase_admin.initialize_app() が既に呼ばれている場合もここに到達する可能性がある
        if "already exists" in str(e).lower():
            print(f"[DEBUG firebase_utils] Firebase Admin SDK初期化試行時に既に存在していました: {e}")
            # この場合は既に初期化されているので、DBクライアントを取得し直す
            if _db is None:
                _db = firestore.client()
            st.session_state[FIREBASE_INITIALIZED_KEY] = True
            return True
        try:
            st.error(f"Firebase Admin SDK初期化失敗(firebase_utils): {e}")
        except Exception: # st.error が Streamlit のコンテキスト外で呼ばれるとエラーになる場合への対処
            print(f"CRITICAL: Firebase Admin SDK初期化失敗(firebase_utils): {e} (Streamlitコンテキスト外の可能性)")
        print(f"[CRITICAL firebase_utils] Full traceback for Firebase init error: {traceback.format_exc()}")
        st.session_state[FIREBASE_INITIALIZED_KEY] = False
        _db = None
        return False

def get_db_client():
    if not st.session_state.get(FIREBASE_INITIALIZED_KEY) or _db is None:
        if not _initialize_firebase_admin_internal():
            return None
    return _db

def ensure_firebase_initialized():
    return get_db_client() is not None

def load_messages_from_firestore(room_id=FIXED_ROOM_ID):
    db = get_db_client()
    if not db: return []
    try:
        messages_ref = db.collection(CHAT_ROOM_COLLECTION).document(room_id).collection(MESSAGES_SUBCOLLECTION).order_by("timestamp", direction=firestore.Query.ASCENDING).limit(100)
        docs = messages_ref.stream()
        messages = []
        for doc in docs:
            msg_data = doc.to_dict()
            msg_data['id'] = doc.id
            if 'timestamp' in msg_data and hasattr(msg_data['timestamp'], 'to_datetime'):
                 msg_data['timestamp_datetime'] = msg_data['timestamp'].to_datetime(timezone.utc)
            messages.append(msg_data)
        return messages
    except Exception as e:
        st.error(f"Firestoreメッセージ読み込みエラー: {e}")
        return []

def save_message_to_firestore(sender_id, sender_name, text, room_id=FIXED_ROOM_ID):
    db = get_db_client()
    if not db: return False
    try:
        messages_ref = db.collection(CHAT_ROOM_COLLECTION).document(room_id).collection(MESSAGES_SUBCOLLECTION)
        message_data = {"senderId": sender_id, "senderName": sender_name, "text": text, "timestamp": firestore.SERVER_TIMESTAMP}
        messages_ref.add(message_data)
        room_ref = db.collection(CHAT_ROOM_COLLECTION).document(room_id)
        room_ref.update({"lastMessageAt": firestore.SERVER_TIMESTAMP})
        return True
    except Exception as e:
        st.error(f"Firestoreメッセージ保存エラー: {e}")
        return False

def get_allowed_emails_from_secret_manager():
    """Secret Managerから許可されたメールアドレスのリスト(JSON文字列)を取得しパースする"""
    gcp_project_id = "my-auth-project-459900" # os.environ.get("GCP_PROJECT_ID") # 例: 
    secret_id_allowed_emails = os.environ.get("SECRET_ID_ALLOWED_EMAILS") # "tan0ry02024@gmail.com" # 環境変数からシークレットIDの文字列を取得
    print(f"[DEBUG firebase_utils] Attempting to get allowed emails. Project ID: {gcp_project_id}, Secret ID for emails: {secret_id_allowed_emails}")
    if gcp_project_id and secret_id_allowed_emails:
        payload_str = _access_secret_version(gcp_project_id, secret_id_allowed_emails)
        print(f"[DEBUG firebase_utils] Payload from Secret Manager for allowed emails ({secret_id_allowed_emails}): {payload_str}")
        if payload_str:
            try:
                allowed_list = json.loads(payload_str) # JSON配列文字列をPythonリストに
                if isinstance(allowed_list, list):
                    print(f"[DEBUG firebase_utils] Successfully parsed {len(allowed_list)} allowed emails from Secret Manager ({secret_id_allowed_emails}): {allowed_list}")
                    return [email.lower() for email in allowed_list] # 小文字で統一
            except json.JSONDecodeError as e_json:
                print(f"[DEBUG firebase_utils] JSONDecodeError for allowed emails ({secret_id_allowed_emails}): {e_json}")
                st.error(f"許可メールリストのJSON形式エラー ({secret_id_allowed_emails}): {e_json}")
            except Exception as e:
                print(f"[DEBUG firebase_utils] Error parsing allowed emails ({secret_id_allowed_emails}): {e}")
                st.error(f"許可メールリスト取得中のエラー ({secret_id_allowed_emails}): {e}")
    st.warning("許可メールリストをSecret Managerから取得できませんでした。環境変数 GCP_PROJECT_ID と SECRET_ID_ALLOWED_EMAILS を確認してください。")
    return [] # 取得失敗時は空リスト

def format_firestore_timestamp(timestamp_obj, default_str="時刻不明"):
    """FirestoreのTimestampオブジェクトまたはdatetimeオブジェクトをJSTの文字列にフォーマットする"""
    if not timestamp_obj:
        return default_str
    try:
        # Firestore SDK v2+ では timestamp_obj は Python の datetime オブジェクト (UTC)
        if isinstance(timestamp_obj, datetime):
            # タイムゾーン情報がない場合はUTCとみなし、JSTに変換
            if timestamp_obj.tzinfo is None:
                dt_obj = timestamp_obj.replace(tzinfo=timezone.utc).astimezone(timezone(timedelta(hours=9)))
            else: # タイムゾーン情報がある場合は、それを元にJSTへ変換
                dt_obj = timestamp_obj.astimezone(timezone(timedelta(hours=9)))
        else: # datetimeオブジェクトでない場合は、そのまま文字列として返す
            return str(timestamp_obj)
        return dt_obj.strftime('%m/%d %H:%M')
    except Exception as e:
        print(f"[DEBUG firebase_utils] Error formatting timestamp '{timestamp_obj}': {e}")
        return str(timestamp_obj) # エラー時もフォールバック