# app.py
from fastapi import FastAPI
import uvicorn
import os
import logging

# 로깅 설정 (DEBUG 레벨로 설정하여 상세 로그 확인)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="Minimal Test App")

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

