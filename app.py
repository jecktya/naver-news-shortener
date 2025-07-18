# -*- coding: utf-8 -*-
import os
import re
import json
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx

# 로그 세팅
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]

PRESS_MAJOR = {
    '연합뉴스', '조선일보', '한겨레', '중앙일보',
    'MBN', 'KBS', 'SBS', 'YTN', '동아일보', '세계일보',
    '문화일보', '뉴시스', '국민일보', '국방일보', '이데일리',
    '뉴스1', 'JTBC'
}

app = FastAPI(title="네이버 뉴스검색기+단축주소")
templates = Jinja2Templates(directory="templates")
templates.env.globals["enumerate"] = enumerate

# 날짜 파싱 (RFC 1123 → datetime)
def parse_api_pubdate(pubdate_str: str):
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(pubdate_str).astimezone(timezone(timedelta(hours=9)))
    except Exception:
        return None

async def search_naver_news(keywords, display=15):
    logger.info(f"[API] 뉴스 검색 요청 | 키워드: {keywords}")
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        logger.error("네이버 API 키 미설정")
        raise HTTPException(500, "NAVER API KEY 미설정")
    # 쉼표/스페이스/엔터 모두 분리
    kw_list = [k.strip() for k in re.split(r'[, \n]+', keywords) if k.strip()]
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS
    # 쿼리: 모든 키워드 포함 기사를 많이 얻으려면 'OR' 방식
    query = " OR ".join(kw_list)
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": query, "display": display, "sort": "date"}
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
        logger.info(f"[API] 응답 status={res.status_code}")
        res.raise_for_status()
        items = res.json().get("items", [])
        logger.info(f"[API] 뉴스 개수: {len(items)}")
        return items

async def get_naverme_from_news(url: str) -> str:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        iphone_vp = {"width": 428, "height": 926}
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(viewport=iphone_vp, user_agent=iphone_ua)
        await page.goto(url, timeout=20000)
        await asyncio.sleep(1.5)
        try:
            await page.click("span.u_hc", timeout=3000)
            await asyncio.sleep(1)
        except Exception:
            pass
        html = await page.content()
        match = re.search(r'https://naver\.me/[a-zA-Z0-9]+', html)
        await browser.close()
        if match:
            logger.info(f"[단축] 변환 성공 {match.group(0)}")
            return match.group(0)
        else:
            logger.warning(f"[단축] 변환실패: {url}")
            return "naver.me 주소를 찾을 수 없음"

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    now = datetime.now(timezone(timedelta(hours=9)))
    return templates.TemplateResponse("index.html", {
        "request": request,
        "results": [],
        "shorten_results": [],
        "keyword_input": '',
        "default_keywords": ', '.join(DEFAULT_KEYWORDS),
        "search_mode": "all",
        "video_only": False,
        "checked_two_keywords": False,
        "now": now.strftime('%Y-%m-%d %H:%M:%S'),
        "error_message": None,
        "msg": ""
    })

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(...),
    search_mode: str = Form("all"),
    video_only: str = Form(""),
    checked_two_keywords: str = Form(""),
):
    try:
        logger.info(f"[검색] POST | 키워드={keywords} | 검색모드={search_mode} | 동영상만={video_only} | 2개이상={checked_two_keywords}")
        news_items = await search_naver_news(keywords)
        now = datetime.now(timezone(timedelta(hours=9)))
        kw_list = [k.strip() for k in re.split(r'[, \n]+', keywords) if k.strip()]
        if not kw_list:
            kw_list = DEFAULT_KEYWORDS

        articles = []
        for item in news_items:
            title = re.sub('<.+?>', '', item.get("title", ""))
            desc = re.sub('<.+?>', '', item.get("description", ""))
            press = item.get("publisher", "")
            url = item.get("link", "")
            pubdate = parse_api_pubdate(item.get("pubDate", ""))
            # 4시간 이내만 필터
            if not pubdate or (now - pubdate > timedelta(hours=4)):
                continue
            # 키워드 매칭
            kwcnt = {}
            all_text = f"{title} {desc}"
            for kw in kw_list:
                # 정확한 포함(부분일치)
                count = len(re.findall(re.escape(kw), all_text, re.IGNORECASE))
                if count > 0:
                    kwcnt[kw] = count
            # 2개 이상 키워드 포함 필터
            if checked_two_keywords == "on" and len(kwcnt) < 2:
                continue
            # 주요 언론사 필터
            if search_mode == "major" and press not in PRESS_MAJOR:
                continue
            # 동영상 키워드(간단 판별)
            if video_only == "on":
                if not any(v in title+desc for v in ["영상", "동영상", "뉴스영상", "video", "VID"]):
                    continue
            articles.append({
                "title": title,
                "press": press,
                "url": url,
                "desc": desc,
                "pubdate": pubdate.strftime('%Y-%m-%d %H:%M') if pubdate else "",
                "kw_count": sum(kwcnt.values()),
                "kw_detail": ", ".join([f"{k}({v})" if v>1 else k for k, v in kwcnt.items()])
            })
        logger.info(f"[검색] 최종 필터링 기사수: {len(articles)}")
        msg = f"총 {len(articles)}건 검색됨"
        return templates.TemplateResponse("index.html", {
            "request": request,
            "results": articles,
            "shorten_results": [],
            "keyword_input": keywords,
            "default_keywords": ', '.join(DEFAULT_KEYWORDS),
            "search_mode": search_mode,
            "video_only": (video_only == "on"),
            "checked_two_keywords": (checked_two_keywords == "on"),
            "now": now.strftime('%Y-%m-%d %H:%M:%S'),
            "error_message": None,
            "msg": msg
        })
    except Exception as e:
        logger.error(f"[검색오류] {e}", exc_info=True)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "results": [],
            "shorten_results": [],
            "keyword_input": keywords,
            "default_keywords": ', '.join(DEFAULT_KEYWORDS),
            "search_mode": search_mode,
            "video_only": (video_only == "on"),
            "checked_two_keywords": (checked_two_keywords == "on"),
            "now": datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S'),
            "error_message": str(e),
            "msg": "검색 실패"
        })

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: list = Form(...),
    results_json: str = Form(...),
    keyword_input: str = Form(''),
    search_mode: str = Form("all"),
    video_only: str = Form(""),
    checked_two_keywords: str = Form(""),
):
    import json
    now = datetime.now(timezone(timedelta(hours=9)))
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
        logger.info(f"[단축] 단축 성공: {len(shorten_results)}건")
        return templates.TemplateResponse("index.html", {
            "request": request,
            "results": results,
            "shorten_results": shorten_results,
            "keyword_input": keyword_input,
            "default_keywords": ', '.join(DEFAULT_KEYWORDS),
            "search_mode": search_mode,
            "video_only": (video_only == "on"),
            "checked_two_keywords": (checked_two_keywords == "on"),
            "now": now.strftime('%Y-%m-%d %H:%M:%S'),
            "error_message": None,
            "msg": "단축 완료"
        })
    except Exception as e:
        logger.error(f"[단축오류] {e}", exc_info=True)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "results": [],
            "shorten_results": [],
            "keyword_input": keyword_input,
            "default_keywords": ', '.join(DEFAULT_KEYWORDS),
            "search_mode": search_mode,
            "video_only": (video_only == "on"),
            "checked_two_keywords": (checked_two_keywords == "on"),
            "now": now.strftime('%Y-%m-%d %H:%M:%S'),
            "error_message": str(e),
            "msg": "단축 실패"
        })

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
