FROM python:3.10

WORKDIR /app
COPY . .

# 필수 리눅스 라이브러리 (Playwright 브라우저용) 설치!
RUN apt-get update && apt-get install -y wget libnss3 libatk-bridge2.0-0 libatk1.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 libasound2 libatspi2.0-0 libdbus-1-3 libxshmfence1 libnspr4

# 파이썬 라이브러리 설치
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 브라우저 바이너리 및 의존성 설치
RUN python -m playwright install --with-deps

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
