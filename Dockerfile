# Dockerfile 예시
FROM python:3.9-slim-buster # 또는 사용하는 Python 버전
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 브라우저 설치 (매우 중요!)
# 필요한 시스템 라이브러리 설치 후 playwright install 실행
RUN apt-get update && apt-get install -y \
    libnss3 \
    libxss1 \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libgdk-pixbuf2.0-0 \
    libfontconfig1 \
    libjpeg-turbo8 \
    libwebp6 \
    libpng16-16 \
    libglib2.0-0 \
    libharfbuzz0b \
    libfreetype6 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libxrender1 \
    libxi6 \
    libxcursor1 \
    libxext6 \
    libxrandr2 \
    libxrender1 \
    libxi6 \
    libxcursor1 \
    libxext6 \
    libxinerama1 \
    libxmu6 \
    libxpm4 \
    libxtst6 \
    libappindicator1 \
    libdbus-glib-1-2 \
    libindicator7 \
    fonts-liberation \
    xdg-utils \
    # 기타 필요한 라이브러리
    && rm -rf /var/lib/apt/lists/*

RUN playwright install --with-deps chromium # --with-deps는 시스템 의존성도 설치 시도

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
