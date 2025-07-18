import os
import json
import random
import string
import logging
import asyncio
import re
from datetime import datetime
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx

# ----- 로깅 설정 -----
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

# ----- 주요언론사 목록 -----
PRESS_MAJOR = {
    '연합뉴스', '조선일보', '한겨레', '중앙일보',
    'MBN', 'KBS', 'SBS', 'YTN',
    '동아일보', '세계일보', '문화일보', '뉴시스',
    '국민일보', '국방일보', '이데일리', '뉴스1', 'JTBC'
}

DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]

def parse_api_pubdate(pubdate_str: str) -> str:
    if not pubdate_str:
        return ""
    try:
        dt = datetime.strptime(pubdate_str[:-6].strip(), "%a, %d %b %Y %H:%M:%S")
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return pubdate_str

async def search_naver_news(keywords: str, display: int = 10):
    # 쉼표/공백 분리
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

async def naver_me_shorten(orig_url: str) -> str:
    # Playwright로 naver.me 주소 추출 (컨테이너 배포 환경에서는 불안정)
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return "Playwright 미설치"
    async with async_playwright() as p:
        iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        iphone_vp = {"width": 428, "height": 926}
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(viewport=iphone_vp, user_agent=iphone_ua)
        await page.goto(orig_url, timeout=20000)
        await asyncio.sleep(2)
        try:
            await page.click("span.u_hc", timeout=3000)
            await asyncio.sleep(2)
        except Exception:
            pass
        html = await page.content()
        match = re.search(r'https://naver\.me/[a-zA-Z0-9]+', html)
        await browser.close()
        if match:
            return match.group(0)
        else:
            return "naver.me 주소를 찾을 수 없음"

# Jinja2Templates
templates = Jinja2Templates(directory="templates")
templates.env.globals["enumerate"] = enumerate

app = FastAPI(title="뉴스검색+단축")

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    return templates.TemplateResponse(
        "index.html", {
            "request": request,
            "keyword_input": '',
            "results": [],
            "shorten_results": [],
            "error": None,
            "default_keywords": ', '.join(DEFAULT_KEYWORDS),
            "search_mode": "all",
            "current_time": datetime.now().strftime("%Y-%m-%d %H:%M")
        })

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(...),
    search_mode: str = Form("all"),
):
    try:
        news_items = await search_naver_news(keywords)
        results = []
        for item in news_items:
            press = item.get("publisher", "")
            if search_mode == "major" and press not in PRESS_MAJOR:
                continue
            results.append({
                "title": re.sub('<.+?>', '', item.get("title", "")),
                "press": press,
                "url": item.get("link", ""),
                "desc": re.sub('<.+?>', '', item.get("description", "")),
                "pubdate": parse_api_pubdate(item.get("pubDate", "")),
            })
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "keyword_input": keywords,
                "results": results,
                "shorten_results": [],
                "error": None,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS),
                "search_mode": search_mode,
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M")
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
                "default_keywords": ', '.join(DEFAULT_KEYWORDS),
                "search_mode": search_mode,
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
        )

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: str = Form(...),
    results_json: str = Form(...),
    keyword_input: str = Form(''),
    search_mode: str = Form('all'),
):
    import json
    try:
        selected = json.loads(selected_urls)
        results = json.loads(results_json)
        shorten_results = []
        for idx in selected:
            url = results[idx]['url']
            naverme = await naver_me_shorten(url)
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
                "default_keywords": ', '.join(DEFAULT_KEYWORDS),
                "search_mode": search_mode,
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M")
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
                "default_keywords": ', '.join(DEFAULT_KEYWORDS),
                "search_mode": search_mode,
                "current_time": datetime.now().strftime("%Y-%m-%d %H:%M")
            }
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
