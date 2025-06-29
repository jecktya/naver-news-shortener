from flask import Flask, request, jsonify
import os

app = Flask(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

@app.route('/')
def index():
    return "뉴스검색기 API 서버가 실행 중입니다!"

# 여기에 검색 엔드포인트 등 붙이기

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
