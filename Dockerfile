# Dockerfile
FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

# ① Python 라이브러리 설치 (Playwright는 베이스 이미지에 이미 설치되어 있습니다)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ② 애플리케이션 코드 복사
COPY . .

# ③ 컨테이너 내부 포트(선택)
EXPOSE 8080

# ④ Uvicorn 실행: app.py 안의 FastAPI 인스턴스(app)를 띄웁니다
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
