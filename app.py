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
import random # 랜덤 딜레이를 위한 import

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="news!search!secret")
# static 디렉토리 있으면 mount, 없으면 무시
if os.path.isdir("static"):
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
    # 키워드 매칭 많은 순 정렬
    results = sorted(results, key=lambda x:(-x['kw_count'], x['pubdate']), reverse=False)
    return results

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

    # 실제 브라우저와 유사한 다양한 HTTP 헤더 추가
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36", # 최신 데스크톱 User-Agent
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(url, headers=headers)
            r.raise_for_status() # HTTP 4xx/5xx 에러 발생 시 예외 발생
            return r.text
        except httpx.HTTPStatusError as e:
            print(f"HTTP 오류 발생 (get_news_html): {e.response.status_code} - {e.response.text}")
            return ""
        except httpx.RequestError as e:
            print(f"요청 오류 발생 (get_news_html): {e}")
            return ""

from playwright.async_api import async_playwright

async def naver_me_shorten(orig_url):
    if not orig_url.startswith("https://n.news.naver.com/"): return orig_url, "n.news.naver.com 아님"
    try:
        async with async_playwright() as p:
            # 봇 감지 회피를 위한 브라우저 인자 추가
            browser = await p.chromium.launch(
                headless=True, # 배포 시 headless 유지, 테스트 시 False로 변경 가능
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu'
                ]
            )
            # 최신 모바일 User-Agent 사용
            latest_user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
            page = await browser.new_page(
                viewport={"width":400, "height":800},
                user_agent=latest_user_agent
            )

            await page.goto(orig_url, timeout=8000)
            await asyncio.sleep(random.uniform(1.5, 3.5)) # 페이지 로드 후 1.5~3.5초 랜덤 대기

            # 'SNS 보내기' 버튼을 찾거나, '공유' 아이콘이 포함된 span을 찾습니다.
            # 네이버 웹 페이지 구조가 변경될 경우 이 선택자를 수정해야 할 수 있습니다.
            share_button_selector = "span.u_hc, span:has-text('SNS 보내기'), #m-toolbar-navernews-share-btn"
            await page.wait_for_selector(share_button_selector, timeout=7000)
            await asyncio.sleep(random.uniform(0.7, 1.8)) # 선택자 대기 후 0.7~1.8초 랜덤 대기

            btn = await page.query_selector(share_button_selector)
            if not btn:
                await browser.close()
                return orig_url, "공유 버튼 selector 못찾음"

            await btn.click()
            await asyncio.sleep(random.uniform(1.0, 2.5)) # 버튼 클릭 후 1~2.5초 랜덤 대기

            # 단축 URL이 포함된 요소 찾기
            link_elem_selector = "#spiButton a, .spi_sns_list .link_sns"
            await page.wait_for_selector(link_elem_selector, timeout=6000)
            await asyncio.sleep(random.uniform(0.5, 1.0)) # 단축 URL 요소 대기 후 0.5~1초 랜덤 대기

            link_elem = await page.query_selector(link_elem_selector)
            link = await link_elem.get_attribute("data-url") if link_elem else None
            await browser.close()
            if link and link.startswith("https://naver.me/"):
                return link, ""
            return orig_url, "naver.me 주소 못찾음"
    except Exception as e:
        # 오류 발생 시 디버깅을 위해 더 상세한 정보 로깅
        print(f"Playwright 오류 발생 (naver_me_shorten): {e}, URL: {orig_url}")
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
    # 검색쿼리 생성 (|로 조합)
    query = " | ".join(kwlist)
    html = await get_news_html(query, video_only=="on")
    newslist = parse_newslist(html, kwlist, search_mode, video_only=="on")
    # 2개 이상 키워드만
    checked_two = checked_two_keywords=="on"
    # 필터링 로직 수정: `c`가 정의되지 않은 오류 수정 및 필터링 조건 명확화
    filtered = [a for a in newslist if len([kw_cnt for kw, kw_cnt in a['keywords'] if kw_cnt > 0]) >= 2] if checked_two else newslist
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
    kwlist = [k.strip() for k in re.split(r"[,\|]", keywords) if k.strip()]
    query = " | ".join(kwlist)
    html = await get_news_html(query, video_only=="on")
    newslist = parse_newslist(html, kwlist, search_mode, video_only=="on")
    checked_two = checked_two_keywords=="on"
    # 필터링 로직 수정: `c`가 정의되지 않은 오류 수정 및 필터링 조건 명확화
    filtered = [a for a in newslist if len([kw_cnt for kw, kw_cnt in a['keywords'] if kw_cnt > 0]) >= 2] if checked_two else newslist
    idx_set = set(map(int, selected_urls)) if isinstance(selected_urls, list) else set()
    selected = [filtered[i] for i in idx_set if 0<=i<len(filtered)]
    shortened_lines = []
    shorten_fail = []
    for art in selected:
        short_url, fail = await naver_me_shorten(art["url"])
        line = f"■ {art['title']} ({art['press']})\n{short_url}"
        shortened_lines.append(line)
        if fail:
            shorten_fail.append(f"{art['title']}: {fail}")
    # 복사 영역: 전체 기사 복사 결과도 항상 제공
    msg = f"총 {len(filtered)}건의 뉴스가 검색되었습니다."
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "keyword_input": keywords,
        "final_results": filtered,
        "msg": msg,
        "checked_two_keywords": checked_two,
        "search_mode": search_mode,
        "video_only": video_only=="on",
        "shortened": "\n\n".join(shortened_lines),
        "shorten_fail": shorten_fail,
    })

