from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI()

@app.get("/debug", response_class=PlainTextResponse)
async def debug():
    import os
    from datetime import datetime

    # 환경변수
    NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
    NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
    now = datetime.now().isoformat()

    # 파일 목록
    try:
        files = os.listdir(".")
        files_str = "\n".join(files)
    except Exception as e:
        files_str = f"파일 목록 오류: {e}"

    # Playwright 상태
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        playwright_status = "Playwright 정상 동작!"
    except Exception as e:
        playwright_status = f"Playwright 오류: {e}"

    # 결과 종합
    return (
        f"[환경변수]\n"
        f"NAVER_CLIENT_ID: {NAVER_CLIENT_ID}\n"
        f"NAVER_CLIENT_SECRET: {NAVER_CLIENT_SECRET}\n"
        f"서버시간: {now}\n\n"
        f"[현재폴더 파일 목록]\n"
        f"{files_str}\n\n"
        f"[Playwright 상태]\n"
        f"{playwright_status}\n"
    )
