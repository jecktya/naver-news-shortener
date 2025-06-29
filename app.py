import os
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from datetime import datetime, timedelta, timezone
import urllib.parse, html, email.utils as eut
import requests
import asyncio

from playwright.async_api import async_playwright

app = FastAPI()
templates = Jinja2Templates(directory="templates")

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

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
    except Exception as e:
        return None, None

def parse_pubdate(pubdate_str):
    try:
        dt = datetime(*eut.parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except:
        return None

async def get_short_url(long_url, debug_msgs):
    """네이버 단축주소를 playwright로 크롤링해서 반환 (실제 구현 예시)"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://me2.do/")  # 예시: naver.me/를 자동으로 생성해주는 사이트 필요
            # [실제 구현은 네이버 단축주소 생성 페이지로 이동해서 form 입력, 결과 추출이 필요합니다]
            # 이 부분은 실제 네이버 단축주소 발급페이지 구조에 맞게 맞추세요!
            # 예시 코드: 실제 동작하려면 맞춤 수정 필요
            # await page.fill("input[name='url']", long_url)
            # await page.click("button[type='submit']")
            # await page.wait_for_selector(".result-link")
            # short_url = await page.input_value(".result-link")
            # ---- 실제 구현 전용 코드 필요 ----
            short_url = long_url  # 디버깅용 (실제 단축URL 코드로 교체 필요)
            await browser.close()
        debug_msgs.append(f"Playwright 성공: {long_url} → {short_url}")
        return short_url
    except Exception as e:
        debug_msgs.append(f"Playwright 오류: {e}")
        return long_url

@app.get("/", response_class=HTMLResponse)
async def search_form(request: Request):
    return templates.TemplateResponse("news_search.html", {"request": request, "results": None, "debug_msgs": []})

@app.post("/", response_class=HTMLResponse)
async def search_news(request: Request, keywords: str = Form(...)):
    debug_msgs = []
    try:
        now = datetime.now(timezone(timedelta(hours=9)))
        debug_msgs.append(f"검색 키워드: {keywords}")
        NAVER_CLIENT_ID and NAVER_CLIENT_SECRET or debug_msgs.append("❌ NAVER API KEY 없음!")
        headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
        results = []
        url_map = {}
        for kw in [k.strip() for k in keywords.split(",") if k.strip()]:
            enc = urllib.parse.quote(kw)
            url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=10&sort=date"
            debug_msgs.append(f"API URL: {url}")
            try:
                r = requests.get(url, headers=headers)
                debug_msgs.append(f"응답코드 {r.status_code}")
                if r.status_code == 200:
                    items = r.json().get("items", [])
                    debug_msgs.append(f"{kw} 결과 {len(items)}건")
                    for a in items:
                        try:
                            title = html.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
                            desc = html.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
                            urlx = a["link"]
                            pub = parse_pubdate(a.get("pubDate", "")) or datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))
                            domain, press = extract_press_name(a.get("originallink") or urlx)
                            if not pub or (now - pub > timedelta(hours=4)):
                                continue
                            if urlx not in url_map:
                                url_map[urlx] = {
                                    "title": title, "desc": desc, "url": urlx, "press": press, "pubdate": pub, "matched": set([kw])
                                }
                            else:
                                url_map[urlx]["matched"].add(kw)
                        except Exception as e:
                            debug_msgs.append(f"기사 처리 예외: {e}")
                else:
                    debug_msgs.append(f"API 에러: {r.text}")
            except Exception as e:
                debug_msgs.append(f"API 예외: {e}")

        articles = []
        for v in url_map.values():
            v["matched"] = sorted(v["matched"])
            articles.append(v)
        articles = sorted(articles, key=lambda x: x['pubdate'], reverse=True)

        # Playwright로 모든 기사 url을 단축url로 변환 (순차적으로 실행)
        for art in articles:
            art["short_url"] = await get_short_url(art["url"], debug_msgs)

        debug_msgs.append(f"최종 기사 수: {len(articles)}")
        return templates.TemplateResponse(
            "news_search.html",
            {"request": request, "results": articles, "debug_msgs": debug_msgs, "now": now.strftime("%Y-%m-%d %H:%M")}
        )
    except Exception as e:
        debug_msgs.append(f"전체 예외: {e}")
        return templates.TemplateResponse("news_search.html", {"request": request, "results": None, "debug_msgs": debug_msgs})
