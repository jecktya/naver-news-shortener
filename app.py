# app.py

import os
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from selector_finder import find_and_click_share
from playwright.async_api import async_playwright
from starlette.responses import JSONResponse
from datetime import datetime, timedelta, timezone
import requests
import urllib.parse
import html as html_util

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

templates = Jinja2Templates(directory="templates")
app = FastAPI()

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
    import urllib.parse
    try:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        for key, name in press_name_map.items():
            if domain == key or domain.endswith("." + key):
                return domain, name
        return domain, domain
    except Exception:
        return None, None

def parse_pubdate(pubdate_str):
    import email.utils as eut
    try:
        dt = datetime(*eut.parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except:
        return None

def convert_to_mobile_link(url):
    if "n.news.naver.com/article" in url:
        return url.replace("n.news.naver.com/article", "n.news.naver.com/mnews/article")
    return url

def search_news(query, search_mode="주요언론사만"):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        items = r.json().get("items", [])
        now = datetime.now(timezone(timedelta(hours=9)))
        url_map = {}
        for a in items:
            title = html_util.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
            desc = html_util.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
            url = a["link"]
            pub = parse_pubdate(a.get("pubDate", "")) or datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))
            domain, press = extract_press_name(a.get("originallink") or url)
            if not pub or (now - pub > timedelta(hours=4)):
                continue
            if search_mode == "주요언론사만" and press not in press_name_map.values():
                continue
            # 중복 관리
            if url not in url_map:
                url_map[url] = {
                    "title": title,
                    "url": url,
                    "press": press,
                    "pubdate": pub,
                    "matched": set([query])
                }
            else:
                url_map[url]["matched"].add(query)
        articles = []
        for v in url_map.values():
            v["matched"] = sorted(v["matched"])
            articles.append(v)
        sorted_list = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
        return sorted_list
    return []

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    def_keywords = ["육군", "국방", "외교", "안보", "북한",
                    "신병교육대", "훈련", "간부", "장교",
                    "부사관", "병사", "용사", "군무원"]
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "def_keywords": ", ".join(def_keywords),
        "articles": [],
        "search_mode": "주요언론사만"
    })

@app.post("/search", response_class=HTMLResponse)
async def do_search(request: Request, input_keywords: str = Form(...), search_mode: str = Form(...)):
    keyword_list = [k.strip() for k in input_keywords.split(",") if k.strip()]
    articles = []
    for kw in keyword_list:
        articles += search_news(kw, search_mode=search_mode)
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "def_keywords": input_keywords,
        "articles": articles,
        "search_mode": search_mode
    })

@app.post("/shorten", response_class=HTMLResponse)
async def do_shorten(request: Request, selected_keys: str = Form(...), titles: str = Form(...), presses: str = Form(...)):
    urls = selected_keys.split('\n')
    titles = titles.split('\n')
    presses = presses.split('\n')
    short_results = []
    for i, url in enumerate(urls):
        press = presses[i] if i < len(presses) else ""
        title = titles[i] if i < len(titles) else ""
        short_url, err = await get_short_url(url, press)
        if short_url:
            short_results.append(f"■ {title} ({press})\n{short_url}")
        else:
            short_results.append(f"■ {title} ({press})\n{url}\n[Playwright 오류: {err}]")
    final_txt = "\n\n".join(short_results)
    return templates.TemplateResponse("short_result.html", {
        "request": request,
        "final_txt": final_txt
    })

async def get_short_url(news_url, press_name):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Linux; Android 11; SM-G991N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/95.0.4638.74 Mobile Safari/537.36"
        )
        page = await context.new_page()
        await page.goto(news_url)
        selector = await find_and_click_share(page, press_name)
        if selector is None:
            await browser.close()
            return None, "공유버튼 selector를 찾지 못함"
        # 공유 버튼 클릭 후, 네이버미 주소 추출
        import re
        content = await page.content()
        urls = re.findall(r"https://naver\.me/\w+", content)
        short_url = urls[0] if urls else None
        await browser.close()
        return short_url, None if short_url else "단축주소 찾지 못함"
