import os
import urllib.parse
import html
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from typing import List, Optional
import requests
import asyncio

from playwright.async_api import async_playwright

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

TEMPLATE_KWS = ["육군", "국방", "외교", "안보", "북한",
                "신병교육대", "훈련", "간부", "장교", "부사관", "병사", "용사", "군무원"]

templates = Jinja2Templates(directory="templates")
app = FastAPI()

def extract_press_name(url):
    try:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        return domain
    except Exception:
        return None

def parse_pubdate(pubdate_str):
    try:
        from email.utils import parsedate
        dt = datetime(*parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except:
        return None

def is_naver_news_url(url):
    return url.startswith("https://n.news.naver.com/")

async def get_naverme_url(news_url):
    """Playwright를 사용해 네이버 뉴스에서 naver.me 단축주소 가져오기"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 13_5_1 like Mac OS X)")
            await page.goto(news_url)
            await page.wait_for_selector('#spiButton', timeout=7000)
            await page.click('#spiButton')
            await page.wait_for_selector('input#spiInput', timeout=7000)
            short_url = await page.get_attribute('input#spiInput', 'value')
            await browser.close()
            return short_url or news_url
    except Exception as e:
        return f"[Playwright 오류: {str(e)}] {news_url}"

def search_news(query):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    else:
        return []

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    default_keywords = ", ".join(TEMPLATE_KWS)
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": default_keywords,
        "final_results": None,
        "selected_urls": [],
        "msg": "",
        "checked_two_keywords": False,
        "search_mode": "major"
    })

@app.post("/", response_class=HTMLResponse)
async def news_search(
    request: Request,
    keywords: str = Form(""),
    checked_two_keywords: Optional[str] = Form(None),
    search_mode: str = Form("major")
):
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    now = datetime.now(timezone(timedelta(hours=9)))
    url_map = {}

    # 여러 키워드에 대해 기사 수집 및 키워드별 매핑
    for kw in keyword_list:
        items = search_news(kw)
        for a in items:
            title = html.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
            url = a["link"]
            pub = parse_pubdate(a.get("pubDate", "")) or datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))
            press = extract_press_name(a.get("originallink") or url)
            if not pub or (now - pub > timedelta(hours=4)):
                continue
            if search_mode == "major":
                # 주요 언론사만 (예시: naver.com, yna.co.kr 등) → 필요시 주요 언론사 도메인 목록 만들어서 체크
                if not press or not any(x in press for x in ["naver", "yna", "hani", "chosun", "joongang", "donga", "sbs", "kbs", "mbn", "ytn", "newsis"]):
                    continue
            # 키워드별 매핑/중복 처리
            if url not in url_map:
                url_map[url] = {
                    "title": title,
                    "url": url,
                    "press": press,
                    "pubdate": pub,
                    "matched": set([kw])
                }
            else:
                url_map[url]["matched"].add(kw)

    # "2개 이상 키워드 포함" 옵션 적용
    articles = []
    for v in url_map.values():
        if checked_two_keywords and len(v["matched"]) < 2:
            continue
        v["matched"] = sorted(v["matched"])
        articles.append(v)
    sorted_list = sorted(articles, key=lambda x: x['pubdate'], reverse=True)

    msg = f"검색결과 {len(sorted_list)}건 (검색어: {keywords})"
    default_keywords = ", ".join(TEMPLATE_KWS)

    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": default_keywords,
        "final_results": sorted_list,
        "selected_urls": [a['url'] for a in sorted_list],
        "msg": msg,
        "checked_two_keywords": bool(checked_two_keywords),
        "search_mode": search_mode
    })

@app.post("/shorten", response_class=JSONResponse)
async def shorten_urls(urls: List[str] = Form(...)):
    # 네이버뉴스 주소만 변환, 그 외는 원본
    results = []
    for url in urls:
        if is_naver_news_url(url):
            short_url = await get_naverme_url(url)
        else:
            short_url = url
        results.append(short_url)
    return {"shortened": results}
