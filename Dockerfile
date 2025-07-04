# Dockerfile
# Playwright + Python 환경이 미리 구성된 공식 이미지 사용
FROM mcr.microsoft.com/playwright/python:v1.52.0-noble

WORKDIR /app

# ① Python 라이브러리 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ② 애플리케이션 코드 복사
COPY . .

# ③ 열어둘 포트
EXPOSE 8080

# ④ 서버 기동
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
