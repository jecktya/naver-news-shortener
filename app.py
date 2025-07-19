# app.py
# -*- coding: utf-8 -*-
import os
import re
import html
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx

# 로깅
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

PRESS_MAJOR = {
    "조선일보", "연합뉴스", "한겨레", "중앙일보", "MBN", "KBS", "SBS", "YTN", "동아일보",
    "세계일보", "문화일보", "뉴시스", "네이버", "다음", "국민일보", "국방일보", "이데일리",
    "뉴스1", "JTBC"
}
DEFAULT_KEYWORDS = [
    "육군", "국방", "외교", "안보", "북한", "신병", "교육대", "훈련", "간부",
    "장교", "부사관", "병사", "용사", "군무원"
]

app = FastAPI()
templates = Jinja2Templates(directory="templates")

def clean_html_tags(text):
    if not text: return ""
    text = html.unescape(text)
    return re.sub(r'<[^>]+>', '', text)

def extract_press(item):
    return item.get("publisher") or ""

def parse_pubdate(pubdate_str):
    try:
        dt = parsedate_to_datetime(pubdate_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))
        return dt
    except Exception as e:
        logger.warning(f"pubDate '{pubdate_str}' 파싱 실패: {e}")
        return None

async def search_news_naver(keyword, display=20, max_retries=2):
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": keyword,
        "display": display,
        "sort": "date"
    }
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                logger.info(f"[API 호출] {attempt + 1}/{max_retries} | 쿼리: '{keyword}'")
                res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
                res.raise_for_status()
                return res.json().get("items", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"[API 오류] 429 Too Many Requests. 재시도...(남은시도:{max_retries-1-attempt})")
                await asyncio.sleep(2 ** attempt)
            else:
                logger.error(f"[API 오류] HTTP {e.response.status_code} - {e.response.text}", exc_info=True)
                raise
        except Exception as e:
            logger.error(f"[API 오류] {e}", exc_info=True)
            raise
    return []

async def get_naverme_from_news(url: str) -> str:
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return "Playwright 미설치"
    async with async_playwright() as p:
        iphone_ua = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
        iphone_vp = {"width": 428, "height": 926}
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox'])
        page = await browser.new_page(viewport=iphone_vp, user_agent=iphone_ua)
        await page.goto(url, timeout=20000)
        await asyncio.sleep(2)
        try:
            await page.click("span.u_hc", timeout=3000)
            await asyncio.sleep(1.2)
        except Exception:
            pass
        html_content = await page.content()
        match = re.search(r'https://naver\.me/[a-zA-Z0-9]+', html_content)
        await browser.close()
        if match:
            return match.group(0)
        else:
            return "naver.me 주소를 찾을 수 없음"

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    now = datetime.now(timezone(timedelta(hours=9)))
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "keyword_input": ', '.join(DEFAULT_KEYWORDS),
            "final_articles": [],
            "search_mode": "전체",
            "now": now.strftime('%Y-%m-%d %H:%M:%S'),
            "msg": None,
            "selected_urls": [],
            "naverme_map": {}
        }
    )

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(""),
    search_mode: str = Form("전체"),
    selected_urls: list = Form(None),
):
    now = datetime.now(timezone(timedelta(hours=9)))
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keyword_list:
        keyword_list = DEFAULT_KEYWORDS
    logger.info(f"[검색] POST | 키워드={keywords} | 검색모드={search_mode}")

    url_map = dict()
    try:
        semaphore = asyncio.Semaphore(5)
        async def limited_search(kw):
            async with semaphore:
                return await search_news_naver(kw, display=15)
        tasks = [limited_search(kw) for kw in keyword_list]
        result_lists = await asyncio.gather(*tasks)
        # 기사 중복 병합 및 키워드 매칭
        for idx, items in enumerate(result_lists):
            kw = keyword_list[idx]
            for a in items:
                title = clean_html_tags(a.get("title", ""))
                desc = clean_html_tags(a.get("description", ""))
                url = a.get("link", "")
                press = extract_press(a)
                pub = parse_pubdate(a.get("pubDate", ""))
                if not url: continue
                haystack = f"{title} {desc}"
                # 포함된 키워드 모두 체크
                matched_keywords = set()
                for check_kw in keyword_list:
                    if check_kw in haystack:
                        matched_keywords.add(check_kw)
                if len(matched_keywords) < 2:  # 2개 이상 포함 아니면 건너뜀
                    continue
                if url not in url_map:
                    url_map[url] = {
                        "title": title,
                        "desc": desc,
                        "url": url,
                        "press": press,
                        "pubdate": pub,
                        "matched": matched_keywords,
                    }
                else:
                    url_map[url]["matched"].update(matched_keywords)
        articles = []
        for v in url_map.values():
            # 4시간 이내
            if not v["pubdate"] or (now - v["pubdate"] > timedelta(hours=4)):
                continue
            if search_mode == "주요언론사만" and v["press"] not in PRESS_MAJOR:
                continue
            articles.append(v)
        # 정렬: 최신순
        sorted_articles = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
        msg = f"검색 결과: {len(sorted_articles)}건 (4시간 이내, 2개 이상 키워드 포함)"
        for art in sorted_articles:
            art["pubdate_str"] = art["pubdate"].strftime('%Y-%m-%d %H:%M') if art["pubdate"] else ""
            art["matched_list"] = sorted(list(art["matched"]))
            art["matched_count"] = len(art["matched"])
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": ', '.join(keyword_list),
                "final_articles": sorted_articles,
                "search_mode": search_mode,
                "now": now.strftime('%Y-%m-%d %H:%M:%S'),
                "msg": msg,
                "selected_urls": [],
                "naverme_map": {}
            }
        )
    except Exception as e:
        logger.error(f"[검색] 오류: {e}", exc_info=True)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": ', '.join(keyword_list),
                "final_articles": [],
                "search_mode": search_mode,
                "now": now.strftime('%Y-%m-%d %H:%M:%S'),
                "msg": f"오류: {e}",
                "selected_urls": [],
                "naverme_map": {}
            }
        )

@app.post("/naverme", response_class=HTMLResponse)
async def post_naverme(
    request: Request,
    keyword_input: str = Form(...),
    search_mode: str = Form(...),
    selected_urls: list = Form(...),
):
    now = datetime.now(timezone(timedelta(hours=9)))
    try:
        import json
        url_list = selected_urls if isinstance(selected_urls, list) else json.loads(selected_urls)
        # 실제 기사 정보 재검색(최신)
        keyword_list = [k.strip() for k in keyword_input.split(",") if k.strip()]
        if not keyword_list:
            keyword_list = DEFAULT_KEYWORDS
        semaphore = asyncio.Semaphore(5)
        async def limited_search(kw):
            async with semaphore:
                return await search_news_naver(kw, display=15)
        tasks = [limited_search(kw) for kw in keyword_list]
        result_lists = await asyncio.gather(*tasks)
        url_map = {}
        for idx, items in enumerate(result_lists):
            kw = keyword_list[idx]
            for a in items:
                title = clean_html_tags(a.get("title", ""))
                desc = clean_html_tags(a.get("description", ""))
                url = a.get("link", "")
                press = extract_press(a)
                pub = parse_pubdate(a.get("pubDate", ""))
                if not url: continue
                haystack = f"{title} {desc}"
                matched_keywords = set()
                for check_kw in keyword_list:
                    if check_kw in haystack:
                        matched_keywords.add(check_kw)
                if len(matched_keywords) < 2: continue
                if url not in url_map:
                    url_map[url] = {
                        "title": title,
                        "desc": desc,
                        "url": url,
                        "press": press,
                        "pubdate": pub,
                        "matched": matched_keywords,
                    }
                else:
                    url_map[url]["matched"].update(matched_keywords)
        articles = []
        for v in url_map.values():
            if not v["pubdate"] or (now - v["pubdate"] > timedelta(hours=4)):
                continue
            if search_mode == "주요언론사만" and v["press"] not in PRESS_MAJOR:
                continue
            articles.append(v)
        sorted_articles = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
        for art in sorted_articles:
            art["pubdate_str"] = art["pubdate"].strftime('%Y-%m-%d %H:%M') if art["pubdate"] else ""
            art["matched_list"] = sorted(list(art["matched"]))
            art["matched_count"] = len(art["matched"])
        # 선택된 기사에 대해 네이버미 변환
        naverme_map = {}
        for url in url_list:
            naverme_map[url] = await get_naverme_from_news(url)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": ', '.join(keyword_list),
                "final_articles": sorted_articles,
                "search_mode": search_mode,
                "now": now.strftime('%Y-%m-%d %H:%M:%S'),
                "msg": f"선택 {len(url_list)}건 네이버me 변환 결과",
                "selected_urls": url_list,
                "naverme_map": naverme_map
            }
        )
    except Exception as e:
        logger.error(f"[네이버미] 오류: {e}", exc_info=True)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": keyword_input,
                "final_articles": [],
                "search_mode": search_mode,
                "now": now.strftime('%Y-%m-%d %H:%M:%S'),
                "msg": f"naverme 오류: {e}",
                "selected_urls": [],
                "naverme_map": {}
            }
        )
