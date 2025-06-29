import os
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from bs4 import BeautifulSoup
import requests
import asyncio

try:
    from playwright.async_api import async_playwright
except ImportError:
    async_playwright = None  # 서버 환경에 따라 playwright 설치 안될 수도 있음

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.add_middleware(SessionMiddleware, secret_key="your-secret-key")

# ------- 기본 설정 -------
DEFAULT_KEYWORDS = [
    "육군", "국방", "외교", "안보", "북한",
    "신병", "교육대", "훈련", "간부", "장교",
    "부사관", "병사", "용사", "군무원"
]

PRESS_NAMES = [
    "연합뉴스", "조선일보", "중앙일보", "동아일보", "한겨레",
    "세계일보", "서울신문", "경향신문", "국민일보", "한국일보",
    "뉴시스", "JTBC", "YTN", "KBS", "MBC", "SBS", "TV조선",
    "채널A", "MBN"
]

def make_search_url(keywords, mode="major", video_only=False):
    base_url = "https://m.search.naver.com/search.naver?ssc=tab.m_news.all"
    q = " | ".join(keywords)
    params = {
        "query": q,
        "sort": "1",
        "photo": "2" if video_only else "0",
        "pd": "0",  # 전체 기간
        "ds": "",
        "de": "",
        "where": "m_news",
        "sm": "mtb_opt"
    }
    if mode == "major":
        params["mynews"] = "1"
    elif mode == "main_pc":
        params["office_type"] = "1"
    elif mode == "main_mobile":
        params["office_type"] = "2"
    # 쿼리스트링 생성
    param_str = "&".join([f"{k}={requests.utils.quote(str(v))}" for k, v in params.items()])
    return f"{base_url}&{param_str}"

def fetch_articles(search_url, checked_two_keywords, keywords):
    headers = {
        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1"
    }
    res = requests.get(search_url, headers=headers)
    soup = BeautifulSoup(res.text, "html.parser")
    articles = []
    for wrap in soup.select(".news_wrap.api_ani_send"):
        tit_tag = wrap.select_one(".news_tit")
        if not tit_tag:
            continue
        title = tit_tag.text.strip()
        url = tit_tag.get("href")
        press_tag = wrap.select_one(".info.press")
        press = press_tag.text.strip().replace("언론사 선정", "") if press_tag else ""
        date_tag = wrap.select_one(".info_group .info:not(.press)")
        pubdate = date_tag.text.strip() if date_tag else ""
        # 키워드 매칭 횟수 세기
        kw_counts = {kw: title.count(kw) for kw in keywords}
        match_count = sum(1 for c in kw_counts.values() if c > 0)
        kw_hit_summary = [(kw, cnt) for kw, cnt in kw_counts.items() if cnt > 0]
        # "2개 이상 키워드" 옵션
        if checked_two_keywords and match_count < 2:
            continue
        articles.append({
            "title": title,
            "url": url,
            "press": press,
            "pubdate": pubdate,
            "matched_keywords": kw_hit_summary,
        })
    return articles

# 단축주소 변환 (Playwright)
async def get_naverme_url(long_url):
    if not async_playwright:
        return None, "Playwright 미설치"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X)")
            await page.goto(long_url, timeout=10000)
            # "공유" 버튼의 selector는 대표 selector, 혹 실패하면 error 반환
            try:
                await page.wait_for_selector("#spiButton > span > span", timeout=5000)
                await page.click("#spiButton > span > span")
                await page.wait_for_selector('input#spiInput', timeout=5000)
                short_url = await page.input_value('input#spiInput')
            except Exception as e:
                short_url = None
            await browser.close()
        if not short_url or not short_url.startswith("https://naver.me/"):
            return None, "공유 버튼 selector를 찾지 못함"
        return short_url, ""
    except Exception as e:
        return None, f"Playwright 오류: {e}"

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "keywords": ", ".join(DEFAULT_KEYWORDS),
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "checked_two_keywords": False,
        "search_mode": "major",
        "video_only": False,
        "final_results": [],
        "copy_area": "",
        "fail_msgs": [],
        "msg": "",
    })

@app.post("/", response_class=HTMLResponse)
async def main_post(
    request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    video_only: str = Form(None),
):
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    checked_two = checked_two_keywords == "on"
    video_only_val = bool(video_only)
    search_url = make_search_url(keyword_list, search_mode, video_only_val)
    articles = fetch_articles(search_url, checked_two, keyword_list)
    msg = f"총 {len(articles)}건의 뉴스가 검색되었습니다."
    # 키워드 많은 순 정렬
    for a in articles:
        a["matched_keywords"] = sorted(a["matched_keywords"], key=lambda x: -x[1])
    copy_area = "\n\n".join([
        f"[{a['press']}] {a['title']}\n{a['url']}" for a in articles
    ])
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "keywords": keywords,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "checked_two_keywords": checked_two,
        "search_mode": search_mode,
        "video_only": video_only_val,
        "final_results": articles,
        "copy_area": copy_area,
        "fail_msgs": [],
        "msg": msg,
    })

@app.post("/shorten", response_class=HTMLResponse)
async def shorten(
    request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    video_only: str = Form(None),
    selected_urls: list = Form([]),
    copy_area: str = Form(""),
):
    # 기존 결과에서 선택된 url만 변환
    urls = selected_urls if isinstance(selected_urls, list) else [selected_urls]
    lines = copy_area.split("\n\n")
    short_url_map = {}
    fail_msgs = []
    for line in lines:
        if not line.strip():
            continue
        parts = line.strip().split("\n")
        if len(parts) != 2:
            continue
        press_title, url = parts
        if url.startswith("https://n.news.naver.com/"):
            short_url, fail_reason = await get_naverme_url(url)
            if short_url:
                short_url_map[url] = short_url
            else:
                fail_msgs.append(f"{press_title}: {fail_reason}")
    # 바꾼 결과 반영
    new_lines = []
    for line in lines:
        parts = line.strip().split("\n")
        if len(parts) == 2 and parts[1] in short_url_map:
            new_lines.append(f"{parts[0]}\n{short_url_map[parts[1]]}")
        else:
            new_lines.append(line)
    copy_area2 = "\n\n".join(new_lines)
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "keywords": keywords,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "checked_two_keywords": checked_two_keywords == "on",
        "search_mode": search_mode,
        "video_only": bool(video_only),
        "final_results": [],
        "copy_area": copy_area2,
        "fail_msgs": fail_msgs,
        "msg": "단축주소 변환 완료"
    })

# 디버그용 API
@app.get("/debug", response_class=PlainTextResponse)
async def debug():
    import datetime
    now = datetime.datetime.now()
    return f"서버시간: {now}"

