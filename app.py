import os
import asyncio
import re
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from playwright.async_api import async_playwright

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 검색 기본 키워드
DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]

NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")

async def search_naver_news(keywords: str, display: int = 10):
    import httpx
    # 쉼표, 스페이스, 엔터 전부 분리 허용
    if ',' in keywords:
        kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
    else:
        kw_list = [k.strip() for k in re.split(r'[\s]+', keywords) if k.strip()]
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS
    query = ' OR '.join(kw_list)
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": display,
        "sort": "date"
    }
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()
        return data.get("items", [])

async def get_naverme_from_news(url: str) -> str:
    async with async_playwright() as p:
        iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        iphone_vp = {"width": 428, "height": 926}
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(viewport=iphone_vp, user_agent=iphone_ua)
        await page.goto(url, timeout=20000)
        await asyncio.sleep(2)
        # 공유버튼(실패해도 그냥 진행)
        try:
            await page.click("span.u_hc", timeout=3000)
            await asyncio.sleep(1.5)
        except Exception:
            pass
        html = await page.content()
        match = re.search(r'https://naver\.me/[a-zA-Z0-9]+', html)
        await browser.close()
        if match:
            return match.group(0)
        else:
            return "naver.me 주소를 찾을 수 없음"

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse(
        "index.html", {
            "request": request,
            "keyword_input": '',
            "results": [],
            "shorten_results": [],
            "error": None,
            "default_keywords": ', '.join(DEFAULT_KEYWORDS)
        })

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(...),
):
    try:
        news_items = await search_naver_news(keywords)
        results = []
        for item in news_items:
            results.append({
                "title": re.sub('<.+?>', '', item.get("title", "")),
                "press": item.get("publisher", ""),
                "url": item.get("link", ""),
                "desc": re.sub('<.+?>', '', item.get("description", "")),
                "pubdate": item.get("pubDate", "")
            })
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "keyword_input": keywords,
                "results": results,
                "shorten_results": [],
                "error": None,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS)
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "keyword_input": keywords,
                "results": [],
                "shorten_results": [],
                "error": f"검색 오류: {e}",
                "default_keywords": ', '.join(DEFAULT_KEYWORDS)
            }
        )

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: str = Form(...),
    results_json: str = Form(...),
    keyword_input: str = Form(''),
):
    import json
    try:
        selected = json.loads(selected_urls)
        results = json.loads(results_json)
        shorten_results = []
        for idx in selected:
            url = results[idx]['url']
            naverme = await get_naverme_from_news(url)
            shorten_results.append({
                "title": results[idx]['title'],
                "press": results[idx]['press'],
                "naverme": naverme
            })
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "keyword_input": keyword_input,
                "results": results,
                "shorten_results": shorten_results,
                "error": None,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS)
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "keyword_input": keyword_input,
                "results": [],
                "shorten_results": [],
                "error": f"단축 오류: {e}",
                "default_keywords": ', '.join(DEFAULT_KEYWORDS)
            }
        )
