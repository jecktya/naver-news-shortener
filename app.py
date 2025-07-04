# app.py
from fastapi import FastAPI
import uvicorn
import os
import logging
import asyncio # asyncio 모듈 임포트

# 로깅 설정 (DEBUG 레벨로 설정하여 상세 로그 확인)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Minimal Test App")

# 애플리케이션 시작 시 실행될 이벤트 핸들러
@app.on_event("startup")
async def startup_event():
    logger.info("Application startup event triggered.")
    # 아주 짧은 비동기 지연을 추가하여 서비스가 완전히 준비될 시간을 줍니다.
    # 이 지연은 메인 이벤트 루프를 블록하지 않습니다.
    await asyncio.sleep(0.5) # 0.5초 지연
    logger.info("Application startup delay completed. App is ready to serve requests.")

@app.get("/")
async def read_root():
    logger.info("Root endpoint accessed.")
    return {"message": "Hello from Minimal FastAPI App!"}

# 이 부분은 Railway에서 자동으로 Uvicorn을 실행하므로 보통 필요 없습니다.
# 하지만 로컬 테스트용으로 남겨둘 수 있습니다.
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    logger.info(f"Starting Uvicorn server on port {port}")
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

