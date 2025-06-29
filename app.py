@app.get("/debug-playwright", response_class=PlainTextResponse)
async def debug_playwright():
    try:
        from playwright.async_api import async_playwright
        async def run():
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                await browser.close()
            return "Playwright 정상 동작!"
        import asyncio
        return await run()
    except Exception as e:
        return f"Playwright 오류: {e}"
