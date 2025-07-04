import os
import re
import asyncio
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from datetime import datetime, timedelta
from typing import List, Dict
from starlette.middleware.sessions import SessionMiddleware

# FastAPI 앱 초기화
app = FastAPI(title="뉴스검색기 (FastAPI+Playwright)")
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET", "!secret!"))
app.mount("/static", StaticFiles(directory="static"), name="static")

# Jinja2 템플릿 경로 설정
templates = Jinja2Templates(directory="templates")

# 기본 키워드 및 주요 언론사 정의
DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]
PRESS_MAJOR = {
    '연합뉴스','조선일보','한겨레','중앙일보','MBN','KBS','SBS','YTN',
    '동아일보','세계일보','문화일보','뉴시스','국민일보','국방일보',
    '이데일리','뉴스1','JTBC'
}

# 시간 문자열 파싱 함수
def parse_time(timestr: str) -> datetime:
    now = datetime.now()
    if '분 전' in timestr:
        try:
            m = int(re.sub(r'[^0-9]', '', timestr))
            return now - timedelta(minutes=m)
        except:
            return None
    if '시간 전' in timestr:
        try:
            h = int(re.sub(r'[^0-9]', '', timestr))
            return now - timedelta(hours=h)
        except:
            return None
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})\.", timestr)
    if m:
        y, mm, d = map(int, m.groups())
        return datetime(y, mm, d)
    return None

# Playwright로 모바일 뉴스 HTML 가져오기
async def get_page_html(query: str, video_only: bool) -> str:
    url = f"https://m.search.naver.com/search.naver?ssc=tab.m_news.all&query={query}&sort=1&photo={'2' if video_only else '0'}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url)
        content = await page.content()
        await browser.close()
        return content

# HTML 파싱: 뉴스 리스트 추출
def parse_news(html: str, keywords: List[str], mode: str, video_only: bool) -> List[Dict]:
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('ul.list_news > li')
    now = datetime.now()
    results: List[Dict] = []
    kw_source = keywords or DEFAULT_KEYWORDS

    for li in items:
        a = li.select_one('a.news_tit')
        if not a:
            continue
        title = a.get('title', '').strip()
        link = a['href']
        press_elem = li.select_one('a.info.press')
        press = press_elem.get_text(strip=True).replace('언론사 선정','') if press_elem else ''
        date_elem = li.select_one('span.info.date')
        pubstr = date_elem.get_text(strip=True) if date_elem else ''
        pub = parse_time(pubstr)
        if not pub or (now - pub) > timedelta(hours=4):
            continue
        if mode == 'major' and press not in PRESS_MAJOR:
            continue
        if video_only and not li.select_one("a.news_tit[href*='tv.naver.com'], span.video"):
            continue
        desc_elem = li.select_one('div.news_dsc, div.api_txt_lines.dsc')
        desc = desc_elem.get_text(' ', strip=True) if desc_elem else ''
        hay = (title + ' ' + desc).lower()
        kwcnt = {kw: hay.count(kw.lower()) for kw in kw_source if hay.count(kw.lower())}
        if not kwcnt:
            continue
        results.append({
            'title': title,
            'press': press,
            'pubdate': pub.strftime('%Y-%m-%d %H:%M'),
            'url': link,
            'keywords': sorted(kwcnt.items(), key=lambda x:(-x[1], x[0])),
            'kw_count': sum(kwcnt.values())
        })
    results.sort(key=lambda x:(-x['kw_count'], x['pubdate']), reverse=False)
    return results

# 루트 GET: 검색 폼
@app.get("/", include_in_schema=False)
async def get_index(request: Request):
    return templates.TemplateResponse("index.html", {
        'request': request,
        'default_keywords': ', '.join(DEFAULT_KEYWORDS),
        'search_mode': 'all',
        'video_only': False,
        'keyword_input': ''
    })

# 루트 POST: 뉴스 검색 결과
@app.post("/", include_in_schema=False)
async def post_search(
    request: Request,
    keywords: str = Form(...),
    search_mode: str = Form('all'),
    video_only: str = Form(None)
):
    kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
    html = await get_page_html('+'.join(kw_list), bool(video_only))
    final_results = parse_news(html, kw_list, search_mode, bool(video_only))
    return templates.TemplateResponse("news_search.html", {
        'request': request,
        'final_results': final_results,
        'keyword_input': keywords,
        'default_keywords': ', '.join(DEFAULT_KEYWORDS),
        'search_mode': search_mode,
        'video_only': bool(video_only)
    })

# /shorten POST: 단축URL 생성
@app.post("/shorten", include_in_schema=False)
async def post_shorten(
    request: Request,
    selected_urls: List[int] = Form(...),
    keyword_input: str = Form(''),
    search_mode: str = Form('all'),
    video_only: str = Form(None),
    final_results: List[Dict] = Form(...)
):
    shortened_list = []
    fail_list = []
    for idx in selected_urls:
        try:
            orig = final_results[int(idx)]['url']
            # 여기에 naver.me 단축 로직 구현
            short = orig  # placeholder
            shortened_list.append(short)
        except Exception:
            fail_list.append(str(idx))
    return templates.TemplateResponse("short_result.html", {
        'request': request,
        'shortened': '\n'.join(shortened_list),
        'shorten_fail': fail_list
    })

# 앱 실행
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
