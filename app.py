import os
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from typing import List
import requests
import urllib.parse
import html
from datetime import datetime, timedelta, timezone
import email.utils as eut
import asyncio

# Playwright
from playwright.async_api import async_playwright

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# (static 디렉토리 없으면 주석처리!)
# app.mount("/static", StaticFiles(directory="static"), name="static")

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

press_name_map = {
    "chosun.com": "조선일보", "yna.co.kr": "연합뉴스", "hani.co.kr": "한겨레",
    "joongang.co.kr": "중앙일보", "mbn.co.kr": "MBN", "kbs.co.kr": "KBS",
    "sbs.co.kr": "SBS", "ytn.co.kr": "YTN", "donga.com": "동아일보",
    "segye.com": "세계일보", "munhwa.com": "문화일보", "newsis.com": "뉴시스",
    "naver.com": "네이버", "daum.net": "다음", "kukinews.com": "국민일보",
    "kookbang.dema.mil.kr": "국방일보", "edaily.co.kr": "이데일리",
    "news1.kr": "뉴스1", "mbnmoney.mbn.co.kr": "MBN", "news.kmib.co.kr": "국민일보",
    "jtbc.co.kr": "JTBC"
}

def extract_press_name(url):
    try:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        for key, name in press_name_map.items():
            if domain == key or domain.endswith("." + key):
                return domain, name
        return domain, domain
    except Exception:
        return None, None

def search_news(query):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    return []

def parse_pubdate(pubdate_str):
    try:
        dt = datetime(*eut.parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        return ""

DEFAULT_KEYWORDS = ["육군", "국방", "외교", "안보", "북한", "신병", "교육대", "훈련", "간부", "장교", "부사관", "병사", "용사", "군무원"]

@app.get("/")
async def root(request: Request):
    return RedirectResponse(url="/news", status_code=302)

@app.get("/news")
async def main_get(request: Request):
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "msg": None,
        "final_results": [],
        "selected_urls": [],
        "failed_urls": [],
        "checked_two_keywords": False,
        "search_mode": "major",
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
    })

@app.post("/news")
async def main_post(
    request: Request,
    keywords: str = Form(...),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    selected_urls: List[str] = Form([]),
):
    # 키워드 정리 (신병교육대 → 신병, 교육대로 분리, 중복 제거)
    input_keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    keywords_expanded = []
    for kw in input_keywords:
        if kw == "신병교육대":
            keywords_expanded.extend(["신병", "교육대"])
        else:
            keywords_expanded.append(kw)
    keywords_expanded = list(dict.fromkeys(keywords_expanded))  # 중복제거, 순서유지

    now = datetime.now(timezone(timedelta(hours=9)))
    url_map = {}
    for kw in keywords_expanded:
        items = search_news(kw)
        for a in items:
            title = html.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
            desc = html.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
            url = a["link"]
            pub = parse_pubdate(a.get("pubDate", "")) or ""
            domain, press = extract_press_name(a.get("originallink") or url)
            # 주요 언론사만 보기
            if search_mode == "major" and press not in press_name_map.values():
                continue
            # 4시간 이내만
            try:
                pub_dt = datetime.strptime(pub, "%Y-%m-%d %H:%M")
                if (now - pub_dt).total_seconds() > 60*60*4:
                    continue
            except:
                continue
            # 키워드 매핑
            if url not in url_map:
                url_map[url] = {
                    "title": title,
                    "url": url,
                    "press": press,
                    "pubdate": pub,
                    "matched": [kw],
                }
            else:
                url_map[url]["matched"].append(kw)

    # 2개이상 키워드 필터 (동일 키워드 2번 포함도 인정)
    show_two_kw = bool(checked_two_keywords)
    results = []
    for art in url_map.values():
        if show_two_kw and len(art["matched"]) < 2:
            continue
        art["matched"] = sorted(art["matched"])
        results.append(art)
    results = sorted(results, key=lambda x: x['pubdate'], reverse=True)

    # 선택된 기사 인덱스(없으면 전부 선택)
    if not selected_urls:
        selected_urls = [str(i) for i in range(len(results))]

    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "msg": f"최종 기사 수: {len(results)}",
        "final_results": results,
        "selected_urls": selected_urls,
        "failed_urls": [],
        "checked_two_keywords": show_two_kw,
        "search_mode": search_mode,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
    })

@app.post("/shorten")
async def shorten(
    request: Request,
    keywords: str = Form(...),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    selected_urls: List[str] = Form([]),
):
    # 위와 같은 뉴스 검색 로직 실행 (selected_urls만 대상으로)
    input_keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    keywords_expanded = []
    for kw in input_keywords:
        if kw == "신병교육대":
            keywords_expanded.extend(["신병", "교육대"])
        else:
            keywords_expanded.append(kw)
    keywords_expanded = list(dict.fromkeys(keywords_expanded))
    now = datetime.now(timezone(timedelta(hours=9)))
    url_map = {}
    for kw in keywords_expanded:
        items = search_news(kw)
        for a in items:
            title = html.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
            desc = html.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
            url = a["link"]
            pub = parse_pubdate(a.get("pubDate", "")) or ""
            domain, press = extract_press_name(a.get("originallink") or url)
            if search_mode == "major" and press not in press_name_map.values():
                continue
            try:
                pub_dt = datetime.strptime(pub, "%Y-%m-%d %H:%M")
                if (now - pub_dt).total_seconds() > 60*60*4:
                    continue
            except:
                continue
            if url not in url_map:
                url_map[url] = {
                    "title": title,
                    "url": url,
                    "press": press,
                    "pubdate": pub,
                    "matched": [kw],
                }
            else:
                url_map[url]["matched"].append(kw)

    show_two_kw = bool(checked_two_keywords)
    results = []
    for art in url_map.values():
        if show_two_kw and len(art["matched"]) < 2:
            continue
        art["matched"] = sorted(art["matched"])
        results.append(art)
    results = sorted(results, key=lambda x: x['pubdate'], reverse=True)

    # 변환 시도
    failed_urls = []
    updated_results = []
    if selected_urls:
        # selected_urls는 인덱스(str) 리스트
        for idx, art in enumerate(results):
            if str(idx) not in selected_urls:
                updated_results.append(art)
                continue
            # 네이버 뉴스만 단축
            if art["url"].startswith("https://n.news.naver.com/"):
                try:
                    new_url, reason = await get_naverme_url(art["url"])
                    if new_url:
                        art["url"] = new_url
                    else:
                        failed_urls.append({
                            "title": art["title"], "press": art["press"],
                            "url": art["url"], "reason": reason or "Playwright 오류"
                        })
                except Exception as e:
                    failed_urls.append({
                        "title": art["title"], "press": art["press"],
                        "url": art["url"], "reason": str(e)
                    })
            updated_results.append(art)
    else:
        updated_results = results

    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "msg": f"최종 기사 수: {len(updated_results)} (단축실패 {len(failed_urls)})",
        "final_results": updated_results,
        "selected_urls": selected_urls,
        "failed_urls": failed_urls,
        "checked_two_keywords": bool(checked_two_keywords),
        "search_mode": search_mode,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
    })

# Playwright 비동기 함수(대표 selector 예시, selector_finder 확장 가능)
async def get_naverme_url(news_url):
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 13_3 like Mac OS X) "
                           "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.4 Mobile/15E148 Safari/604.1"
            )
            await page.goto(news_url)
            # 네이버 뉴스 공유 버튼 selector (대표예시)
            await page.wait_for_selector("#spiButton", timeout=7000)
            await page.click("#spiButton")
            # naver.me 링크 버튼이 보일 때까지 대기
            await page.wait_for_selector('a[href^="https://naver.me"]', timeout=7000)
            elem = await page.query_selector('a[href^="https://naver.me"]')
            short_url = await elem.get_attribute('href')
            await browser.close()
            return short_url, None
    except Exception as e:
        return None, f"Playwright 오류: {e}"
