# Dockerfile

# 1) Playwright 공식 이미지 사용 (Python 3.9 + Chromium 브라우저 내장)
FROM mcr.microsoft.com/playwright/python:1.38.1-focal

WORKDIR /app

# 2) Python 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3) 애플리케이션 코드 복사
COPY . .

# 4) 컨테이너 내부 포트
EXPOSE 8080

# 5) 서버 기동: app.py 안의 FastAPI 인스턴스(app)를 uvicorn으로 실행
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
