# app.py
# -*- coding: utf-8 -*-

import os
import json
import random
import string
import logging
import asyncio
import re
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# 로거 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")

logger.info("="*35)
logger.info(f"NAVER_CLIENT_ID: {NAVER_CLIENT_ID}")
logger.info(f"NAVER_CLIENT_SECRET: {NAVER_CLIENT_SECRET[:4]}{'*'*(len(NAVER_CLIENT_SECRET)-4)}")
logger.info("="*35)

NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

templates = Jinja2Templates(directory="templates")
templates.env.globals["enumerate"] = enumerate

app = FastAPI(title="뉴스검색기 (FastAPI+NaverAPI)")

DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]

PRESS_MAJOR = {
    '연합뉴스', '조선일보', '한겨레', '중앙일보',
    'MBN', 'KBS', 'SBS', 'YTN',
    '동아일보', '세계일보', '문화일보', '뉴시스',
    '국민일보', '국방일보', '이데일리',
    '뉴스1', 'JTBC'
}

def parse_api_pubdate(pubdate_str: str) -> Optional[datetime]:
    if not pubdate_str:
        return None
    try:
        date_time_part = pubdate_str[:-6].strip()
        return datetime.strptime(date_time_part, "%a, %d %b %Y %H:%M:%S")
    except ValueError as e:
        logger.error(f"pubDate 파싱 실패 ('{pubdate_str}'): {e}", exc_info=True)
        return None
    except Exception as e:
        logger.error(f"pubDate 파싱 중 예상치 못한 오류: {e}", exc_info=True)
        return None

async def search_naver_news(query: str, display: int = 10):
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
        "sort": "date",
    }
    logger.info(f"네이버 뉴스 API 요청 시작. 쿼리: '{query}', 표시 개수: {display}")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
            res.raise_for_status()
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

# ---- 아래 함수가 핵심! (Streamlit식 합산) ----
async def search_naver_news_multi_keywords(kw_list, display=10):
    """
    키워드별로 각각 네이버 뉴스 API를 호출하여 결과를 합치고,
    기사별로 어떤 키워드를 포함하는지, 몇 개 포함하는지까지 분석한다.
    """
    all_articles = {}
    for kw in kw_list:
        items = await search_naver_news(kw, display)
        for a in items:
            url = a.get("link", "")
            if not (url.startswith("https://n.news.naver.com/") or url.startswith("https://m.entertain.naver.com/")):
                continue
            if url not in all_articles:
                all_articles[url] = {
                    "title": a.get("title", "").replace("<b>", "").replace("</b>", ""),
                    "press": a.get("publisher", ""),
                    "pubdate": a.get("pubDate", ""),
                    "url": url,
                    "desc": a.get("description", "").replace("<b>", "").replace("</b>", ""),
                    "matched": set(),
                }
            all_articles[url]["matched"].add(kw)
    articles = []
    for v in all_articles.values():
        v["matched"] = sorted(v["matched"])
        v["kw_count"] = len(v["matched"])
        articles.append(v)
    articles = sorted(
        articles,
        key=lambda x: (x["kw_count"], x["pubdate"]),
        reverse=True
    )
    return articles

async def naver_me_shorten(orig_url: str) -> tuple[str, str]:
    from playwright.async_api import async_playwright
    logger.info(f"naver.me 단축 URL 변환 시도 시작. 원본 URL: {orig_url}")

    if not (orig_url.startswith("https://n.news.naver.com/") or \
            orig_url.startswith("https://m.entertain.naver.com/")):
        logger.warning(f"naver.me 단축 URL 대상 아님. 지원하지 않는 도메인: {orig_url}")
        return orig_url, "지원하지 않는 네이버 도메인 (n.news.naver.com 또는 m.entertain.naver.com만 지원)"

    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu',
                '--start-maximized'
            ])
            iphone_13_user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
            iphone_13_viewport = {"width": 428, "height": 926}
            page = await browser.new_page(
                viewport=iphone_13_viewport, 
                user_agent=iphone_13_user_agent
            )
            logger.info(f"Playwright 페이지 생성 완료. User-Agent: {iphone_13_user_agent}, Viewport: {iphone_13_viewport}")

            await page.goto(orig_url, timeout=20000)
            await page.wait_for_load_state('networkidle')
            logger.info(f"페이지 로드 완료 및 networkidle 상태 대기 완료: {orig_url}")
            await asyncio.sleep(random.uniform(2.0, 4.0))

            share_button_selectors = [
                "span.u_hc", "span:has-text('SNS 보내기')", "#m-toolbar-navernews-share-btn",
                "#toolbar .tool_share", "button[aria-label*='공유']", "button[data-tooltip-contents='공유하기']",
                "a[href*='share']", "button.Nicon_share, a.Nicon_share"
            ]
            share_button_found = False
            for selector in share_button_selectors:
                logger.debug(f"공유 버튼 선택자 시도 중: {selector}")
                try:
                    btn = await page.wait_for_selector(selector, timeout=7000, state='visible') 
                    if btn and await btn.is_enabled():
                        await btn.click(timeout=3000)
                        logger.info(f"공유 버튼 클릭 성공 (선택자: {selector}).")
                        share_button_found = True
                        break
                except Exception as e:
                    logger.debug(f"공유 버튼 선택자 '{selector}' 대기 또는 클릭 실패: {e}")
                    continue
            if not share_button_found:
                logger.warning("모든 공유 버튼 선택자 시도 실패. 공유 버튼을 찾을 수 없습니다.")
                return orig_url, "공유 버튼을 찾을 수 없음"

            logger.info("공유 팝업 대기 중...")
            await asyncio.sleep(random.uniform(1.5, 3.0))
            link_elem_selectors = [
                "button[data-url^='https://naver.me/']",
                "span[data-url^='https://naver.me/']",
                "a.link_sns[href^='https://naver.me/']",
                "#spiButton a",
                ".spi_sns_list .link_sns",
                "#clipBtn",
                "._clipUrlBtn",
                "input[readonly][value^='https://naver.me/']",
                "div.share_url_area .url_item",
                "div.url_copy_area input[type='text']"
            ]
            short_link = None
            for selector in link_elem_selectors:
                logger.debug(f"단축 URL 요소 선택자 시도 중: {selector}")
                try:
                    link_elem = await page.wait_for_selector(selector, timeout=6000, state='visible')
                    if link_elem and await link_elem.is_visible():
                        link = await link_elem.get_attribute("data-url")
                        if not link:
                            link = await link_elem.get_attribute("href")
                        if not link:
                            link = await link_elem.get_attribute("value")
                        if not link:
                            link = await link_elem.inner_text()
                        if link and link.startswith("https://naver.me/"):
                            short_link = link
                            logger.info(f"단축 URL 변환 성공 (선택자: {selector}, 최종 URL: {short_link})")
                            break
                except Exception as e:
                    logger.debug(f"단축 URL 요소 선택자 '{selector}' 대기 실패: {e}")
                    continue
            if short_link:
                return short_link, ""
            else:
                logger.warning("모든 단축 URL 요소 선택자 시도 실패. naver.me 주소를 찾을 수 없습니다.")
                return orig_url, "naver.me 주소를 찾을 수 없음 (최종)"
    except Exception as e:
        logger.error(f"Playwright 오류 발생 (naver_me_shorten): {e}", exc_info=True)
        return orig_url, f"Playwright 오류: {str(e)}"
    finally:
        if browser:
            await browser.close()

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    logger.info("GET / 요청 수신. 초기 news_search.html 렌더링.")
    return templates.TemplateResponse(
        "news_search.html",
        {
            'request': request,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'keyword_input': '',
            'final_results': [],
            'msg': "검색된 뉴스가 없습니다. 키워드나 필터링 조건을 다시 확인해주세요.",
            'checked_two_keywords': False,
            'search_mode': 'major',
            'video_only': False,
            'shortened': None,
            'shorten_fail': [],
            'error_message': None
        }
    )

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(...),
    checked_two_keywords: str = Form(""),
    search_mode: str = Form("major"),
    video_only: str = Form(""),
):
    logger.info(f"POST / 요청 수신. 키워드: '{keywords}', 2개 키워드: {checked_two_keywords}, 검색 모드: {search_mode}, 동영상만: {video_only}")
    kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS
        logger.info("키워드가 없어 기본 키워드 사용.")

    # >>> Streamlit 스타일(키워드별 검색, 합산)
    all_results = await search_naver_news_multi_keywords(kw_list)

    # 추가 필터링
    processed_results = []
    for item in all_results:
        title = item["title"]
        press = item["press"]
        url = item["url"]
        desc = item["desc"]
        pubdate_str = item.get("pubdate", "")
        matched_keywords = item["matched"]
        kw_count = item["kw_count"]

        # 2개 이상 키워드 포함 필터링
        if checked_two_keywords == "on" and kw_count < 2:
            continue

        # 주요 언론사 필터링
        if search_mode == "major" and press:
            if press.lower() not in [p.lower() for p in PRESS_MAJOR]:
                continue

        # 동영상만 필터링(구현 필요시 추가)

        # pubDate 파싱
        parsed_pubdate = parse_api_pubdate(pubdate_str)

        processed_results.append({
            "title": title,
            "press": press,
            "pubdate": parsed_pubdate,
            "pubdate_display": parsed_pubdate.strftime('%Y-%m-%d %H:%M') if parsed_pubdate else pubdate_str,
            "url": url,
            "desc": desc,
            "keywords": matched_keywords,
            "kw_count": kw_count
        })

    # 정렬
    processed_results.sort(key=lambda x: (-x['kw_count'], x['pubdate'] if x['pubdate'] else datetime.min), reverse=False)
    final_results = processed_results
    msg = f"총 {len(final_results)}건의 뉴스가 검색되었습니다."
    if not final_results:
        msg = "검색된 뉴스가 없습니다. 키워드나 필터링 조건을 다시 확인해주세요."
    logger.info(f"네이버 뉴스 검색 결과 (최종 필터링 후): 총 {len(final_results)}건.")

    # 직렬화
    serializable_final_results = []
    for item in final_results:
        serializable_item = item.copy()
        if serializable_item['pubdate'] is not None:
            serializable_item['pubdate'] = serializable_item['pubdate'].isoformat()
        serializable_final_results.append(serializable_item)

    return templates.TemplateResponse(
        "news_search.html",
        {
            'request': request,
            'final_results': serializable_final_results,
            'keyword_input': keywords,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'msg': msg,
            'checked_two_keywords': checked_two_keywords == "on",
            'search_mode': search_mode,
            'video_only': video_only == "on",
            'shortened': None,
            'shorten_fail': [],
            'error_message': None
        }
    )

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: list = Form(..., description="선택된 URL의 인덱스 목록"),
    final_results_json: str = Form(..., description="검색 결과 JSON 문자열"),
    keyword_input: str = Form('', description="이전 검색 키워드 입력"),
    checked_two_keywords: str = Form(""),
    search_mode: str = Form("major"),
    video_only: str = Form(""),
):
    logger.info(f"POST /shorten 요청 수신. 선택된 URL 인덱스: {selected_urls}")
    final_results = []
    error_message = None
    try:
        parsed_json_results = json.loads(final_results_json)
        for item in parsed_json_results:
            if 'pubdate' in item and item['pubdate']:
                try:
                    item['pubdate'] = datetime.fromisoformat(item['pubdate'])
                except ValueError:
                    logger.warning(f"JSON에서 pubdate 파싱 실패: {item['pubdate']}. 문자열로 유지.")
                    item['pubdate'] = None
            else:
                item['pubdate'] = None
        final_results = parsed_json_results
        logger.info(f"JSON 로드 완료. 총 {len(final_results)}개 결과.")
    except json.JSONDecodeError as e:
        error_message = f"검색 결과 JSON 파싱 오류: {e}"
        logger.error(error_message, exc_info=True)
        final_results = [] 

    shortened_list = []
    shorten_fail_list = []
    tasks = []
    selected_articles_info = []
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

    if not tasks and not shorten_fail_list:
        logger.warning("단축 변환할 선택된 기사가 없습니다.")
        error_message = "단축할 뉴스를 선택해주세요."

    if tasks:
        shorten_results = await asyncio.gather(*tasks)
        for i, (short_url, fail_reason) in enumerate(shorten_results):
            art = selected_articles_info[i]
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

    serializable_final_results_for_template = []
    for item in final_results:
        serializable_item = item.copy()
        if 'pubdate' in serializable_item and serializable_item['pubdate'] is not None:
            serializable_item['pubdate'] = serializable_item['pubdate'].isoformat()
        serializable_final_results_for_template.append(serializable_item)

    return templates.TemplateResponse(
        "news_search.html",
        {
            'request': request,
            'final_results': serializable_final_results_for_template,
            'shortened': '\n\n'.join(shortened_list),
            'shorten_fail': shorten_fail_list,
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
