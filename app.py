# app.py
# -*- coding: utf-8 -*-

import os
import json
import random
import string
import logging
import asyncio
import re
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# --- 로거 설정 ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")

logger.info("="*35)
logger.info(f"NAVER_CLIENT_ID: {NAVER_CLIENT_ID}")
logger.info(f"NAVER_CLIENT_SECRET: {NAVER_CLIENT_SECRET[:4]}{'*'*(len(NAVER_CLIENT_SECRET)-4)}")
logger.info("="*35)

NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"
templates = Jinja2Templates(directory="templates")
templates.env.globals["enumerate"] = enumerate

app = FastAPI(title="뉴스검색기 (FastAPI+NaverAPI+네이버미변환)")

DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]

PRESS_MAJOR = {
    '연합뉴스', '조선일보', '한겨레', '중앙일보',
    'MBN', 'KBS', 'SBS', 'YTN',
    '동아일보', '세계일보', '문화일보', '뉴시스',
    '국민일보', '국방일보', '이데일리',
    '뉴스1', 'JTBC'
}

def parse_api_pubdate(pubdate_str: str) -> Optional[datetime]:
    if not pubdate_str:
        return None
    try:
        date_time_part = pubdate_str[:-6].strip()
        return datetime.strptime(date_time_part, "%a, %d %b %Y %H:%M:%S")
    except Exception:
        return None

async def search_naver_news(query: str, display: int = 10):
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET or \
       NAVER_CLIENT_ID == "YOUR_NAVER_CLIENT_ID_HERE" or \
       NAVER_CLIENT_SECRET == "YOUR_NAVER_CLIENT_SECRET_HERE":
        raise HTTPException(status_code=500, detail="NAVER API 키 환경변수 확인")
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": display,
        "sort": "date"
    }
    logger.info(f"네이버 뉴스 API 요청 시작. 쿼리: '{query}', 표시 개수: {display}")
    async with httpx.AsyncClient(timeout=10) as client:
        res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
        res.raise_for_status()
        data = res.json()
        items = data.get("items", [])
        logger.info(f"네이버 뉴스 API 응답 수신. 총 {len(items)}개 아이템.")
        return items

async def get_naverme_from_news(url: str) -> str:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        iphone_vp = {"width": 428, "height": 926}
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(viewport=iphone_vp, user_agent=iphone_ua)
        await page.goto(url, timeout=20000)
        await asyncio.sleep(2)
        # 공유버튼 여러 방식 시도
        try:
            await page.click("span.u_hc", timeout=3000)
            await asyncio.sleep(1.2)
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
            "default_keywords": ', '.join(DEFAULT_KEYWORDS),
            "keyword_input": '',
            "final_results": [],
            "msg": "검색 결과 없음",
            "shortened": None,
            "shorten_fail": [],
            "error_message": None
        })

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(...),
    search_mode: str = Form("major"),
    video_only: str = Form("")
):
    try:
        # 키워드 처리 (콤마/스페이스/줄바꿈 구분)
        if ',' in keywords:
            kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
        else:
            kw_list = [k.strip() for k in re.split(r'[\s]+', keywords) if k.strip()]
        if not kw_list:
            kw_list = DEFAULT_KEYWORDS
        query = ' OR '.join(kw_list)
        news_items = await search_naver_news(query)
        filtered_news_items_by_domain = []
        for item in news_items:
            link = item.get("link", "")
            if link.startswith("https://n.news.naver.com/") or link.startswith("https://m.entertain.naver.com/"):
                filtered_news_items_by_domain.append(item)
        processed_results = []
        for item in filtered_news_items_by_domain:
            title = re.sub('<.+?>', '', item.get("title", ""))
            press = item.get("publisher", "")
            url = item.get("link", "")
            desc = re.sub('<.+?>', '', item.get("description", ""))
            pubdate_str = item.get("pubDate", "")
            parsed_pubdate = parse_api_pubdate(pubdate_str)
            processed_results.append({
                "title": title,
                "press": press,
                "pubdate": parsed_pubdate,
                "pubdate_display": parsed_pubdate.strftime('%Y-%m-%d %H:%M') if parsed_pubdate else pubdate_str,
                "url": url,
                "desc": desc,
            })
        processed_results.sort(key=lambda x: (x['pubdate'] if x['pubdate'] is not None else datetime.min), reverse=True)
        serializable_results = []
        for item in processed_results:
            serializable_item = item.copy()
            if serializable_item['pubdate'] is not None:
                serializable_item['pubdate'] = serializable_item['pubdate'].isoformat()
            serializable_results.append(serializable_item)
        msg = f"총 {len(serializable_results)}건의 뉴스가 검색되었습니다."
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS),
                "keyword_input": keywords,
                "final_results": serializable_results,
                "msg": msg,
                "shortened": None,
                "shorten_fail": [],
                "error_message": None
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS),
                "keyword_input": keywords,
                "final_results": [],
                "msg": "오류 발생: " + str(e),
                "shortened": None,
                "shorten_fail": [],
                "error_message": str(e)
            }
        )

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: List[str] = Form(...),
    final_results_json: str = Form(...),
    keyword_input: str = Form('')
):
    import json
    try:
        final_results = json.loads(final_results_json)
        shortened_list = []
        shorten_fail_list = []
        # naver.me 변환 (병렬 실행)
        tasks = []
        selected_articles_info = []
        for idx_str in selected_urls:
            try:
                idx = int(idx_str)
                if 0 <= idx < len(final_results):
                    selected_articles_info.append(final_results[idx])
                    tasks.append(get_naverme_from_news(final_results[idx]['url']))
                else:
                    shorten_fail_list.append(f"유효하지 않은 뉴스 선택 (인덱스: {idx_str})")
            except Exception as e:
                shorten_fail_list.append(f"URL 선택 처리 오류: {e}")
        if tasks:
            shorten_results = await asyncio.gather(*tasks)
            for i, short_url in enumerate(shorten_results):
                art = selected_articles_info[i]
                if not short_url or not short_url.startswith("https://naver.me/"):
                    shorten_fail_list.append(f"'{art['title']}': {short_url}")
                else:
                    line = f"■ {art['title']} ({art['press']})\n{short_url}"
                    shortened_list.append(line)
        msg = f"총 {len(final_results)}건의 뉴스가 검색되었습니다."
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS),
                "keyword_input": keyword_input,
                "final_results": final_results,
                "msg": msg,
                "shortened": '\n\n'.join(shortened_list) if shortened_list else None,
                "shorten_fail": shorten_fail_list,
                "error_message": None
            }
        )
    except Exception as e:
        return templates.TemplateResponse(
            "index.html", {
                "request": request,
                "default_keywords": ', '.join(DEFAULT_KEYWORDS),
                "keyword_input": keyword_input,
                "final_results": [],
                "msg": "단축 오류: " + str(e),
                "shortened": None,
                "shorten_fail": [],
                "error_message": str(e)
            }
        )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
