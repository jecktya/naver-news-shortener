# Dockerfile 최종 버전
# 이 Dockerfile은 Python 기반 FastAPI 애플리케이션을 컨테이너화합니다.

# 1. 기본 이미지 지정: Python 3.9 Slim Buster 버전을 사용합니다.
#    Slim 버전은 필요한 라이브러리만 포함하여 이미지 크기를 줄입니다.
FROM python:3.9-slim-buster

# 2. 작업 디렉토리 설정: 컨테이너 내부의 작업 디렉토리를 /app으로 설정합니다.
WORKDIR /app

# 3. 시스템 의존성 설치: Playwright 브라우저 실행에 필요한 시스템 라이브러리들을 설치합니다.
#    이 단계는 Playwright를 requirements.txt에 포함했을 때 필수적입니다.
#    `apt-get update`와 `apt-get install`을 한 줄에 작성하여 캐시 문제를 방지합니다.
#    Playwright 공식 문서에서 권장하는 핵심 의존성 목록과 함께 'libgbm1'을 추가합니다.
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxkbcommon0 \
    libxrandr2 \
    libxrender1 \
    libxss1 \
    libxtst6 \
    xdg-utils \
    libgbm1 \
    # apt 캐시 정리 (이미지 크기 최적화)
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 4. requirements.txt 복사 및 Python 의존성 설치:
#    requirements.txt 파일을 먼저 복사하여 pip install을 실행합니다.
#    이렇게 하면 코드 변경 시에도 의존성 변경이 없으면 이 레이어가 캐시되어 빌드 속도가 빨라집니다.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Playwright 브라우저 설치:
#    requirements.txt에 playwright가 명시되어 있으므로, 실제 브라우저 바이너리를 설치합니다.
#    `chromium`만 설치합니다. 필요에 따라 `firefox`, `webkit`을 추가할 수 있습니다.
RUN playwright install chromium

# 6. 애플리케이션 코드 복사:
#    현재 디렉토리의 모든 파일(Dockerfile, requirements.txt 제외)을 컨테이너의 /app으로 복사합니다.
COPY . .

# 7. 컨테이너 실행 명령 정의:
#    컨테이너가 시작될 때 실행될 명령어를 정의합니다.
#    Uvicorn을 사용하여 FastAPI 애플리케이션을 실행하며,
#    --host 0.0.0.0은 모든 네트워크 인터페이스에서 수신하도록 하고,
#    --port $PORT는 Railway와 같은 환경에서 자동으로 설정되는 PORT 환경 변수를 사용합니다.
#    'app:app'은 'app.py' 파일 내의 'app' FastAPI 인스턴스를 의미합니다.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
