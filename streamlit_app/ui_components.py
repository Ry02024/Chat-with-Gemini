# ui_components.py
import streamlit as st
from datetime import datetime, timezone, timedelta
import firebase_utils
import auth_utils

USER_INFO_KEY = "user_info"
AUTH_ERROR_KEY = "auth_error_message"

def display_auth_error(error_message_to_display=None): # デフォルト引数をNoneに変更
    """
    認証エラーメッセージを表示する。
    セッションにエラーがあればそれを表示しクリアする。
    引数で直接メッセージが渡された場合はそれを表示する。
    """
    message = None
    if error_message_to_display: # 引数でメッセージが指定された場合
        message = error_message_to_display
    elif AUTH_ERROR_KEY in st.session_state and st.session_state[AUTH_ERROR_KEY]:
        # セッションにエラーメッセージがあれば取得
        message = st.session_state[AUTH_ERROR_KEY]
        del st.session_state[AUTH_ERROR_KEY] # 表示したらクリア

    if message: # 表示すべきメッセージがあれば表示
        st.error(message)

def show_login_page():
    st.title("チャットアプリへようこそ")
    st.info("続行するにはログインしてください。")
    display_auth_error() # ★引数なしで呼び、セッションのエラーを表示

    login_url = auth_utils.AUTH_LOGIN_URL
    if login_url:
        if hasattr(st, 'link_button'):
            st.link_button("Googleアカウントでログイン", login_url, type="primary", use_container_width=True)
        else:
            st.markdown(f'<a href="{login_url}" target="_self" style="padding:0.5em 1em; background-color:red; color:white; border-radius:5px; text-decoration:none;">Googleアカウントでログイン</a>', unsafe_allow_html=True)
    else:
        st.error("ログインURLが設定されていません。")

def show_chat_page(user_info):
    loaded_chat_log = firebase_utils.load_messages_from_firestore()
    db_client = firebase_utils.get_db_client()
    room_name = "チャットルーム"
    if db_client:
        room_doc = db_client.collection(firebase_utils.CHAT_ROOM_COLLECTION).document(firebase_utils.FIXED_ROOM_ID).get()
        if room_doc.exists:
            room_name = room_doc.to_dict().get('name', 'チャットルーム')

    st.title(f"💬 {room_name}")
    current_user_name = user_info.get('name', 'あなた')
    current_user_id = st.session_state.get('firebase_auth_uid')

    if not current_user_id:
        st.error("ユーザーID不明。再ログインしてください。")
        auth_utils.logout(); st.stop()

    with st.sidebar:
        st.subheader("👤 ユーザー情報")
        st.write(f"**{current_user_name}** ({user_info.get('email')})")
        st.markdown("---")
        if st.button("🚪 ログアウト", type="primary", key="sidebar_logout_chat_ui_v2"):
            auth_utils.logout()

    chat_container = st.container()
    with chat_container:
        if not loaded_chat_log: st.info("まだメッセージはありません。")
        for msg in loaded_chat_log:
            is_own = (current_user_id == msg.get('senderId'))
            avatar = "🙂" if is_own else "👤"
            timestamp_dt = msg.get("timestamp_datetime")
            with st.chat_message(name="user" if is_own else msg.get('senderName', '不明'), avatar=avatar):
                if not is_own: st.caption(f"{msg.get('senderName', '不明')} より:")
                st.markdown(msg.get('text', ''))
                if timestamp_dt:
                    try:
                        jst_ts = timestamp_dt.astimezone(timezone(timedelta(hours=9)))
                        st.caption(jst_ts.strftime('%m/%d %H:%M'))
                    except: pass # タイムスタンプ表示エラーは無視

    user_input = st.chat_input("メッセージを入力...", key="chat_input_main_ui_v2")
    if user_input and user_input.strip():
        if firebase_utils.save_message_to_firestore(current_user_id, current_user_name, user_input):
            st.rerun()
        else: st.error("メッセージ送信失敗。")