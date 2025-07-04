import os
import re
import json
from datetime import datetime, timedelta
from typing import List, Dict

import asyncio
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

app = FastAPI(title="뉴스검색기 (FastAPI+Playwright)")
templates = Jinja2Templates(directory="templates")

DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]
PRESS_MAJOR = {
    '연합뉴스','조선일보','한겨레','중앙일보','MBN','KBS','SBS','YTN',
    '동아일보','세계일보','문화일보','뉴시스','국민일보','국방일보',
    '이데일리','뉴스1','JTBC'
}

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

async def get_page_html(query: str, video_only: bool) -> str:
    url = f"https://m.search.naver.com/search.naver?ssc=tab.m_news.all&query={query}&sort=1&photo={'2' if video_only else '0'}"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url)
        content = await page.content()
        await browser.close()
        return content

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

# 실제 서비스에서는 Playwright로 naver.me 생성 로직 넣으세요!
async def naver_me_shorten(orig_url: str) -> str:
    import random, string
    return "https://naver.me/" + ''.join(random.choices(string.ascii_letters + string.digits, k=7))

@app.get("/", include_in_schema=False)
async def get_index(request: Request):
    return templates.TemplateResponse("index.html", {
        'request': request,
        'default_keywords': ', '.join(DEFAULT_KEYWORDS),
        'search_mode': 'all',
        'video_only': False,
        'keyword_input': '',
        'final_results': None,
        'shortened': None
    })

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
    return templates.TemplateResponse("index.html", {
        'request': request,
        'final_results': final_results,
        'keyword_input': keywords,
        'default_keywords': ', '.join(DEFAULT_KEYWORDS),
        'search_mode': search_mode,
        'video_only': bool(video_only),
        'shortened': None
    })

@app.post("/shorten", include_in_schema=False)
async def post_shorten(
    request: Request,
    selected_urls: List[str] = Form(...),
    final_results_json: str = Form(...),
    keyword_input: str = Form(''),
    search_mode: str = Form('all'),
    video_only: str = Form(None)
):
    final_results = json.loads(final_results_json)
    shortened_list = []
    for idx in selected_urls:
        try:
            orig = final_results[int(idx)]['url']
            short = await naver_me_shorten(orig)
            shortened_list.append(short)
        except Exception:
            pass
    return templates.TemplateResponse("index.html", {
        'request': request,
        'final_results': final_results,
        'shortened': '\n'.join(shortened_list),
        'keyword_input': keyword_input,
        'default_keywords': ', '.join(DEFAULT_KEYWORDS),
        'search_mode': search_mode,
        'video_only': bool(video_only)
    })

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
