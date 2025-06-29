import os
import urllib.parse, html, email.utils as eut
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, Form, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

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
    except Exception:
        return None, None

def parse_pubdate(pubdate_str):
    try:
        dt = datetime(*eut.parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except:
        return None

async def get_short_url(long_url, debug_msgs):
    """실제 서비스 시, 네이버 단축주소 발급 사이트 구조 맞춰 수정!"""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto("https://me2.do/")  # 임시 예시
            # 실제 동작 코드는 네이버 단축주소 발급 사이트에 맞춰 커스터마이즈 필요!
            short_url = long_url  # 실서비스용은 이 부분을 교체
            await browser.close()
        debug_msgs.append(f"Playwright: {long_url} → {short_url}")
        return short_url
    except Exception as e:
        debug_msgs.append(f"Playwright 오류: {e}")
        return long_url

@app.get("/", response_class=HTMLResponse)
async def get_form(request: Request):
    now = datetime.now(timezone(timedelta(hours=9)))
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "results": [],
        "selected": [],
        "search_mode": "전체",
        "keywords": "",
        "debug_msgs": [],
        "now": now.strftime("%Y-%m-%d %H:%M"),
    })

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(...),
    search_mode: str = Form("전체"),
    selected: list = Form(None)
):
    debug_msgs = []
    now = datetime.now(timezone(timedelta(hours=9)))
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        debug_msgs.append("❗ 네이버 API 키 환경변수 미설정")
        return templates.TemplateResponse("news_search.html", {
            "request": request, "results": [], "selected": [],
            "search_mode": search_mode, "keywords": keywords,
            "debug_msgs": debug_msgs, "now": now.strftime("%Y-%m-%d %H:%M"),
        })

    # 키워드 리스트 생성
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    url_map = {}
    for kw in keyword_list:
        enc = urllib.parse.quote(kw)
        url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
        headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
        try:
            r = requests.get(url, headers=headers)
            if r.status_code == 200:
                items = r.json().get("items", [])
                for a in items:
                    title = html.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
                    desc = html.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
                    urlx = a["link"]
                    pub = parse_pubdate(a.get("pubDate", "")) or datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))
                    domain, press = extract_press_name(a.get("originallink") or urlx)

                    # 4시간 필터
                    if not pub or (now - pub > timedelta(hours=4)):
                        continue
                    # 주요언론 모드
                    if search_mode == "주요언론사만" and press not in press_name_map.values():
                        continue
                    # 동영상 모드
                    if search_mode == "동영상만":
                        video_keys = ["영상", "동영상", "영상보기", "보러가기", "뉴스영상", "영상뉴스", "클릭하세요", "바로보기"]
                        video_text = any(k in desc for k in video_keys) or any(k in title for k in video_keys)
                        video_url = any(p in urlx for p in ["/v/", "/video/", "vid="])
                        if not (video_text or video_url):
                            continue

                    # 중복 URL 관리 및 키워드 매핑
                    if urlx not in url_map:
                        url_map[urlx] = {
                            "title": title,
                            "desc": desc,
                            "url": urlx,
                            "press": press,
                            "pubdate": pub,
                            "matched": set([kw]),
                        }
                    else:
                        url_map[urlx]["matched"].add(kw)
            else:
                debug_msgs.append(f"API({kw}) 오류: {r.status_code} {r.text}")
        except Exception as e:
            debug_msgs.append(f"API({kw}) 요청 예외: {e}")

    articles = []
    for v in url_map.values():
        v["matched"] = sorted(v["matched"])
        articles.append(v)
    articles = sorted(articles, key=lambda x: x['pubdate'], reverse=True)

    # 모든 기사 url 단축주소화 (순차, 병렬화 필요시 gather 등 사용)
    for art in articles:
        art["short_url"] = await get_short_url(art["url"], debug_msgs)

    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "results": articles,
        "selected": selected or [a["url"] for a in articles],
        "search_mode": search_mode,
        "keywords": keywords,
        "debug_msgs": debug_msgs,
        "now": now.strftime("%Y-%m-%d %H:%M"),
    })

@app.post("/download", response_class=Response)
async def download_news(
    request: Request,
    selected: list = Form(...),
    titles: list = Form(...),
    press: list = Form(...),
    urls: list = Form(...)
):
    # txt로 다운
    lines = []
    for i, url in enumerate(selected):
        lines.append(f"■ {titles[i]} ({press[i]})\n{urls[i]}")
    txt = "\n\n".join(lines)
    return StreamingResponse(
        iter([txt]), 
        media_type="text/plain", 
        headers={"Content-Disposition": "attachment; filename=news.txt"}
    )
