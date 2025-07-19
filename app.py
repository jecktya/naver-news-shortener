# -*- coding: utf-8 -*-
import os
import re
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx
import json

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

app = FastAPI()
templates = Jinja2Templates(directory="templates")

PRESS_MAJOR = {
    "조선일보", "연합뉴스", "한겨레", "중앙일보", "MBN", "KBS", "SBS", "YTN", "동아일보",
    "세계일보", "문화일보", "뉴시스", "네이버", "다음", "국민일보", "국방일보", "이데일리",
    "뉴스1", "JTBC"
}
DEFAULT_KEYWORDS = [
    "육군", "국방", "외교", "안보", "북한", "신병", "교육대", "훈련", "간부",
    "장교", "부사관", "병사", "용사", "군무원"
]

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

def clean_html_tags(text):
    return re.sub(r'<[^>]+>', '', text or "")

async def search_news_naver(keyword, display=15, max_retries=3):
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": keyword, "display": display, "sort": "date"}
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                logger.info(f"[API] HTTP Request: GET {NAVER_NEWS_API_URL}?query={keyword}")
                res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
                res.raise_for_status()
                return res.json().get("items", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"[API] 429 Too Many Requests. (재시도 {attempt+1})")
                await asyncio.sleep(2 ** attempt)
            else:
                logger.error(f"[API] HTTP Error: {e.response.status_code}")
                raise
        except Exception as e:
            logger.error(f"[API] Unexpected Error: {e}")
            raise
    logger.error("[API] 모든 재시도 실패")
    return []

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
        }
    )

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(""),
    search_mode: str = Form("전체"),
):
    now = datetime.now(timezone(timedelta(hours=9)))
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if len(keyword_list) < 2:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": ', '.join(keyword_list),
                "final_articles": [],
                "search_mode": search_mode,
                "now": now.strftime('%Y-%m-%d %H:%M:%S'),
                "msg": "키워드는 2개 이상 입력하세요.",
            }
        )
    logger.info(f"[검색] POST | 키워드={keywords} | 검색모드={search_mode}")

    url_map = dict()
    try:
        semaphore = asyncio.Semaphore(5)
        async def limited_search(kw):
            async with semaphore:
                return await search_news_naver(kw, display=15)
        tasks = [limited_search(kw) for kw in keyword_list]
        result_lists = await asyncio.gather(*tasks)

        # 기사 병합: 모든 키워드에 대해 등장한 기사 url별로 matched 집합 관리
        for idx, items in enumerate(result_lists):
            kw = keyword_list[idx]
            for a in items:
                title = clean_html_tags(a.get("title", ""))
                desc = clean_html_tags(a.get("description", ""))
                url = a.get("link", "")
                press = extract_press(a)
                pub = parse_pubdate(a.get("pubDate", ""))
                if not url:
                    continue
                if url not in url_map:
                    url_map[url] = {
                        "title": title,
                        "desc": desc,
                        "url": url,
                        "press": press,
                        "pubdate": pub,
                        "matched": set(),
                    }
                # 제목/내용에 키워드 포함 여부
                haystack = f"{title} {desc}"
                if kw in haystack:
                    url_map[url]["matched"].add(kw)

        # '모든 키워드'가 포함된 기사만
        articles = []
        for v in url_map.values():
            if not v["pubdate"] or (now - v["pubdate"] > timedelta(hours=4)):
                continue
            if len(v["matched"]) != len(keyword_list):  # **모든 키워드 포함**
                continue
            if search_mode == "주요언론사만" and v["press"] not in PRESS_MAJOR:
                continue
            v["pubdate_str"] = v["pubdate"].strftime('%Y-%m-%d %H:%M') if v["pubdate"] else ""
            v["matched"] = list(v["matched"])  # set→list 변환!
            articles.append(v)

        sorted_articles = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
        msg = f"검색 결과: {len(sorted_articles)}건 (4시간 이내, {len(keyword_list)}개 키워드 모두 포함)"
        logger.info(f"[검색] 최종 기사수: {len(sorted_articles)}")

        # JSON 직렬화 위해 set → list로 변환
        for art in sorted_articles:
            if isinstance(art.get("matched"), set):
                art["matched"] = list(art["matched"])

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": ', '.join(keyword_list),
                "final_articles": sorted_articles,
                "search_mode": search_mode,
                "now": now.strftime('%Y-%m-%d %H:%M:%S'),
                "msg": msg,
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
            }
        )

# --- 네이버미 변환 Dummy 함수 (여기에 Playwright 코드 연동 가능) ---
async def get_naverme_from_news(url: str) -> str:
    # 실제로는 Playwright 등으로 변환
    # 예시: return await 실제변환함수(url)
    return f"https://naver.me/fakecode123"  # 데모용

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: str = Form(...),
    final_articles_json: str = Form(...),
    keyword_input: str = Form(""),
    search_mode: str = Form("전체"),
):
    try:
        selected = json.loads(selected_urls)
        articles = json.loads(final_articles_json)
        results = []
        for url in selected:
            art = next((a for a in articles if a['url'] == url), None)
            if not art:
                continue
            naverme = await get_naverme_from_news(url)
            results.append({
                "title": art['title'],
                "press": art['press'],
                "naverme": naverme,
                "pubdate_str": art.get("pubdate_str", "")
            })
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": keyword_input,
                "final_articles": articles,
                "search_mode": search_mode,
                "now": datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S'),
                "msg": f"네이버미 변환 결과 {len(results)}건",
                "shortened": results,
            }
        )
    except Exception as e:
        logger.error(f"[단축주소] 오류: {e}", exc_info=True)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": keyword_input,
                "final_articles": [],
                "search_mode": search_mode,
                "now": datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M:%S'),
                "msg": f"단축주소 오류: {e}",
            }
        )
