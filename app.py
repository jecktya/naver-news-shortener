from fastapi.responses import PlainTextResponse

@app.get("/debug-playwright", response_class=PlainTextResponse)
async def debug_playwright():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return "Playwright 정상 동작!"
    except Exception as e:
        return f"Playwright 오류: {e}"
