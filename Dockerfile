# Dockerfile
FROM python:3.9-slim-buster

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# (선택) 컨테이너 내에서 열어둘 포트 표시
EXPOSE 8080

# uvicorn 실행 시 $PORT (Railway에서 주입) 또는 기본 8080 사용
CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT:-8080}"]
