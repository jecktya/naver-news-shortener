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
import logging # 로깅 모듈 임포트

# 로거 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
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
    news_cards = soup.select(".news_area, .bx")
    now = datetime.now()
    results = []
    
    if not news_cards:
        logger.warning("뉴스 카드 요소를 찾을 수 없습니다. HTML 구조 변경 가능성 또는 검색 결과 없음.")
        logger.debug(f"받은 HTML 미리보기: {html[:500]}...") # HTML의 앞부분 500자 로깅

    for card in news_cards:
        a = card.select_one("a.news_tit, a")
        if not a: 
            logger.debug("뉴스 제목/링크 요소를 찾을 수 없습니다. 다음 카드로 이동.")
            continue
        title = a["title"] if a.has_attr("title") else a.get_text(strip=True)
        url = a["href"]
        press = card.select_one(".info.press")
        press_name = press.get_text(strip=True).replace("언론사 선정", "") if press else ""
        desc = card.select_one(".dsc_wrap") or card.select_one(".desc")
        desc_txt = desc.get_text(" ", strip=True) if desc else ""
        pubdate = card.select_one(".info_group .date, .info .date")
        pub_str = pubdate.get_text(strip=True) if pubdate else ""
        pub_kst = parse_time(pub_str)
        
        if not pub_kst or (now - pub_kst > timedelta(hours=4)):
            logger.debug(f"뉴스 시간 필터링: '{title}' - {pub_str} ({pub_kst}). 4시간 초과 또는 파싱 실패.")
            continue
        if search_mode=="major" and press_name and press_name not in PRESS_MAJOR:
            logger.debug(f"주요 언론사 필터링: '{title}' - {press_name}. 제외됨.")
            continue
        if video_only:
            if not card.select_one("a.news_thumb[href*='tv.naver.com'], a.news_thumb[href*='video.naver.com'], span[class*=video]"):
                logger.debug(f"동영상 필터링: '{title}'. 동영상 아님.")
                continue
        
        kwcnt = {}
        for kw in keywords:
            pat = re.compile(re.escape(kw), re.IGNORECASE)
            c = pat.findall(title+desc_txt)
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
        min_ago = int(timestr.split("분")[0])
        return now - timedelta(minutes=min_ago)
    if "시간 전" in timestr:
        hr_ago = int(timestr.split("시간")[0])
        return now - timedelta(hours=hr_ago)
    try:
        if re.match(r"\d{4}\.\d{2}\.\d{2}", timestr):
            t = datetime.strptime(timestr, "%Y.%m.%d.")
            return t.replace(hour=0, minute=0)
    except Exception as e:
        logger.error(f"시간 파싱 오류: '{timestr}' - {e}")
        pass
    return now

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
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(url, headers=headers)
            logger.info(f"뉴스 검색 HTML 응답 수신. 상태 코드: {r.status_code}")
            r.raise_for_status()
            logger.debug(f"응답 HTML 미리보기 (get_news_html): {r.text[:500]}...") # 응답 HTML 앞부분 로깅
            return r.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP 상태 오류 (get_news_html): {e.response.status_code} - {e.response.text[:200]}...") # 오류 응답 텍스트 일부 로깅
            return ""
        except httpx.RequestError as e:
            logger.error(f"요청 오류 발생 (get_news_html): {e}")
            return ""
        except Exception as e:
            logger.error(f"예상치 못한 오류 발생 (get_news_html): {e}")
            return ""

from playwright.async_api import async_playwright

async def naver_me_shorten(orig_url):
    logger.info(f"naver.me 단축 URL 변환 시도 시작. 원본 URL: {orig_url}")
    if not orig_url.startswith("https://n.news.naver.com/"): 
        logger.warning("naver.me 단축 URL 대상 아님.")
        return orig_url, "n.news.naver.com 아님"
    try:
        async with async_playwright() as p:
            # ### 중요: 디버깅을 위해 headless=False로 설정. 문제 해결 후 True로 변경 권장 ###
            browser = await p.chromium.launch(
                headless=False, # 디버깅용: 브라우저 창을 띄워서 동작 확인
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu'
                ]
            )
            latest_user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
            page = await browser.new_page(
                viewport={"width":400, "height":800},
                user_agent=latest_user_agent
            )
            logger.info(f"Playwright 페이지 생성 완료. User-Agent: {latest_user_agent}")

            await page.goto(orig_url, timeout=8000)
            logger.info(f"페이지 로드 완료: {orig_url}")
            await asyncio.sleep(random.uniform(1.5, 3.5))

            share_button_selector = "span.u_hc, span:has-text('SNS 보내기'), #m-toolbar-navernews-share-btn, #toolbar .tool_share" # 추가 선택자
            logger.info(f"공유 버튼 선택자 대기 중: {share_button_selector}")
            try:
                await page.wait_for_selector(share_button_selector, timeout=7000)
                logger.info("공유 버튼 선택자 발견.")
            except Exception as e:
                logger.warning(f"공유 버튼 선택자 대기 실패: {e}")
                await browser.close()
                return orig_url, "공유 버튼 selector 대기 실패"
            
            await asyncio.sleep(random.uniform(0.7, 1.8))

            btn = await page.query_selector(share_button_selector)
            if not btn:
                logger.warning("공유 버튼 요소를 찾을 수 없습니다.")
                await browser.close()
                return orig_url, "공유 버튼 요소 못찾음"
            
            await btn.click()
            logger.info("공유 버튼 클릭 완료.")
            await asyncio.sleep(random.uniform(1.0, 2.5))

            link_elem_selector = "#spiButton a, .spi_sns_list .link_sns, #clipBtn, ._clipUrlBtn" # 추가 선택자
            logger.info(f"단축 URL 요소 선택자 대기 중: {link_elem_selector}")
            try:
                await page.wait_for_selector(link_elem_selector, timeout=6000)
                logger.info("단축 URL 요소 선택자 발견.")
            except Exception as e:
                logger.warning(f"단축 URL 요소 선택자 대기 실패: {e}")
                await browser.close()
                return orig_url, "단축 URL 요소 대기 실패"
            
            await asyncio.sleep(random.uniform(0.5, 1.0))

            link_elem = await page.query_selector(link_elem_selector)
            if not link_elem:
                logger.warning("단축 URL 요소를 찾을 수 없습니다.")
                await browser.close()
                return orig_url, "단축 URL 요소 못찾음 (최종)"
            
            link = await link_elem.get_attribute("data-url") # data-url 속성 먼저 시도
            if not link:
                # data-url이 없으면 href 속성 시도 (혹은 innerText 등)
                link = await link_elem.get_attribute("href")
                if not link:
                    link = await link_elem.inner_text() # 텍스트 내용 시도
            
            await browser.close()
            
            if link and link.startswith("https://naver.me/"):
                logger.info(f"단축 URL 변환 성공: {link}")
                return link, ""
            
            logger.warning(f"naver.me 주소 아님 또는 유효하지 않은 링크: {link}")
            return orig_url, f"naver.me 주소 못찾음 (최종 링크: {link})"
    except Exception as e:
        logger.error(f"Playwright 오류 발생 (naver_me_shorten): {e}", exc_info=True) # 스택 트레이스 포함
        return orig_url, f"Playwright 오류: {str(e)}"

@app.get("/", response_class=None)
async def main(request: Request):
    logger.info("메인 페이지 GET 요청 수신.")
    return await render_news(request)

@app.post("/", response_class=None)
async def main_post(request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(""),
    search_mode: str = Form("major"),
    video_only: str = Form(""),
):
    logger.info(f"메인 페이지 POST 요청 수신. 키워드: '{keywords}', 모드: {search_mode}")
    return await render_news(request, keywords, checked_two_keywords, search_mode, video_only)

async def render_news(request, keywords="", checked_two_keywords="", search_mode="major", video_only=""):
    kwlist = [k.strip() for k in re.split(r"[,\|]", keywords) if k.strip()]
    if not kwlist:
        kwlist = DEFAULT_KEYWORDS
        logger.info("키워드가 없어 기본 키워드 사용.")
    
    query = " | ".join(kwlist)
    logger.info(f"검색 쿼리: '{query}'")
    
    html = await get_news_html(query, video_only=="on")
    if not html:
        logger.error("네이버 뉴스 HTML을 가져오는데 실패했습니다. 파싱 건너뛰기.")
        newslist = [] # HTML을 가져오지 못했으므로 빈 리스트
    else:
        newslist = parse_newslist(html, kwlist, search_mode, video_only=="on")
        
    checked_two = checked_two_keywords=="on"
    filtered = [a for a in newslist if len([kw_cnt for kw, kw_cnt in a['keywords'] if kw_cnt > 0]) >= 2] if checked_two else newslist
    
    msg = f"총 {len(filtered)}건의 뉴스가 검색되었습니다."
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
    logger.info(f"단축 URL 변환 요청 수신. 선택된 URL 수: {len(selected_urls)}")
    kwlist = [k.strip() for k in re.split(r"[,\|]", keywords) if k.strip()]
    if not kwlist:
        kwlist = DEFAULT_KEYWORDS
    query = " | ".join(kwlist)

    html = await get_news_html(query, video_only=="on")
    if not html:
        logger.error("네이버 뉴스 HTML을 가져오는데 실패했습니다. 단축 변환 진행 불가.")
        # 이 경우, filtered는 빈 리스트가 될 가능성이 높음.
        # 사용자에게 이를 알리는 메시지 추가 고려 가능.
        newslist = []
    else:
        newslist = parse_newslist(html, kwlist, search_mode, video_only=="on")
    
    checked_two = checked_two_keywords=="on"
    filtered = [a for a in newslist if len([kw_cnt for kw, kw_cnt in a['keywords'] if kw_cnt > 0]) >= 2] if checked_two else newslist
    
    idx_set = set(map(int, selected_urls)) if isinstance(selected_urls, list) else set()
    selected = [filtered[i] for i in idx_set if 0<=i<len(filtered)]
    
    shortened_lines = []
    shorten_fail = []
    
    if not selected:
        logger.warning("단축 변환할 선택된 기사가 없습니다.")

    for art in selected:
        short_url, fail = await naver_me_shorten(art["url"])
        line = f"■ {art['title']} ({art['press']})\n{short_url}"
        shortened_lines.append(line)
        if fail:
            shorten_fail.append(f"{art['title']}: {fail}")
            logger.error(f"'{art['title']}' 단축 변환 실패: {fail}")
        else:
            logger.info(f"'{art['title']}' 단축 변환 성공.")
            
    msg = f"총 {len(filtered)}건의 뉴스가 검색되었습니다."
    logger.info(f"단축 변환 처리 완료. 성공: {len(shortened_lines) - len(shorten_fail)}건, 실패: {len(shorten_fail)}건")
    
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

