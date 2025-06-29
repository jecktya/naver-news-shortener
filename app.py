from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

app = FastAPI()

@app.get("/debug", response_class=PlainTextResponse)
async def debug():
    import os
    from datetime import datetime

    NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
    NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
    now = datetime.now().isoformat()

    # 파일 목록
    try:
        files = os.listdir(".")
        files_str = "\n".join(files)
    except Exception as e:
        files_str = f"파일 목록 오류: {e}"

    # Playwright 상태 (비동기)
    try:
        from playwright.async_api import async_playwright
        import asyncio

        async def playwright_check():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                await browser.close()
            return "Playwright 정상 동작!"

        playwright_status = await playwright_check()
    except Exception as e:
        playwright_status = f"Playwright 오류: {e}"

    return (
        f"서버시간: {now}\n\n"
        f"[현재폴더 파일 목록]\n{files_str}\n\n"
        f"[Playwright 상태]\n{playwright_status}\n"
    )
