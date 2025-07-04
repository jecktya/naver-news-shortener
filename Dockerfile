FROM python:3.9-slim-buster

WORKDIR /app

# 1) 시스템 종속성 설치 (Playwright 권장 라이브러리)
RUN apt-get update && apt-get install -y \
      libnss3 \
      libatk1.0-0 \
      libatk-bridge2.0-0 \
      libcups2 \
      libxkbcommon0 \
      libxss1 \
      libgtk-3-0 \
      libgbm-dev \
      ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2) Python 종속성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 3) Playwright 브라우저 설치
RUN playwright install --with-deps

# 4) 앱 코드 복사
COPY . .

# 5) 컨테이너 포트
EXPOSE 8080

# 6) 서버 기동: 애플리케이션 파일명이 app.py인 경우
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
