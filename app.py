from flask import Flask
import os

app = Flask(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

@app.route("/")
def home():
    return f"Flask 앱이 실행 중입니다.<br>NAVER_CLIENT_ID: {NAVER_CLIENT_ID}", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
