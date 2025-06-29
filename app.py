# -*- coding: utf-8 -*-
import os
import urllib.parse
import html
import asyncio
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import httpx
from collections import Counter
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright

# 기본값
DEFAULT_KEYWORDS = ["육군", "국방", "외교", "안보", "북한", "신병", "교육대", "훈련", "간부", "장교", "부사관", "병사", "용사", "군무원"]
PRESS_NAME_MAP = {
    "chosun.com": "조선일보", "yna.co.kr": "연합뉴스", "hani.co.kr": "한겨레",
    "joongang.co.kr": "중앙일보", "mbn.co.kr": "MBN", "kbs.co.kr": "KBS",
    "sbs.co.kr": "SBS", "ytn.co.kr": "YTN", "donga.com": "동아일보",
    "segye.com": "세계일보", "munhwa.com": "문화일보", "newsis.com": "뉴시스",
    "naver.com": "네이버", "daum.net": "다음", "kukinews.com": "국민일보",
    "kookbang.dema.mil.kr": "국방일보", "edaily.co.kr": "이데일리",
    "news1.kr": "뉴스1", "mbnmoney.mbn.co.kr": "MBN", "news.kmib.co.kr": "국민일보",
    "jtbc.co.kr": "JTBC"
}
MAJOR_PRESS = set(PRESS_NAME_MAP.values())

app = FastAPI()
templates = Jinja2Templates(directory="templates")

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET")

def extract_press_name(url):
    try:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        for key, name in PRESS_NAME_MAP.items():
            if domain == key or domain.endswith("." + key):
                return name
        return domain
    except:
        return "기타"

def parse_pubdate(pubdate_str):
    try:
        from email.utils import parsedate
        dt = datetime(*parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except:
        return None

async def search_news(keywords, search_mode, checked_two_keywords):
    url_map = {}
    article_kwcount = {}
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    now = datetime.now(timezone(timedelta(hours=9)))
    async with httpx.AsyncClient(timeout=10) as client:
        for kw in keywords:
            enc = urllib.parse.quote(kw)
            url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
            r = await client.get(url, headers=headers)
            if r.status_code != 200:
                continue
            items = r.json().get("items", [])
            for a in items:
                title = html.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
                desc = html.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
                link = a["link"]
                pub = parse_pubdate(a.get("pubDate", "")) or datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))
                press = extract_press_name(a.get("originallink") or link)

                # 4시간 내 기사만
                if not pub or (now - pub > timedelta(hours=4)):
                    continue
                # 주요언론사 필터
                if search_mode == "major" and press not in MAJOR_PRESS:
                    continue

                # 키워드 포함수 계산
                match_count = sum(1 for k in keywords if k in title or k in desc)
                # 2개이상 키워드 체크
                if checked_two_keywords and match_count < 2:
                    continue

                if link not in url_map:
                    url_map[link] = {
                        "title": title, "press": press, "url": link,
                        "pubdate": pub, "matched": [], "match_count": match_count
                    }
                url_map[link]["matched"] += [k for k in keywords if k in title or k in desc]
                url_map[link]["match_count"] = match_count
    articles = []
    for v in url_map.values():
        # 키워드 중복 카운팅
        counter = Counter(v["matched"])
        sorted_kws = sorted(counter.items(), key=lambda x: -x[1])
        v["matched_str"] = ", ".join([f"{k}({n})" if n > 1 else k for k, n in sorted_kws])
        v["match_count"] = sum(count for _, count in sorted_kws)
        articles.append(v)
    # 키워드 많은 순 정렬
    articles = sorted(articles, key=lambda x: (-x["match_count"], -x["pubdate"].timestamp()))
    return articles

@app.get("/", response_class=HTMLResponse)
async def get_main(request: Request):
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "final_results": None,
        "msg": "",
        "checked_two_keywords": False,
        "search_mode": "major"
    })

@app.post("/", response_class=HTMLResponse)
async def main(
    request: Request,
    keywords: str = Form(...),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    selected_urls: str = Form(None)
):
    msg = ""
    try:
        # 키워드 처리
        kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
        checked = bool(checked_two_keywords)
        articles = await search_news(kw_list, search_mode, checked)
        # 결과가져오기
        for a in articles:
            a["pubdate_str"] = a["pubdate"].strftime("%Y-%m-%d %H:%M")
        # selected_urls
        selected = selected_urls.split(",") if selected_urls else [a["url"] for a in articles]
        return templates.TemplateResponse("news_search.html", {
            "request": request,
            "default_keywords": ", ".join(kw_list),
            "final_results": articles,
            "msg": f"검색결과: {len(articles)}건",
            "checked_two_keywords": checked,
            "search_mode": search_mode,
            "selected_urls": selected,
        })
    except Exception as e:
        msg = f"오류: {e}"
        return templates.TemplateResponse("news_search.html", {
            "request": request,
            "default_keywords": keywords,
            "final_results": [],
            "msg": msg,
            "checked_two_keywords": checked_two_keywords,
            "search_mode": search_mode
        })

@app.post("/shorten", response_class=JSONResponse)
async def shorten_api(request: Request):
    data = await request.json()
    url_list = data.get("urls", [])
    result_map = {}
    fail_map = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) "
                       "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1"
        )
        for url in url_list:
            try:
                if url.startswith("https://n.news.naver.com/"):
                    page = await context.new_page()
                    await page.goto(url, timeout=8000)
                    # 공유버튼 selector (네이버 뉴스 모바일 기준)
                    try:
                        await page.wait_for_selector('span.u_hc', timeout=5000)
                        await page.click('span.u_hc')
                    except:
                        try:
                            await page.wait_for_selector('#spiButton > span > span', timeout=5000)
                            await page.click('#spiButton > span > span')
                        except Exception as e:
                            fail_map[url] = "공유 버튼 selector 찾지 못함"
                            continue
                    await asyncio.sleep(1.2)
                    # 링크 복사 영역의 input 가져오기 (naver.me)
                    try:
                        await page.wait_for_selector('input#spiInput', timeout=4000)
                        short_url = await page.input_value('input#spiInput')
                        result_map[url] = short_url
                    except Exception as e:
                        fail_map[url] = "링크 복사 input 찾지 못함"
                    await page.close()
                else:
                    # 변환 대상 아님
                    continue
            except Exception as e:
                fail_map[url] = f"Playwright 오류: {e}"
        await browser.close()
    return {"result": result_map, "fail": fail_map}
