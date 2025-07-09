# -*- coding: utf-8 -*-
import os
import re
import asyncio
import json # json 모듈 추가
import random
import string
import logging # 로깅 모듈 임포트
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.responses import RedirectResponse, HTMLResponse # HTMLResponse 추가
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.staticfiles import StaticFiles
from bs4 import BeautifulSoup
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Optional # Optional 추가

# 로거 설정: DEBUG 레벨로 설정하여 상세 로그를 확인합니다.
# 프로덕션 환경에서는 INFO 또는 WARNING으로 변경하는 것이 좋습니다.
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = FastAPI(title="네이버 뉴스 검색 및 단축기")
# SessionMiddleware는 FastAPI의 세션 관리에 필요하며, secret_key는 보안상 중요합니다.
# 실제 프로덕션 환경에서는 이 키를 환경 변수에서 가져오거나 더 복잡하게 생성해야 합니다.
app.add_middleware(SessionMiddleware, secret_key="super-secret-key-for-news-app-please-change-this-in-prod-env")

# 'static' 폴더가 존재하면 정적 파일을 서빙합니다. CSS, JS, 이미지 등을 여기에 둘 수 있습니다.
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static", html=True), name="static")
templates = Jinja2Templates(directory="templates")

# 기본 검색 키워드 목록
DEFAULT_KEYWORDS = ['육군', '국방', '외교', '안보', '북한', '신병', '교육대', '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원']
# 주요 언론사 목록 (필터링에 사용)
PRESS_MAJOR = set([
    '연합뉴스', '조선일보', '한겨레', '중앙일보', 'MBN', 'KBS', 'SBS', 'YTN',
    '동아일보', '세계일보', '문화일보', '뉴시스', '국민일보', '국방일보', '이데일리',
    '뉴스1', 'JTBC'
])

def parse_newslist(html:str, keywords:List[str], search_mode:str, video_only:bool) -> List[Dict]:
    """
    네이버 뉴스 검색 결과 HTML을 파싱하여 뉴스 기사 목록을 반환합니다.
    주어진 키워드, 언론사 모드, 동영상 필터링 조건을 적용합니다.
    """
    logger.info("뉴스 HTML 파싱 시작.")
    soup = BeautifulSoup(html, "html.parser")
    # 다양한 뉴스 카드 선택자 시도 (네이버 HTML 구조는 자주 변경될 수 있음)
    # .news_area: 일반적인 뉴스 검색 결과 카드
    # .bx: 가끔 다른 레이아웃에서 사용되는 카드
    # .news_wrap, ._news_item: 추가적인 뉴스 항목 선택자
    news_cards = soup.select(".news_area, .bx, .news_wrap, ._news_item") 
    now = datetime.now()
    results = []
    
    if not news_cards:
        logger.warning("뉴스 카드 요소를 찾을 수 없습니다. HTML 구조 변경 가능성 또는 검색 결과 없음.")
        logger.debug(f"받은 HTML 미리보기: {html[:1000]}...") # HTML의 앞부분 로깅 (더 길게)
        return []

    for card in news_cards:
        # 뉴스 제목과 링크 추출 (다양한 선택자 시도)
        # a.news_tit: 모바일 뉴스 제목 링크
        # a.tit: 일반적인 제목 링크
        # a[role='text']: 접근성 역할 기반 링크
        # .news_area .title a: 특정 영역 내 제목 링크
        a = card.select_one("a.news_tit, a.tit, a[role='text'], .news_area .title a")
        if not a: 
            logger.debug(f"뉴스 제목/링크 요소를 찾을 수 없습니다. 카드 스킵: {card.prettify()[:200]}...")
            continue
        title = a["title"] if a.has_attr("title") else a.get_text(strip=True)
        url = a["href"]

        # 언론사 이름 추출 (다양한 선택자 시도)
        # .info.press: 모바일 뉴스 언론사 정보
        # .press: 일반적인 언론사 클래스
        # ._sp_each_info: 스페셜 영역 정보
        # .news_info .press: 뉴스 정보 영역 내 언론사
        press = card.select_one(".info.press, .press, ._sp_each_info, .news_info .press")
        press_name = press.get_text(strip=True).replace("언론사 선정", "").replace("언론사", "").strip() if press else ""
        
        # 뉴스 본문 요약 추출 (다양한 선택자 시도)
        # .dsc_wrap: 모바일 뉴스 요약
        # .desc: 일반적인 요약 클래스
        # .api_txt_lines.dsc: API 텍스트 라인 요약
        # .news_dsc: 뉴스 요약
        desc = card.select_one(".dsc_wrap, .desc, .api_txt_lines.dsc, .news_dsc")
        desc_txt = desc.get_text(" ", strip=True) if desc else ""
        
        # 발행일 추출 및 시간 필터링 (최근 4시간 이내)
        # .info_group .date: 모바일 뉴스 날짜 그룹
        # .info .date: 일반적인 날짜 정보
        # ._sp_each_date: 스페셜 영역 날짜
        # .news_info .date: 뉴스 정보 영역 내 날짜
        pubdate = card.select_one(".info_group .date, .info .date, ._sp_each_date, .news_info .date")
        pub_str = pubdate.get_text(strip=True) if pubdate else ""
        pub_kst = parse_time(pub_str)
        
        if not pub_kst or (now - pub_kst > timedelta(hours=4)):
            logger.debug(f"뉴스 시간 필터링: '{title}' - {pub_str} ({pub_kst}). 4시간 초과 또는 파싱 실패. 제외됨.")
            continue
        
        # 주요 언론사 필터링
        if search_mode=="major" and press_name and press_name not in PRESS_MAJOR:
            logger.debug(f"주요 언론사 필터링: '{title}' - {press_name}. 제외됨.")
            continue
        
        # 동영상 뉴스만 필터링
        if video_only:
            # 동영상 뉴스를 나타내는 특정 요소나 URL 패턴 확인
            # a.news_thumb[href*='tv.naver.com']: 네이버 TV 링크 썸네일
            # a.news_thumb[href*='video.naver.com']: 네이버 비디오 링크 썸네일
            # span[class*=video]: 'video' 클래스를 포함하는 span
            # ._playing_area: 재생 영역
            # .sp_thmb_video: 비디오 썸네일
            if not card.select_one("a.news_thumb[href*='tv.naver.com'], a.news_thumb[href*='video.naver.com'], span[class*='video'], ._playing_area, .sp_thmb_video"):
                logger.debug(f"동영상 필터링: '{title}'. 동영상 아님. 제외됨.")
                continue
        
        # 키워드 매칭 및 카운트
        kwcnt = {}
        for kw in keywords:
            pat = re.compile(re.escape(kw), re.IGNORECASE)
            c = pat.findall(title + " " + desc_txt) # 제목과 요약 텍스트 모두에서 키워드 검색
            if c: kwcnt[kw] = len(c)
        
        if not kwcnt: 
            logger.debug(f"키워드 매칭 없음: '{title}'. 제외됨.")
            continue
        
        results.append(dict(
            title=title, url=url, press=press_name,
            pubdate=pub_kst.strftime('%Y-%m-%d %H:%M'),
            keywords=sorted(kwcnt.items(), key=lambda x:(-x[1], x[0])), # 키워드 빈도수 내림차순, 키워드명 오름차순 정렬
            kw_count=sum(kwcnt.values()) # 총 키워드 출현 횟수
        ))
    logger.info(f"뉴스 파싱 완료. 총 {len(results)}건의 뉴스 기사 추출.")
    # 총 키워드 출현 횟수 내림차순, 발행일 오름차순으로 최종 정렬
    results = sorted(results, key=lambda x:(-x['kw_count'], x['pubdate']), reverse=False)
    return results

def parse_time(timestr: str) -> Optional[datetime]:
    """
    주어진 시간 문자열을 datetime 객체로 파싱합니다.
    'X분 전', 'X시간 전', 'YYYY.MM.DD.' 형식을 지원합니다.
    파싱 실패 시 None을 반환합니다.
    """
    if not timestr:
        logger.debug("시간 문자열이 비어 있습니다.")
        return None
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
        # YYYY.MM.DD. 형식 (점 포함)
        if re.match(r"\d{4}\.\d{2}\.\d{2}\.", timestr):
            t = datetime.strptime(timestr, "%Y.%m.%d.")
            return t.replace(hour=0, minute=0) # 날짜만 있는 경우 시,분,초 0으로 설정
        # YYYY.MM.DD 형식 (점 없음)
        elif re.match(r"\d{4}\.\d{2}\.\d{2}", timestr):
            t = datetime.strptime(timestr, "%Y.%m.%d")
            return t.replace(hour=0, minute=0)
    except Exception as e:
        logger.error(f"날짜 형식 시간 파싱 오류: '{timestr}' - {e}")
        pass
    return None # 어떤 형식도 매칭되지 않거나 오류 발생 시 None 반환

async def get_news_html(query: str, video_only: bool, date: Optional[str] = None) -> str:
    """
    네이버 모바일 뉴스 검색 페이지에서 HTML을 가져옵니다.
    """
    dt = date or datetime.now().strftime("%Y.%m.%d")
    smode = "2" if video_only else "0" # photo=2 for video, photo=0 for all
    # 네이버 모바일 뉴스 검색 URL (sort=1: 최신순)
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
    async with httpx.AsyncClient(timeout=15) as client: # 타임아웃 설정
        try:
            r = await client.get(url, headers=headers)
            logger.info(f"뉴스 검색 HTML 응답 수신. 상태 코드: {r.status_code}")
            r.raise_for_status() # 200 이외의 응답에 대해 예외 발생
            logger.debug(f"응답 HTML 미리보기 (get_news_html): {r.text[:1000]}...") # 응답 HTML 앞부분 로깅
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

async def naver_me_shorten(orig_url: str) -> tuple[str, str]:
    """
    Playwright를 사용하여 naver.me 단축 URL을 생성합니다.
    이 함수는 웹 자동화에 의존하므로 불안정할 수 있습니다.
    성공 시 (단축 URL, ""), 실패 시 (원본 URL, 실패 이유 문자열) 튜플 반환.
    """
    # Playwright는 컨테이너 환경에서 브라우저 설치가 필요합니다. Dockerfile을 확인하세요.
    # 함수 내부에서 임포트하여 필요할 때만 로드하도록 합니다.
    from playwright.async_api import async_playwright 

    logger.info(f"naver.me 단축 URL 변환 시도 시작. 원본 URL: {orig_url}")
    if not orig_url.startswith("https://n.news.naver.com/"): 
        logger.warning("naver.me 단축 URL 대상 아님. n.news.naver.com 주소가 아님.")
        return orig_url, "n.news.naver.com 주소가 아님"
    
    browser = None # browser 객체 초기화 (finally 블록에서 닫기 위함)
    try:
        async with async_playwright() as p:
            # headless=True: 브라우저 UI 없이 백그라운드에서 실행 (배포 환경 권장)
            # headless=False: 브라우저 UI를 띄워서 실행 (로컬 디버깅용)
            browser = await p.chromium.launch(
                headless=True, 
                args=[
                    '--disable-blink-features=AutomationControlled', # 봇 감지 회피
                    '--no-sandbox', # 리눅스 환경에서 필요할 수 있음
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage', # /dev/shm 사용 비활성화 (메모리 문제 방지)
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu', # GPU 가속 비활성화 (컨테이너 환경에서 GPU가 없을 때 문제 방지)
                    '--start-maximized' # 브라우저 창을 최대화하여 요소를 더 잘 찾도록 함
                ]
            )
            # User-Agent 설정: 네이버 모바일 뉴스 페이지에 접근하므로 모바일 UA가 유리할 수 있습니다.
            current_user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
            
            page = await browser.new_page(
                viewport={"width":400, "height":800}, # 모바일 뷰포트 설정
                user_agent=current_user_agent
            )
            logger.info(f"Playwright 페이지 생성 완료. User-Agent: {current_user_agent}")

            # 리소스 차단 (선택 사항: 페이지 로딩 속도 향상 및 안정성 개선)
            # await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font"] else route.continue())

            await page.goto(orig_url, timeout=20000) # 페이지 로드 타임아웃 증가 (20초)
            logger.info(f"페이지 로드 완료: {orig_url}")
            await asyncio.sleep(random.uniform(2.5, 4.5)) # 페이지 로드 후 충분히 대기

            # --- 공유 버튼 찾기 및 클릭 ---
            # 네이버 뉴스 모바일 웹의 공유 버튼은 '.u_hc' 또는 'sns 보내기' 텍스트를 가진 span 태그이거나,
            # 툴바에 있는 공유 아이콘일 수 있습니다. 여러 선택자를 시도합니다.
            share_button_selectors = [
                "span.u_hc",                                   # 일반적인 공유 아이콘 클래스
                "span:has-text('SNS 보내기')",                  # 텍스트 기반 검색
                "#m-toolbar-navernews-share-btn",              # 모바일 툴바의 공유 버튼 ID
                "#toolbar .tool_share",                        # PC 버전 툴바의 공유 버튼
                "button[aria-label*='공유']",                   # 접근성 라벨 기반
                "button[data-tooltip-contents='공유하기']",      # 새로운 속성 기반
                "a[href*='share']"                             # 공유 링크 자체를 찾아볼 수도
            ]
            
            share_button_found = False
            for selector in share_button_selectors:
                logger.debug(f"공유 버튼 선택자 시도 중: {selector}")
                try:
                    # 요소가 나타날 때까지 대기하고, 나타나면 가져옵니다.
                    btn = await page.wait_for_selector(selector, timeout=7000, state='visible') # 요소가 'visible' 상태가 될 때까지 대기
                    if btn and await btn.is_visible(): # 실제로 보이는지 다시 확인
                        await btn.click(timeout=3000) # 클릭 시 타임아웃 설정
                        logger.info(f"공유 버튼 클릭 성공 (선택자: {selector}).")
                        share_button_found = True
                        break
                    else:
                        logger.debug(f"선택자 '{selector}'의 요소가 보이지 않습니다.")
                except Exception as e:
                    logger.debug(f"공유 버튼 선택자 '{selector}' 대기 또는 클릭 실패: {e}")
                    continue
            
            if not share_button_found:
                logger.warning("모든 공유 버튼 선택자 시도 실패. 공유 버튼을 찾을 수 없습니다.")
                # 디버깅을 위해 스크린샷 저장
                # await page.screenshot(path="share_button_not_found.png") 
                return orig_url, "공유 버튼을 찾을 수 없음"
            
            await asyncio.sleep(random.uniform(1.5, 3.0)) # 공유 팝업이 뜨는 것을 대기

            # --- 단축 URL 요소 찾기 ---
            # 공유 팝업 내에서 naver.me 단축 URL을 포함하는 요소를 찾습니다.
            link_elem_selectors = [
                "button[data-url^='https://naver.me/']",     # data-url 속성으로 naver.me 주소 바로 찾기 (버튼)
                "span[data-url^='https://naver.me/']",       # data-url 속성으로 naver.me 주소 바로 찾기 (span)
                "a.link_sns[href^='https://naver.me/']",     # href 속성으로 naver.me 주소 바로 찾기 (링크)
                "#spiButton a",                               # 일반적인 단축 URL 복사 버튼 ID
                ".spi_sns_list .link_sns",                    # SNS 공유 리스트 내 링크
                "#clipBtn",                                   # 클립보드 복사 버튼 ID
                "._clipUrlBtn",                               # 클립보드 복사 버튼 클래스
                "input[readonly][value^='https://naver.me/']", # 읽기 전용 input 필드에 URL이 있을 경우
                "div.share_url_area .url_item"                # URL 텍스트가 직접 표시되는 영역
            ]
            
            short_link = None
            for selector in link_elem_selectors:
                logger.debug(f"단축 URL 요소 선택자 시도 중: {selector}")
                try:
                    link_elem = await page.wait_for_selector(selector, timeout=6000, state='visible')
                    if link_elem and await link_elem.is_visible():
                        link = await link_elem.get_attribute("data-url") # data-url 속성 먼저 시도
                        if not link:
                            link = await link_elem.get_attribute("href") # href 속성 시도
                        if not link:
                            link = await link_elem.get_attribute("value") # input 필드의 value 속성 시도
                        if not link:
                            link = await link_elem.inner_text() # 텍스트 내용 시도
                        
                        if link and link.startswith("https://naver.me/"):
                            short_link = link
                            logger.info(f"단축 URL 변환 성공 (선택자: {selector}, 최종 URL: {short_link})")
                            break
                        else:
                            logger.debug(f"선택자 '{selector}'에서 naver.me 주소를 찾지 못했습니다. (링크: {link})")
                    else:
                        logger.debug(f"선택자 '{selector}'의 단축 URL 요소가 보이지 않습니다.")
                except Exception as e:
                    logger.debug(f"단축 URL 요소 선택자 '{selector}' 대기 실패: {e}")
                    continue

            if short_link:
                return short_link, "" # 성공 시 단축 URL과 빈 문자열 반환
            else:
                logger.warning("모든 단축 URL 요소 선택자 시도 실패. naver.me 주소를 찾을 수 없습니다.")
                # 디버깅을 위해 스크린샷 저장
                # await page.screenshot(path="short_url_not_found.png") 
                return orig_url, "naver.me 주소를 찾을 수 없음 (최종)"

    except Exception as e:
        logger.error(f"Playwright 오류 발생 (naver_me_shorten): {e}", exc_info=True) # 스택 트레이스 포함
        return orig_url, f"Playwright 오류: {str(e)}"
    finally:
        if browser: # 브라우저 객체가 생성되었다면 확실히 닫아줍니다.
            await browser.close()

@app.get("/", response_class=HTMLResponse) # HTML 응답을 명시
async def main(request: Request):
    """
    메인 검색 페이지를 렌더링합니다.
    """
    logger.info("메인 페이지 GET 요청 수신.")
    return await render_news(request)

@app.post("/", response_class=HTMLResponse) # HTML 응답을 명시
async def main_post(request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(""),
    search_mode: str = Form("major"),
    video_only: str = Form(""),
):
    """
    키워드를 받아 네이버 뉴스 웹 페이지를 검색하고 결과를 표시합니다.
    """
    logger.info(f"메인 페이지 POST 요청 수신. 키워드: '{keywords}', 모드: {search_mode}, 비디오 전용: {video_only}")
    return await render_news(request, keywords, checked_two_keywords, search_mode, video_only)

async def render_news(request: Request, keywords: str = "", checked_two_keywords: str = "", search_mode: str = "major", video_only: str = ""):
    """
    뉴스 검색 결과를 렌더링하여 HTML 페이지로 반환합니다.
    """
    kwlist = [k.strip() for k in re.split(r"[,\|]", keywords) if k.strip()]
    if not kwlist:
        kwlist = DEFAULT_KEYWORDS
        logger.info("키워드가 없어 기본 키워드 사용.")
    
    query = " | ".join(kwlist) # 네이버 웹 검색 쿼리 형식
    logger.info(f"검색 쿼리: '{query}'")
    
    html = await get_news_html(query, video_only=="on")
    newslist = []
    error_message = None

    if not html:
        error_message = "네이버 뉴스 HTML을 가져오는데 실패했습니다. 네트워크 또는 웹사이트 문제일 수 있습니다."
        logger.error(error_message)
    else:
        try:
            newslist = parse_newslist(html, kwlist, search_mode, video_only=="on")
        except Exception as e:
            error_message = f"뉴스 HTML 파싱 중 오류 발생: {e}"
            logger.error(error_message, exc_info=True)
            newslist = [] # 파싱 실패 시 빈 리스트
            
    checked_two = checked_two_keywords=="on"
    # 두 개 이상의 키워드 일치 필터링 로직
    # 'keywords' 리스트의 길이가 2 이상인 경우를 확인합니다.
    filtered = [a for a in newslist if len(a['keywords']) >= 2] if checked_two else newslist
    
    msg = f"총 {len(filtered)}건의 뉴스가 검색되었습니다."
    if not filtered and not error_message: # 결과가 없고 에러 메시지도 없으면
        msg = "검색된 뉴스가 없습니다. 키워드나 필터링 조건을 다시 확인해주세요."
    logger.info(msg)
    
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "keyword_input": keywords,
        "final_results": filtered,
        "msg": msg,
        "checked_two_keywords": checked_two,
        "search_mode": search_mode,
        "video_only": video_only=="on",
        "shortened": None,
        "shorten_fail": [],
        "error_message": error_message # 에러 메시지 템플릿으로 전달
    })

@app.post("/shorten", response_class=HTMLResponse) # HTML 응답을 명시
async def shorten_urls(
    request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(""),
    search_mode: str = Form("major"),
    video_only: str = Form(""),
    selected_urls: List[str] = Form(...), # List[str]로 타입 힌트
    final_results_json: str = Form(...) # JSON 문자열로 받음
):
    """
    선택된 뉴스 URL들을 Playwright를 사용하여 naver.me URL로 단축합니다.
    """
    logger.info(f"POST /shorten 요청 수신. 선택된 URL 인덱스 수: {len(selected_urls)}")
    
    # 이전 검색 조건 복원
    kwlist = [k.strip() for k in re.split(r"[,\|]", keywords) if k.strip()]
    if not kwlist:
        kwlist = DEFAULT_KEYWORDS
    query = " | ".join(kwlist)

    # 이전 검색 결과 HTML 다시 가져오기 및 파싱 (데이터 일관성 유지)
    html = await get_news_html(query, video_only=="on")
    newslist = []
    error_message = None
    if not html:
        error_message = "네이버 뉴스 HTML을 다시 가져오는데 실패했습니다. URL 단축을 진행할 수 없습니다."
        logger.error(error_message)
    else:
        try:
            newslist = parse_newslist(html, kwlist, search_mode, video_only=="on")
        except Exception as e:
            error_message = f"뉴스 HTML 재파싱 중 오류 발생: {e}"
            logger.error(error_message, exc_info=True)
            newslist = []

    # UI에서 전달된 JSON 데이터를 사용하여 final_results 복원
    final_results_from_ui = []
    try:
        if not final_results_json:
            logger.warning("final_results_json이 비어 있습니다. 빈 리스트로 처리합니다.")
        else:
            final_results_from_ui = json.loads(final_results_json)
        logger.debug(f"UI에서 로드된 final_results 수: {len(final_results_from_ui)}")
    except json.JSONDecodeError as e:
        error_message = f"검색 결과 JSON 파싱 오류: {e}. 다시 검색해 주세요."
        logger.error(error_message, exc_info=True)
        final_results_from_ui = [] # 파싱 실패 시 빈 리스트로 설정

    # 필터링된 최종 결과 (현재 페이지에 표시된 결과)
    # UI에서 받은 final_results_from_ui를 사용하여 선택된 기사를 찾습니다.
    # 이렇게 하면 서버가 HTML을 다시 파싱하지 않아도 UI에 표시된 정확한 데이터를 사용합니다.
    filtered_current_page_results = final_results_from_ui
    
    # 선택된 URL만 단축 처리
    selected_articles_to_shorten = []
    for idx_str in selected_urls:
        try:
            idx = int(idx_str)
            # filtered_current_page_results에서 해당 인덱스의 기사를 찾습니다.
            if 0 <= idx < len(filtered_current_page_results):
                selected_articles_to_shorten.append(filtered_current_page_results[idx])
            else:
                logger.warning(f"유효하지 않은 선택 인덱스: {idx_str}. 현재 결과 수: {len(filtered_current_page_results)}")
                if not error_message: # 기존 에러 메시지가 없으면 추가
                    error_message = f"선택된 뉴스 중 일부가 유효하지 않습니다 (인덱스: {idx_str})."
        except ValueError:
            logger.error(f"선택된 URL 인덱스 파싱 오류: '{idx_str}'는 정수가 아닙니다.", exc_info=True)
            if not error_message:
                error_message = f"선택된 뉴스 인덱스 형식이 잘못되었습니다: {idx_str}"
        except Exception as e:
            logger.error(f"선택된 URL 처리 중 예상치 못한 오류 발생: {e}", exc_info=True)
            if not error_message:
                error_message = f"선택된 뉴스 처리 중 오류 발생: {e}"

    shortened_lines = []
    shorten_fail = []
    
    if not selected_articles_to_shorten:
        logger.warning("단축 변환할 선택된 기사가 없습니다.")
        if not error_message:
            error_message = "단축할 뉴스를 선택해주세요."

    # 각 URL에 대해 Playwright 단축 함수 실행
    tasks = [naver_me_shorten(art["url"]) for art in selected_articles_to_shorten]
    # Playwright 작업은 시간이 오래 걸릴 수 있으므로 타임아웃을 충분히 줍니다.
    # 개별 naver_me_shorten 함수 내에 타임아웃이 설정되어 있습니다.
    shorten_results = await asyncio.gather(*tasks) 

    for i, (short_url, fail_reason) in enumerate(shorten_results):
        art = selected_articles_to_shorten[i] # 원래 기사 정보 가져오기
        line = f"■ {art['title']} ({art['press']})\n{short_url}"
        shortened_lines.append(line)
        if fail_reason:
            shorten_fail.append(f"'{art['title']}': {fail_reason}")
            logger.error(f"'{art['title']}' 단축 변환 실패: {fail_reason}")
        else:
            logger.info(f"'{art['title']}' 단축 변환 성공.")
            
    # 최종 메시지 구성
    msg = f"총 {len(filtered_current_page_results)}건의 뉴스가 검색되었습니다."
    if shortened_lines:
        msg += f" (단축 성공: {len(shortened_lines) - len(shorten_fail)}건, 실패: {len(shorten_fail)}건)"
    logger.info(f"단축 변환 처리 완료. {msg}")
    
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "keyword_input": keywords,
        "final_results": filtered_current_page_results, # 현재 페이지에 표시될 결과
        "msg": msg,
        "checked_two_keywords": checked_two,
        "search_mode": search_mode,
        "video_only": video_only=="on",
        "shortened": "\n\n".join(shortened_lines),
        "shorten_fail": shorten_fail,
        "error_message": error_message # 에러 메시지 템플릿으로 전달
    })

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    # reload=True는 개발용입니다. 프로덕션 환경에서는 제거하세요.
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

