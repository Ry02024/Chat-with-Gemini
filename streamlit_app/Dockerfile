# Pythonの公式イメージをベースとして使用
FROM python:3.10-slim

# pipを最新バージョンにアップグレードし、キャッシュを無効化
RUN pip install --no-cache-dir --upgrade pip

# 作業ディレクトリを設定
WORKDIR /app

# ★★★ root以外のユーザーを作成し、そのユーザーに切り替える (オプションだが推奨) ★★★
# RUN useradd -m myuser
# USER myuser
# WORKDIR /home/myuser/app # ユーザーのホームディレクトリを作業ディレクトリにする場合

# 依存関係ファイルをコピー
COPY requirements.txt requirements.txt

# 依存関係をインストール (キャッシュを無効化)
# もし仮想環境を使うなら、ここで仮想環境を作成・アクティベートし、その中でpip install
RUN pip install --no-cache-dir -r requirements.txt

# アプリケーションコードをコピー
# USER myuser を使っている場合、ファイルの所有者を適切に設定する必要がある場合がある
# COPY --chown=myuser:myuser . .
COPY . .

# Streamlitが使用するポートを公開
EXPOSE 8080

# アプリケーションを実行
# USER myuser を使っている場合、streamlitコマンドがそのユーザーで実行される
CMD ["streamlit", "run", "app.py", "--server.port=8080", "--server.headless=true"]