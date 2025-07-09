# app.py
# -*- coding: utf-8 -*-

import os
import json
import random
import string
import logging
import asyncio # asyncio 임포트 추가 (Playwright 사용을 위해)
import re # re (정규 표현식) 모듈 임포트. 'NameError' 발생 시 이 줄을 확인하십시오.
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx
from datetime import datetime, timedelta # datetime, timedelta 임포트 추가
from typing import List, Dict, Optional # Optional 임포트 추가

# 로거 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 네이버 API 키 환경 변수에서 로드
# 실제 서비스에서는 이 값을 반드시 유효한 네이버 개발자 센터 키로 설정해야 합니다.
# https://developers.naver.com/main/ 에 접속하여 애플리케이션을 등록하고 Client ID와 Client Secret을 발급받으세요.
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")

# API 키 로깅 (보안을 위해 SECRET은 일부만 표시)
logger.info("="*35)
logger.info(f"NAVER_CLIENT_ID: {NAVER_CLIENT_ID}")
logger.info(f"NAVER_CLIENT_SECRET: {NAVER_CLIENT_SECRET[:4]}{'*'*(len(NAVER_CLIENT_SECRET)-4)}")
logger.info("="*35)

NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

# Jinja2Templates 초기화 시 enumerate를 글로벌 함수로 추가
templates = Jinja2Templates(directory="templates")
templates.env.globals["enumerate"] = enumerate # enumerate 함수를 Jinja2 환경에 추가

app = FastAPI(title="뉴스검색기 (FastAPI+NaverAPI)")


DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]

# 주요 언론사 목록 (대소문자 구분 없이 비교하기 위해 set 사용)
PRESS_MAJOR = {
    '연합뉴스', '조선일보', '한겨레', '중앙일보',
    'MBN', 'KBS', 'SBS', 'YTN',
    '동아일보', '세계일보', '문화일보', '뉴시스',
    '국민일보', '국방일보', '이데일리',
    '뉴스1', 'JTBC'
}

def parse_api_pubdate(pubdate_str: str) -> Optional[datetime]:
    """
    RFC 1123 형식의 날짜 문자열을 datetime 객체로 파싱합니다.
    예: "Wed, 09 Jul 2025 12:55:29 +0900"
    """
    if not pubdate_str:
        return None
    try:
        # RFC 1123 형식 파싱 (요일, 일, 월, 년, 시:분:초, 타임존)
        # 타임존 정보는 strptime에서 직접 처리하기 어려우므로, 제거 후 파싱
        # 예: "Wed, 09 Jul 2025 12:55:29 +0900" -> "Wed, 09 Jul 2025 12:55:29"
        # 마지막 6자리는 타임존 정보 (+0900)이므로, 이를 제외하고 파싱
        date_time_part = pubdate_str[:-6].strip()
        # %a: 요일 약어, %d: 일, %b: 월 약어, %Y: 년도, %H: 시, %M: 분, %S: 초
        return datetime.strptime(date_time_part, "%a, %d %b %Y %H:%M:%S")
    except ValueError as e:
        logger.error(f"pubDate 파싱 실패 ('{pubdate_str}'): {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"pubDate 파싱 중 예상치 못한 오류: {e}", exc_info=True)
        return None

async def search_naver_news(query: str, display: int = 10):
    """
    네이버 뉴스 검색 API를 호출하여 뉴스 아이템을 가져옵니다.
    """
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET or \
       NAVER_CLIENT_ID == "YOUR_NAVER_CLIENT_ID_HERE" or \
       NAVER_CLIENT_SECRET == "YOUR_NAVER_CLIENT_SECRET_HERE":
        logger.error("네이버 API 클라이언트 ID 또는 시크릿이 설정되지 않았습니다.")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="네이버 API 키가 설정되지 않았습니다. 환경 변수 'NAVER_CLIENT_ID'와 'NAVER_CLIENT_SECRET'을 확인해주세요."
        )

    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": display,
        "sort": "date", # 최신순 정렬
    }
    logger.info(f"네이버 뉴스 API 요청 시작. 쿼리: '{query}', 표시 개수: {display}")
    try:
        async with httpx.AsyncClient(timeout=10) as client: # 타임아웃 설정
            res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
            res.raise_for_status() # 200 OK가 아니면 예외 발생
            data = res.json()
            items = data.get("items", [])
            logger.info(f"네이버 뉴스 API 응답 수신. 총 {len(items)}개 아이템.")
            return items
    except httpx.HTTPStatusError as e:
        logger.error(f"네이버 API HTTP 오류: {e.response.status_code} - {e.response.text}", exc_info=True)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"네이버 API 요청 실패: {e.response.text}"
        )
    except httpx.RequestError as e:
        logger.error(f"네이버 API 요청 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"네이버 API 요청 중 네트워크 오류 발생: {e}"
        )
    except json.JSONDecodeError as e:
        logger.error(f"네이버 API 응답 JSON 파싱 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="네이버 API 응답 형식이 올바르지 않습니다."
        )
    except Exception as e:
        logger.error(f"예상치 못한 오류 발생: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"서버 내부 오류: {e}"
        )

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
    
    # URL 검사 조건 확장: n.news.naver.com 또는 m.entertain.naver.com 허용
    if not (orig_url.startswith("https://n.news.naver.com/") or \
            orig_url.startswith("https://m.entertain.naver.com/")):
        logger.warning(f"naver.me 단축 URL 대상 아님. 지원하지 않는 도메인: {orig_url}")
        return orig_url, "지원하지 않는 네이버 도메인 (n.news.naver.com 또는 m.entertain.naver.com만 지원)"
    
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
            # User-Agent 설정: 아이폰 13 Pro Max (iOS 17.5.1) 기준 User-Agent
            # Viewport 설정: 아이폰 13 Pro Max (428x926) 기준 Viewport
            iphone_13_user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
            iphone_13_viewport = {"width": 428, "height": 926} # iPhone 13 Pro Max 해상도

            page = await browser.new_page(
                viewport=iphone_13_viewport, 
                user_agent=iphone_13_user_agent
            )
            logger.info(f"Playwright 페이지 생성 완료. User-Agent: {iphone_13_user_agent}, Viewport: {iphone_13_viewport}")

            # 리소스 차단 (선택 사항: 페이지 로딩 속도 향상 및 안정성 개선)
            # await page.route("**/*", lambda route: route.abort() if route.request.resource_type in ["image", "stylesheet", "font"] else route.continue())

            await page.goto(orig_url, timeout=20000) # 페이지 로드 타임아웃 증가 (20초)
            # 페이지의 모든 네트워크 요청이 완료될 때까지 대기
            await page.wait_for_loadstate('networkidle') 
            logger.info(f"페이지 로드 완료 및 networkidle 상태 대기 완료: {orig_url}")
            await asyncio.sleep(random.uniform(2.0, 4.0)) # 추가적인 안정화를 위한 대기

            # --- 공유 버튼 찾기 및 클릭 ---
            logger.info("공유 버튼 찾기 시도 시작.")
            share_button_selectors = [
                "span.u_hc",                                   # 일반적인 공유 아이콘 클래스
                "span:has-text('SNS 보내기')",                  # 텍스트 기반 검색
                "#m-toolbar-navernews-share-btn",              # 모바일 툴바의 공유 버튼 ID
                "#toolbar .tool_share",                        # PC 버전 툴바의 공유 버튼
                "button[aria-label*='공유']",                   # 접근성 라벨 기반
                "button[data-tooltip-contents='공유하기']",      # 새로운 속성 기반
                "a[href*='share']",                            # 공유 링크 자체를 찾아볼 수도
                "button.Nicon_share, a.Nicon_share"            # 엔터테인먼트 뉴스 등에서 사용될 수 있는 공유 버튼
            ]
            
            share_button_found = False
            for selector in share_button_selectors:
                logger.debug(f"공유 버튼 선택자 시도 중: {selector}")
                try:
                    # 요소가 나타나고 클릭 가능할 때까지 대기
                    btn = await page.wait_for_selector(selector, timeout=7000, state='visible') 
                    if btn and await btn.is_enabled(): # 버튼이 활성화되어 있는지 확인
                        await btn.click(timeout=3000)
                        logger.info(f"공유 버튼 클릭 성공 (선택자: {selector}).")
                        share_button_found = True
                        break
                    else:
                        logger.debug(f"선택자 '{selector}'의 요소가 보이지 않거나 활성화되지 않았습니다.")
                except Exception as e:
                    logger.debug(f"공유 버튼 선택자 '{selector}' 대기 또는 클릭 실패: {e}")
                    # 디버깅을 위해 실패 시 스크린샷 저장 (로컬에서만 사용 권장)
                    # await page.screenshot(path=f"share_button_fail_{selector.replace(' ', '_').replace(':', '_').replace('#', '')}.png")
                    continue
            
            if not share_button_found:
                logger.warning("모든 공유 버튼 선택자 시도 실패. 공유 버튼을 찾을 수 없습니다.")
                # 디버깅을 위해 스크린샷 저장 (로컬에서만 사용 권장)
                # await page.screenshot(path="share_button_not_found_final.png") 
                return orig_url, "공유 버튼을 찾을 수 없음"
            
            logger.info("공유 팝업 대기 중...")
            await asyncio.sleep(random.uniform(1.5, 3.0)) # 공유 팝업이 뜨는 것을 대기

            # --- 단축 URL 요소 찾기 ---
            logger.info("단축 URL 요소 찾기 시도 시작.")
            link_elem_selectors = [
                "button[data-url^='https://naver.me/']",     # data-url 속성으로 naver.me 주소 바로 찾기 (버튼)
                "span[data-url^='https://naver.me/']",       # data-url 속성으로 naver.me 주소 바로 찾기 (span)
                "a.link_sns[href^='https://naver.me/']",     # href 속성으로 naver.me 주소 바로 찾기 (링크)
                "#spiButton a",                               # 일반적인 단축 URL 복사 버튼 ID
                ".spi_sns_list .link_sns",                    # SNS 공유 리스트 내 링크
                "#clipBtn",                                   # 클립보드 복사 버튼 ID
                "._clipUrlBtn",                               # 클립보드 복사 버튼 클래스
                "input[readonly][value^='https://naver.me/']", # 읽기 전용 input 필드에 URL이 있을 경우
                "div.share_url_area .url_item",               # URL 텍스트가 직접 표시되는 영역
                "div.url_copy_area input[type='text']"        # 엔터테인먼트 뉴스 등에서 사용될 수 있는 URL 복사 input
            ]
            
            short_link = None
            for selector in link_elem_selectors:
                logger.debug(f"단축 URL 요소 선택자 시도 중: {selector}")
                try:
                    # 요소가 나타나고 텍스트를 포함할 때까지 대기
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
                    # 디버깅을 위해 실패 시 스크린샷 저장 (로컬에서만 사용 권장)
                    # await page.screenshot(path=f"short_url_fail_{selector.replace(' ', '_').replace(':', '_').replace('#', '')}.png")
                    continue

            if short_link:
                return short_link, "" # 성공 시 단축 URL과 빈 문자열 반환
            else:
                logger.warning("모든 단축 URL 요소 선택자 시도 실패. naver.me 주소를 찾을 수 없습니다.")
                # 디버깅을 위해 스크린샷 저장 (로컬에서만 사용 권장)
                # await page.screenshot(path="short_url_not_found_final.png") 
                return orig_url, "naver.me 주소를 찾을 수 없음 (최종)"

    except Exception as e:
        logger.error(f"Playwright 오류 발생 (naver_me_shorten): {e}", exc_info=True) # 스택 트레이스 포함
        return orig_url, f"Playwright 오류: {str(e)}"
    finally:
        if browser: # 브라우저 객체가 생성되었다면 확실히 닫아줍니다.
            await browser.close()

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """
    초기 검색 페이지를 렌더링합니다.
    """
    logger.info("GET / 요청 수신. 초기 news_search.html 렌더링.")
    return templates.TemplateResponse(
        "news_search.html", # <-- index.html 대신 news_search.html 렌더링
        {
            'request': request,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'keyword_input': '',
            'final_results': [], # 초기에는 빈 리스트
            'msg': "검색된 뉴스가 없습니다. 키워드나 필터링 조건을 다시 확인해주세요.", # 초기 메시지 추가
            'checked_two_keywords': False, # 기본값 설정
            'search_mode': 'major', # 기본값 설정
            'video_only': False, # 기본값 설정
            'shortened': None,
            'shorten_fail': [],
            'error_message': None
        }
    )

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(...),
    checked_two_keywords: str = Form(""), # 폼 데이터 추가
    search_mode: str = Form("major"), # 폼 데이터 추가
    video_only: str = Form(""), # 폼 데이터 추가
):
    """
    키워드를 받아 네이버 뉴스 API를 검색하고 결과를 표시합니다.
    네이버 뉴스 도메인 (n.news.naver.com 또는 m.entertain.naver.com) 기사만 필터링합니다.
    """
    logger.info(f"POST / 요청 수신. 키워드: '{keywords}', 2개 키워드: {checked_two_keywords}, 검색 모드: {search_mode}, 동영상만: {video_only}")
    kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS
        logger.info("키워드가 없어 기본 키워드 사용.")
    
    # 네이버 API는 'OR' 연산자를 지원합니다.
    query = " OR ".join(kw_list) 
    logger.info(f"네이버 API 검색 쿼리: '{query}'")

    final_results = []
    error_message = None
    msg = ""

    try:
        news_items = await search_naver_news(query)
        
        # 네이버 뉴스 도메인으로만 필터링
        filtered_news_items_by_domain = []
        for item in news_items:
            link = item.get("link", "")
            if link.startswith("https://n.news.naver.com/") or \
               link.startswith("https://m.entertain.naver.com/"):
                filtered_news_items_by_domain.append(item)
            else:
                logger.debug(f"외부 도메인 기사 제외됨: {link}")

        # 추가 필터링 (2개 이상 키워드, 주요 언론사, 동영상만)
        processed_results = []
        for item in filtered_news_items_by_domain:
            title = item.get("title", "").replace("<b>", "").replace("</b>", "")
            press = item.get("publisher", "")
            url = item.get("link", "")
            desc = item.get("description", "").replace("<b>", "").replace("</b>", "")
            pubdate_str = item.get("pubDate", "") # API에서 받은 pubDate 문자열

            # 키워드 매칭 및 카운트
            kwcnt = {}
            for kw in kw_list:
                # re 모듈을 사용하여 정규 표현식 컴파일 및 검색
                pat = re.compile(re.escape(kw), re.IGNORECASE)
                c = pat.findall(title + " " + desc)
                if c: kwcnt[kw] = len(c)

            # 2개 이상 키워드 포함 필터링
            if checked_two_keywords == "on" and len(kwcnt) < 2:
                logger.debug(f"2개 이상 키워드 필터링: '{title}'. 키워드 부족. 제외됨.")
                continue

            # 주요 언론사 필터링
            # search_mode가 'major'이고, 언론사 이름이 있으며, 해당 언론사가 주요 언론사 목록에 없으면 제외
            if search_mode == "major" and press: # press가 비어있지 않은 경우에만 검사
                # 대소문자 구분 없이 비교하기 위해 모두 소문자로 변환
                if press.lower() not in [p.lower() for p in PRESS_MAJOR]:
                    logger.debug(f"주요 언론사 필터링: '{title}' - {press}. 제외됨.")
                    continue

            # 동영상만 필터링 (네이버 API 응답에는 직접적인 동영상 여부 필드가 없을 수 있으므로, URL로 추정)
            if video_only == "on":
                # 현재 API 검색에서는 동영상 필터링을 위한 명확한 필드가 없으므로,
                # 이 부분은 Playwright 기반의 웹 스크래핑에서 더 유용합니다.
                # API를 통한 동영상 필터링은 네이버 API 문서 확인 후 추가 구현이 필요합니다.
                pass 

            # pubDate 문자열을 datetime 객체로 파싱
            parsed_pubdate = parse_api_pubdate(pubdate_str)
            
            processed_results.append({
                "title": title,
                "press": press,
                "pubdate": parsed_pubdate, # datetime 객체로 저장 (정렬용)
                "pubdate_display": parsed_pubdate.strftime('%Y-%m-%d %H:%M') if parsed_pubdate else pubdate_str, # 표시용 문자열
                "url": url,
                "desc": desc,
                "keywords": sorted(kwcnt.items(), key=lambda x:(-x[1], x[0])),
                "kw_count": sum(kwcnt.values())
            })
        
        # 최종 정렬 (키워드 빈도수 내림차순, 발행일 오름차순)
        # pubdate가 None인 경우를 대비하여 None 값을 가장 작은 값으로 처리하거나, 정렬 키에서 제외
        # 여기서는 None 값을 가진 항목이 정렬 순서에서 뒤로 가도록 처리 (None 비교는 파이썬 3에서 가능)
        processed_results.sort(key=lambda x: (-x['kw_count'], x['pubdate'] if x['pubdate'] is not None else datetime.min), reverse=False)
        final_results = processed_results
        
        msg = f"총 {len(final_results)}건의 뉴스가 검색되었습니다."
        if not final_results:
            msg = "검색된 뉴스가 없습니다. 키워드나 필터링 조건을 다시 확인해주세요."

        logger.info(f"네이버 뉴스 검색 결과 (최종 필터링 후): 총 {len(final_results)}건.")

    except HTTPException as e:
        error_message = f"뉴스 검색 중 오류 발생: {e.detail}"
        logger.error(error_message)
        msg = f"오류 발생: {e.detail}"
    except Exception as e:
        error_message = f"예상치 못한 오류 발생: {e}"
        logger.error(error_message, exc_info=True)
        msg = f"오류 발생: {e}"

    # final_results를 템플릿으로 전달하기 전에 pubdate를 문자열로 변환
    # JSON 직렬화 오류를 방지하기 위함
    serializable_final_results = []
    for item in final_results:
        serializable_item = item.copy() # 원본 딕셔너리 변경 방지
        if serializable_item['pubdate'] is not None:
            serializable_item['pubdate'] = serializable_item['pubdate'].isoformat() # ISO 8601 문자열로 변환
        serializable_final_results.append(serializable_item)


    return templates.TemplateResponse(
        "news_search.html", # <-- news_search.html 렌더링
        {
            'request': request,
            'final_results': serializable_final_results, # 직렬화된 결과 전달
            'keyword_input': keywords,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'msg': msg,
            'checked_two_keywords': checked_two_keywords == "on",
            'search_mode': search_mode,
            'video_only': video_only == "on",
            'shortened': None,
            'shorten_fail': [],
            'error_message': error_message
        }
    )

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: list = Form(..., description="선택된 URL의 인덱스 목록"),
    final_results_json: str = Form(..., description="검색 결과 JSON 문자열"),
    keyword_input: str = Form('', description="이전 검색 키워드 입력"),
    checked_two_keywords: str = Form(""), # 폼 데이터 추가
    search_mode: str = Form("major"), # 폼 데이터 추가
    video_only: str = Form(""), # 폼 데이터 추가
):
    """
    선택된 뉴스 URL들을 실제 Playwright를 사용하여 naver.me URL로 단축하여 표시합니다.
    """
    logger.info(f"POST /shorten 요청 수신. 선택된 URL 인덱스: {selected_urls}")
    final_results = []
    error_message = None
    try:
        # JSON 문자열을 파싱할 때, pubdate 필드가 ISO 문자열로 되어 있을 것이므로,
        # 다시 datetime 객체로 변환하여 내부 로직(정렬 등)에서 사용할 수 있도록 합니다.
        parsed_json_results = json.loads(final_results_json)
        for item in parsed_json_results:
            if 'pubdate' in item and item['pubdate']:
                try:
                    item['pubdate'] = datetime.fromisoformat(item['pubdate'])
                except ValueError:
                    logger.warning(f"JSON에서 pubdate 파싱 실패: {item['pubdate']}. 문자열로 유지.")
                    item['pubdate'] = None # 파싱 실패 시 None으로 설정하여 정렬 오류 방지
            else:
                item['pubdate'] = None # pubdate가 없거나 비어 있으면 None으로 설정

        final_results = parsed_json_results
        logger.info(f"JSON 로드 완료. 총 {len(final_results)}개 결과.")
    except json.JSONDecodeError as e:
        error_message = f"검색 결과 JSON 파싱 오류: {e}"
        logger.error(error_message, exc_info=True)
        # JSON 파싱 실패 시 빈 결과로 진행
        final_results = [] 

    shortened_list = []
    shorten_fail_list = [] # 실패 목록 추가
    
    # 병렬 처리를 위한 태스크 생성
    tasks = []
    selected_articles_info = [] # 단축 변환할 기사 정보 저장
    for idx_str in selected_urls:
        try:
            idx = int(idx_str)
            if 0 <= idx < len(final_results):
                selected_articles_info.append(final_results[idx])
                tasks.append(naver_me_shorten(final_results[idx]['url']))
            else:
                logger.warning(f"유효하지 않은 인덱스 선택됨: {idx_str}. 총 결과 수: {len(final_results)}")
                shorten_fail_list.append(f"유효하지 않은 뉴스 선택 (인덱스: {idx_str})")
        except ValueError:
            logger.error(f"선택된 URL 인덱스 파싱 오류: '{idx_str}'는 정수가 아닙니다.", exc_info=True)
            shorten_fail_list.append(f"선택된 뉴스 인덱스 형식이 잘못됨 (값: {idx_str})")
        except Exception as e:
            logger.error(f"URL 선택 처리 중 예상치 못한 오류 발생: {e}", exc_info=True)
            shorten_fail_list.append(f"URL 선택 처리 중 오류: {e}")

    if not tasks and not shorten_fail_list: # 선택된 URL이 전혀 없는 경우
        logger.warning("단축 변환할 선택된 기사가 없습니다.")
        error_message = "단축할 뉴스를 선택해주세요."

    # Playwright 작업 병렬 실행
    if tasks:
        shorten_results = await asyncio.gather(*tasks)

        for i, (short_url, fail_reason) in enumerate(shorten_results):
            art = selected_articles_info[i] # 원래 기사 정보 가져오기
            if fail_reason:
                shorten_fail_list.append(f"'{art['title']}': {fail_reason}")
                logger.error(f"'{art['title']}' 단축 변환 실패: {fail_reason}")
            else:
                line = f"■ {art['title']} ({art['press']})\n{short_url}"
                shortened_list.append(line)
                logger.info(f"'{art['title']}' 단축 변환 성공.")
            
    logger.info(f"URL 단축 처리 완료. 성공: {len(shortened_list)}건, 실패: {len(shorten_fail_list)}건")
    
    msg = f"총 {len(final_results)}건의 뉴스가 검색되었습니다."
    if shortened_list:
        msg += f" (단축 성공: {len(shortened_list) - len(shorten_fail_list)}건, 실패: {len(shorten_fail_list)}건)"

    # final_results를 템플릿으로 전달하기 전에 pubdate를 문자열로 다시 변환
    # JSON 직렬화 오류를 방지하기 위함
    serializable_final_results_for_template = []
    for item in final_results:
        serializable_item = item.copy()
        if 'pubdate' in serializable_item and serializable_item['pubdate'] is not None:
            serializable_item['pubdate'] = serializable_item['pubdate'].isoformat()
        serializable_final_results_for_template.append(serializable_item)


    return templates.TemplateResponse(
        "news_search.html", # <-- news_search.html 렌더링
        {
            'request': request,
            'final_results': serializable_final_results_for_template, # 직렬화된 결과 전달
            'shortened': '\n\n'.join(shortened_list),
            'shorten_fail': shorten_fail_list, # 실패 목록 전달
            'keyword_input': keyword_input,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'msg': msg,
            'checked_two_keywords': checked_two_keywords == "on",
            'search_mode': search_mode,
            'video_only': video_only == "on",
            'error_message': error_message
        }
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
