FROM python:3.10

WORKDIR /app
COPY . .

# 패키지 설치
RUN pip install --no-cache-dir -r requirements.txt

# Playwright 브라우저 설치
RUN python -m playwright install

CMD ["python", "app.py"]
