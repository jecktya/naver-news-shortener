# -*- coding: utf-8 -*-
import os, re, asyncio
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from bs4 import BeautifulSoup
import httpx
from datetime import datetime, timedelta
from typing import List, Dict

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="news!search!secret")
app.mount("/static", StaticFiles(directory="static", html=True), name="static")
templates = Jinja2Templates(directory="templates")

DEFAULT_KEYWORDS = ['육군', '국방', '외교', '안보', '북한', '신병', '교육대', '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원']
PRESS_MAJOR = set([
    '연합뉴스', '조선일보', '한겨레', '중앙일보', 'MBN', 'KBS', 'SBS', 'YTN',
    '동아일보', '세계일보', '문화일보', '뉴시스', '국민일보', '국방일보', '이데일리',
    '뉴스1', 'JTBC'
])

def parse_newslist(html:str, keywords:List[str], search_mode:str, video_only:bool) -> List[Dict]:
    soup = BeautifulSoup(html, "html.parser")
    news_cards = soup.select(".news_area, .bx")
    now = datetime.now()
    results = []
    for card in news_cards:
        a = card.select_one("a.news_tit, a")
        if not a: continue
        title = a["title"] if a.has_attr("title") else a.get_text(strip=True)
        url = a["href"]
        press = card.select_one(".info.press")
        press_name = press.get_text(strip=True).replace("언론사 선정", "") if press else ""
        desc = card.select_one(".dsc_wrap") or card.select_one(".desc")
        desc_txt = desc.get_text(" ", strip=True) if desc else ""
        pubdate = card.select_one(".info_group .date, .info .date")
        pub_str = pubdate.get_text(strip=True) if pubdate else ""
        pub_kst = parse_time(pub_str)
        # 4시간 이내
        if not pub_kst or (now - pub_kst > timedelta(hours=4)):
            continue
        # 주요언론사 only
        if search_mode=="major" and press_name and press_name not in PRESS_MAJOR:
            continue
        # 동영상 only
        if video_only:
            if not card.select_one("a.news_thumb[href*='tv.naver.com'], a.news_thumb[href*='video.naver.com'], span[class*=video]"):
                continue
        # 키워드 매칭/카운트
        kwcnt = {}
        for kw in keywords:
            pat = re.compile(re.escape(kw), re.IGNORECASE)
            c = pat.findall(title+desc_txt)
            if c: kwcnt[kw] = len(c)
        if not kwcnt: continue
        results.append(dict(
            title=title, url=url, press=press_name,
            pubdate=pub_kst.strftime('%Y-%m-%d %H:%M'), 
            keywords=sorted(kwcnt.items(), key=lambda x:(-x[1], x[0])),
            kw_count=sum(kwcnt.values())
        ))
    # 2개이상 키워드 포함 only 필터
    return sorted(results, key=lambda x:(-x['kw_count'], x['pubdate']))

def parse_time(timestr):
    if not timestr: return None
    now = datetime.now()
    if "분 전" in timestr:
        min_ago = int(timestr.split("분")[0])
        return now - timedelta(minutes=min_ago)
    if "시간 전" in timestr:
        hr_ago = int(timestr.split("시간")[0])
        return now - timedelta(hours=hr_ago)
    try:
        if re.match(r"\d{4}\.\d{2}\.\d{2}", timestr):
            t = datetime.strptime(timestr, "%Y.%m.%d.")
            return t.replace(hour=0, minute=0)
    except: pass
    return now

async def get_news_html(query, video_only, date=None):
    dt = date or datetime.now().strftime("%Y.%m.%d")
    smode = "2" if video_only else "0"
    url = f"https://m.search.naver.com/search.naver?ssc=tab.m_news.all&query={query}&sm=mtb_opt&sort=1&photo={smode}&field=0&pd=0&ds={dt}&de={dt}&docid=&related=0&mynews=0&office_type=0&office_section_code=0&news_office_checked=&nso=so%3Add%2Cp%3Aall"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers={"User-Agent":"Mozilla/5.0"})
        return r.text

from playwright.async_api import async_playwright

async def naver_me_shorten(orig_url):
    if not orig_url.startswith("https://n.news.naver.com/"): return orig_url, "n.news.naver.com 아님"
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width":400, "height":800}, user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X)")
            await page.goto(orig_url, timeout=8000)
            await page.wait_for_selector("span.u_hc, span:has-text('SNS 보내기')", timeout=7000)
            btn = await page.query_selector("span.u_hc, span:has-text('SNS 보내기')")
            if not btn:
                await browser.close()
                return orig_url, "공유 버튼 selector 못찾음"
            await btn.click()
            await page.wait_for_selector("#spiButton a, .spi_sns_list .link_sns", timeout=6000)
            link_elem = await page.query_selector("#spiButton a, .spi_sns_list .link_sns")
            link = await link_elem.get_attribute("data-url") if link_elem else None
            await browser.close()
            if link and link.startswith("https://naver.me/"):
                return link, ""
            return orig_url, "naver.me 주소 못찾음"
    except Exception as e:
        return orig_url, f"Playwright 오류: {str(e)}"

@app.get("/", response_class=None)
async def main(request: Request):
    return await render_news(request)

@app.post("/", response_class=None)
async def main_post(request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(""),
    search_mode: str = Form("major"),
    video_only: str = Form(""),
):
    return await render_news(request, keywords, checked_two_keywords, search_mode, video_only)

async def render_news(request, keywords="", checked_two_keywords="", search_mode="major", video_only=""):
    # 키워드 입력 및 정제
    if not keywords:
        keyword_input = ", ".join(DEFAULT_KEYWORDS)
        kwlist = DEFAULT_KEYWORDS
    else:
        keyword_input = keywords
        kwlist = [k.strip() for k in re.split(r"[,\|]", keywords) if k.strip()]
    # 검색쿼리 생성 (|로 조합, 7글자 이내 10개 제한)
    query = " | ".join(kwlist)
    html = await get_news_html(query, video_only=="on")
    newslist = parse_newslist(html, kwlist, search_mode, video_only=="on")
    # 2개 이상 키워드만
    checked_two = checked_two_keywords=="on"
    filtered = [a for a in newslist if len([cnt for k,cnt in a['keywords'] if c>0])>=2] if checked_two else newslist
    msg = f"총 {len(filtered)}건의 뉴스가 검색되었습니다."
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "keyword_input": keyword_input,
        "final_results": filtered,
        "msg": msg,
        "checked_two_keywords": checked_two,
        "search_mode": search_mode,
        "video_only": video_only=="on",
        "shortened": None,
        "shorten_fail": [],
    })

@app.post("/shorten")
async def shorten_urls(
    request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(""),
    search_mode: str = Form("major"),
    video_only: str = Form(""),
    selected_urls: List[str] = Form([])
):
    # 키워드 파싱
    kwlist = [k.strip() for k in re.split(r"[,\|]", keywords) if k.strip()]
    query = " | ".join(kwlist)
    html = await get_news_html(query, video_only=="on")
    newslist = parse_newslist(html, kwlist, search_mode, video_only=="on")
    checked_two = checked_two_keywords=="on"
    filtered = [a for a in newslist if len([cnt for k,cnt in a['keywords'] if c>0])>=2] if checked_two else newslist
    idx_set = set(map(int, selected_urls)) if isinstance(selected_urls, list) else set()
    selected = [filtered[i] for i in idx_set if 0<=i<len(filtered)]
    # 단축주소 변환
    shortened_lines = []
    shorten_fail = []
    for art in selected:
        short_url, fail = await naver_me_shorten(art["url"])
        line = f"■ {art['title']} ({art['press']})\n{short_url}"
        shortened_lines.append(line)
        if fail:
            shorten_fail.append(f"{art['title']}: {fail}")
    # 미선택 결과도 계속 노출
    msg = f"총 {len(filtered)}건의 뉴스가 검색되었습니다."
    return templates.TemplateResponse("news_search.html", {
        "request":
