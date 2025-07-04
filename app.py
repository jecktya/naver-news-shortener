import os
import re
import json
from datetime import datetime, timedelta
from typing import List, Dict

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
    print(">> [get_page_html] URL:", url)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto(url)
        print(">> [get_page_html] Page loaded")
        content = await page.content()
        print(">> [get_page_html] Content length:", len(content))
        await browser.close()
        print(">> [get_page_html] Browser closed")
        return content

def parse_news(html: str, keywords: List[str], mode: str, video_only: bool) -> List[Dict]:
    print(">> [parse_news] called")
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('ul.list_news > li')
    print(">> [parse_news] Found items:", len(items))
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
    print(">> [parse_news] Returning", len(results), "results")
    results.sort(key=lambda x:(-x['kw_count'], x['pubdate']), reverse=False)
    return results

async def naver_me_shorten(orig_url: str) -> str:
    # 실제 naver.me 단축주소 크롤링은 필요시 구현
    import random, string
    short = "https://naver.me/" + ''.join(random.choices(string.ascii_letters + string.digits, k=7))
    print(f">> [naver_me_shorten] {orig_url} -> {short}")
    return short

@app.get("/", include_in_schema=False)
async def get_index(request: Request):
    print(">> [GET /] index")
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
    print(f">> [POST /] keywords={keywords} search_mode={search_mode} video_only={video_only}")
    kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
    print(">> [POST /] kw_list:", kw_list)
    html = await get_page_html('+'.join(kw_list), bool(video_only))
    print(">> [POST /] HTML fetched")
    final_results = parse_news(html, kw_list, search_mode, bool(video_only))
    print(">> [POST /] parse_news results:", len(final_results))
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
    print(">> [POST /shorten] selected_urls:", selected_urls)
    final_results = json.loads(final_results_json)
    print(">> [POST /shorten] final_results loaded:", len(final_results))
    shortened_list = []
    for idx in selected_urls:
        try:
            orig = final_results[int(idx)]['url']
            short = await naver_me_shorten(orig)
            shortened_list.append(short)
        except Exception as e:
            print("!! [POST /shorten] Error:", e)
    print(">> [POST /shorten] shortened_list:", shortened_list)
    return templates.TemplateResponse("index.html", {
        'request': request,
        'final_results': final_results,
        'shortened': '\n'.join(shortened_list),
        'keyword_input': keyword_input,
        'default_keywords': ', '.join(DEFAULT_KEYWORDS),
        'search_mode': search_mo
