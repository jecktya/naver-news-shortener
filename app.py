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
import random
import logging 

# 로거 설정: DEBUG 레벨로 설정하여 상세 로그를 확인합니다.
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="news!search!secret")
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
    logger.info("뉴스 HTML 파싱 시작.")
    soup = BeautifulSoup(html, "html.parser")
    # 네이버 뉴스 카드 선택자: .news_area는 일반 뉴스, .bx는 가끔씩 다른 레이아웃에 사용됨
    news_cards = soup.select(".news_area, .bx, .api_txt_lines.news_tit") # 추가 선택자 고려
    now = datetime.now()
    results = []
    
    if not news_cards:
        logger.warning("뉴스 카드 요소를 찾을 수 없습니다. HTML 구조 변경 가능성 또는 검색 결과 없음.")
        logger.debug(f"받은 HTML 미리보기: {html[:1000]}...") # HTML의 앞부분 로깅 (더 길게)

    for card in news_cards:
        # 뉴스 제목과 링크를 포함하는 요소 선택
        a = card.select_one("a.news_tit, a.tit, a[role='text']") # 추가 선택자 고려
        if not a: 
            logger.debug(f"뉴스 제목/링크 요소를 찾을 수 없습니다. 카드 스킵: {card.prettify()[:200]}...")
            continue
        title = a["title"] if a.has_attr("title") else a.get_text(strip=True)
        url = a["href"]

        # 언론사 이름 선택
        press = card.select_one(".info.press, .press, ._sp_each_info") # 추가 선택자 고려
        press_name = press.get_text(strip=True).replace("언론사 선정", "").replace("언론사", "").strip() if press else ""
        
        # 뉴스 본문 요약 선택
        desc = card.select_one(".dsc_wrap, .desc, .api_txt_lines.dsc") # 추가 선택자 고려
        desc_txt = desc.get_text(" ", strip=True) if desc else ""
        
        # 발행일 선택
        pubdate = card.select_one(".info_group .date, .info .date, ._sp_each_date") # 추가 선택자 고려
        pub_str = pubdate.get_text(strip=True) if pubdate else ""
        pub_kst = parse_time(pub_str)
        
        if not pub_kst or (now - pub_kst > timedelta(hours=4)):
            logger.debug(f"뉴스 시간 필터링: '{title}' - {pub_str} ({pub_kst}). 4시간 초과 또는 파싱 실패. 제외됨.")
            continue
        
        if search_mode=="major" and press_name and press_name not in PRESS_MAJOR:
            logger.debug(f"주요 언론사 필터링: '{title}' - {press_name}. 제외됨.")
            continue
        
        if video_only:
            # 동영상 뉴스 식별자 추가
            if not card.select_one("a.news_thumb[href*='tv.naver.com'], a.news_thumb[href*='video.naver.com'], span[class*='video'], ._playing_area"):
                logger.debug(f"동영상 필터링: '{title}'. 동영상 아님. 제외됨.")
                continue
        
        kwcnt = {}
        for kw in keywords:
            pat = re.compile(re.escape(kw), re.IGNORECASE)
            # 제목과 요약 텍스트 모두에서 키워드 검색
            c = pat.findall(title + " " + desc_txt) 
            if c: kwcnt[kw] = len(c)
        
        if not kwcnt: 
            logger.debug(f"키워드 매칭 없음: '{title}'. 제외됨.")
            continue
        
        results.append(dict(
            title=title, url=url, press=press_name,
            pubdate=pub_kst.strftime('%Y-%m-%d %H:%M'),
            keywords=sorted(kwcnt.items(), key=lambda x:(-x[1], x[0])),
            kw_count=sum(kwcnt.values())
        ))
    logger.info(f"뉴스 파싱 완료. 총 {len(results)}건의 뉴스 기사 추출.")
    results = sorted(results, key=lambda x:(-x['kw_count'], x['pubdate']), reverse=False)
    return results

def parse_time(timestr):
    if not timestr: return None
    now = datetime.now()
    if "분 전" in timestr:
        try:
            min_ago = int(timestr.split("분")[0].strip())
            return now - timedelta(minutes=min_ago)
        except ValueError:
            logger.warning(f"분 전 파싱 오류: '{timestr}'")
            return None
    if "시간 전" in timestr:
        try:
            hr_ago = int(timestr.split("시간")[0].strip())
            return now - timedelta(hours=hr_ago)
        except ValueError:
            logger.warning(f"시간 전 파싱 오류: '{timestr}'")
            return None
    try:
        if re.match(r"\d{4}\.\d{2}\.\d{2}", timestr):
            t = datetime.strptime(timestr, "%Y.%m.%d.")
            return t.replace(hour=0, minute=0) # 날짜만 있는 경우 시,분,초 0으로 설정
    except Exception as e:
        logger.error(f"날짜 형식 시간 파싱 오류: '{timestr}' - {e}")
        pass
    return None # 어떤 형식도 매칭되지 않거나 오류 발생 시 None 반환

async def get_news_html(query, video_only, date=None):
    dt = date or datetime.now().strftime("%Y.%m.%d")
    smode = "2" if video_only else "0"
    url = f"https://m.search.naver.com/search.naver?ssc=tab.m_news.all&query={query}&sm=mtb_opt&sort=1&photo={smode}&field=0&pd=0&ds={dt}&de={dt}&docid=&related=0&mynews=0&office_type=0&office_section_code=0&news_office_checked=&nso=so%3Add%2Cp%3Aall"
    logger.info(f"뉴스 검색 HTML 요청 시작. URL: {url}")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
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
    async with httpx.AsyncClient(timeout=15) as client: # 타임아웃 증가
        try:
            r = await client.get(url, headers=headers)
            logger.info(f"뉴스 검색 HTML 응답 수신. 상태 코드: {r.status_code}")
            r.raise_for_status() # 200 이외의 응답에 대해 예외 발생
            logger.debug(f"응답 HTML 미리보기 (get_news_html): {r.text[:1000]}...") # 응답 HTML 앞부분 로깅 (더 길게)
            return r.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP 상태 오류 (get_news_html): {e.response.status_code} - {e.response.text[:500]}...", exc_info=True)
            return ""
        except httpx.RequestError as e:
            logger.error(f"요청 오류 발생 (get_news_html): {e}", exc_info=True)
            return ""
        except Exception as e:
            logger.error(f"예상치 못한 오류 발생 (get_news_html): {e}", exc_info=True)
            return ""

from playwright.async_api import async_playwright

async def naver_me_shorten(orig_url):
    logger.info(f"naver.me 단축 URL 변환 시도 시작. 원본 URL: {orig_url}")
    if not orig_url.startswith("https://n.news.naver.com/"): 
        logger.warning("naver.me 단축 URL 대상 아님.")
        return orig_url, "n.news.naver.com 주소가 아님"
    
    browser = None # browser 변수 초기화
    try:
        async with async_playwright() as p:
            # ### 중요: 디버깅을 위해 headless=False로 설정. 문제 해결 후 True로 변경 권장 ###
            # 프로덕션 환경에서는 headless=True로 변경해야 합니다.
            browser = await p.chromium.launch(
                headless=False, # 디버깅용: 브라우저 창을 띄워서 동작 확인
                args=[
                    '--disable-blink-features=AutomationControlled', # 봇 감지 회피
                    '--no-sandbox', # 리눅스 환경에서 필요할 수 있음
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--start-maximized' # 브라우저 창을 최대화하여 요소를 더 잘 찾도록 함
                ]
            )
            # User-Agent 설정: 네이버 모바일 뉴스 페이지에 접근하므로 모바일 UA가 유리할 수 있습니다.
            # PC User-Agent: "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            # Mobile User-Agent (iPhone): "Mozilla/5.0 (iPhone; CPU iPhone OS
