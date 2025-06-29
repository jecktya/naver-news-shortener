FROM python:3.10

WORKDIR /app
COPY . .

# 필수 라이브러리 설치 (Playwright에서 요구하는 모든 패키지)
RUN apt-get update && \
    apt-get install -y wget \
        libnss3 \
        libatk-bridge2.0-0 \
        libatk1.0-0 \
        libcups2 \
        libdrm2 \
        libxkbcommon0 \
        libxcomposite1 \
        libxdamage1 \
        libxrandr2 \
        libgbm1 \
        libasound2 \
        libatspi2.0-0 \
        libdbus-1-3 \
        libxshmfence1 \
        libnspr4 \
        fonts-noto-color-emoji

# 파이썬 라이브러리 설치
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 및 브라우저 설치
RUN python -m playwright install --with-deps

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
