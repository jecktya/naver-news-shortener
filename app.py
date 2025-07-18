# -*- coding: utf-8 -*-

import os
import re
import html
import asyncio
import json
import httpx
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

# 기본 설정
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 네이버 API 환경 변수
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

# 기본 키워드 및 주요 언론사
DEFAULT_KEYWORDS = [
    "육군", "국방", "외교", "안보", "북한", "신병", "교육대",
    "훈련", "간부", "장교", "부사관", "병사", "용사", "군무원"
]
PRESS_MAJOR = {
    "조선일보", "연합뉴스", "한겨레", "중앙일보",
    "MBN", "KBS", "SBS", "YTN",
    "동아일보", "세계일보", "문화일보", "뉴시스",
    "국민일보", "국방일보", "이데일리",
    "뉴스1", "JTBC"
}

# 기사 pubdate 문자열을 datetime으로 변환
def parse_pubdate(pubdate_str: str):
    try:
        # e.g. "Wed, 10 Jul 2024 14:03:00 +0900"
        return datetime.strptime(pubdate_str[:-6].strip(), "%a, %d %b %Y %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=9)))
    except Exception:
        return None

# 네이버 뉴스 API 검색
async def search_naver_news(keywords: str, display: int = 30, search_mode="all", video_only=False):
    kw_list = [k.strip() for k in re.split(r"[, ]+", keywords) if k.strip()]
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS
    query = " OR ".join(kw_list)
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
        items = data.get("items", [])

    # 필터/정제
    filtered = []
    now = datetime.now(timezone(timedelta(hours=9)))
    for item in items:
        title = html.unescape(item.get("title", "")).replace("<b>", "").replace("</b>", "")
        desc = html.unescape(item.get("description", "")).replace("<b>", "").replace("</b>", "")
        content = f"{title} {desc}"
        press = item.get("publisher", "") or ""
        url = item.get("link", "")
        pubdate_str = item.get("pubDate", "")
        pubdate = parse_pubdate(pubdate_str)
        # (1) 4시간 이내
        if pubdate and now - pubdate > timedelta(hours=4):
            continue
        # (2) 언론사 필터
        if search_mode == "major" and press not in PRESS_MAJOR:
            continue
        # (3) 동영상 필터 (간단 키워드/URL 패턴)
        if video_only:
            if not ("영상" in title or "영상" in desc or "/v/" in url or "video" in url):
                continue
        # (4) 키워드 매칭(부분일치/횟수)
        kwcnt = {}
        for kw in kw_list:
            cnt = len(re.findall(re.escape(kw), content, re.IGNORECASE))
            if cnt > 0:
                kwcnt[kw] = cnt
        if len(kwcnt) < 2:  # "2개 이상 키워드" 필터
            continue
        filtered.append({
            "title": title,
            "desc": desc,
            "press": press,
            "url": url,
            "pubdate": pubdate.strftime("%Y-%m-%d %H:%M") if pubdate else pubdate_str,
            "keywords": sorted(kwcnt.items(), key=lambda x: (-x[1], x[0])),
        })
    return filtered

# naver.me 변환 (Colab에서 성공한 로직)
async def get_naverme_from_news(url: str) -> str:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        iphone_vp = {"width": 428, "height": 926}
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport=iphone_vp, user_agent=iphone_ua)
        await page.goto(url, timeout=20000)
        await asyncio.sleep(2)
        try:
            await page.click("span.u_hc", timeout=3000)
            await asyncio.sleep(1.5)
        except Exception:
            pass
        html_src = await page.content()
        match = re.search(r"https://naver\.me/[a-zA-Z0-9]+", html_src)
        await browser.close()
        if match:
            return match.group(0)
        else:
            return "naver.me 주소를 찾을 수 없음"

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    now = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')
    return templates.TemplateResponse(
        "index.html", {
            "request": request,
            "keyword_input": "",
            "search_mode": "all",
            "video_only": False,
            "results": [],
            "shorten_results": [],
            "error": None,
            "now": now,
            "default_keywords": ', '.join(DEFAULT_KEYWORDS)
        })

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(...),
    search_mode: str = Form("all"),
    video_only: str = Form(""),
):
    now = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')
    try:
        results = await search_naver_news(
            keywords,
            display=30,
            search_mode=search_mode,
            video_only=(video_only == "on")
        )
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "keyword_input": keywords,
                "search_mode": search_mode,
                "video_only": (video_only == "on"),
                "results": results,
                "shorten_results": [],
                "error": None,
                "now": now,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS)
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "keyword_input": keywords,
                "search_mode": search_mode,
                "video_only": (video_only == "on"),
                "results": [],
                "shorten_results": [],
                "error": f"검색 오류: {e}",
                "now": now,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS)
            }
        )

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: list = Form(...),
    results_json: str = Form(...),
    keyword_input: str = Form(""),
    search_mode: str = Form("all"),
    video_only: str = Form(""),
):
    now = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S')
    import json
    try:
        results = json.loads(results_json)
        shorten_results = []
        for idx_str in selected_urls:
            idx = int(idx_str)
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
                "search_mode": search_mode,
                "video_only": (video_only == "on"),
                "results": results,
                "shorten_results": shorten_results,
                "error": None,
                "now": now,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS)
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "keyword_input": keyword_input,
                "search_mode": search_mode,
                "video_only": (video_only == "on"),
                "results": [],
                "shorten_results": [],
                "error": f"단축 오류: {e}",
                "now": now,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS)
            }
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
