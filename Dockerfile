FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    curl unzip xvfb libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
    libasound2 libxshmfence1 libx11-xcb1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install

COPY . /app
WORKDIR /app
CMD ["streamlit", "run", "app.py", "--server.port=8000", "--server.enableCORS=false"]
