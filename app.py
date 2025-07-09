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
from datetime import datetime
from typing import List, Dict, Optional

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
templates.env.globals["enumerate"] = enumerate  # Jinja2에서 enumerate 사용 가능하게

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
    except Exception as e:
        logger.error(f"pubDate 파싱 실패 ('{pubdate_str}'): {e}", exc_info=True)
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
    except Exception as e:
        logger.error(f"네이버 뉴스 API 호출 오류: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="네이버 API 호출 오류"
        )

async def naver_me_shorten(orig_url: str) -> tuple[str, str]:
    from playwright.async_api import async_playwright
    logger.info(f"naver.me 단축 URL 변환 시도 시작. 원본 URL: {orig_url}")

    if not (orig_url.startswith("https://n.news.naver.com/") or
            orig_url.startswith("https://m.entertain.naver.com/")):
        return orig_url, "지원하지 않는 네이버 도메인"

    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas', '--disable-gpu', '--start-maximized'
            ])
            iphone_13_user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
            iphone_13_viewport = {"width": 428, "height": 926}
            page = await browser.new_page(viewport=iphone_13_viewport, user_agent=iphone_13_user_agent)
            logger.info(f"Playwright 페이지 생성 완료. User-Agent: {iphone_13_user_agent}, Viewport: {iphone_13_viewport}")

            await page.goto(orig_url, timeout=20000)
            await page.wait_for_load_state('networkidle')
            await asyncio.sleep(random.uniform(2.0, 4.0))

            share_button_selectors = [
                "span.u_hc", "span:has-text('SNS 보내기')", "#m-toolbar-navernews-share-btn",
                "#toolbar .tool_share", "button[aria-label*='공유']",
                "button[data-tooltip-contents='공유하기']", "a[href*='share']",
                "button.Nicon_share, a.Nicon_share"
            ]
            share_button_found = False
            for selector in share_button_selectors:
                try:
                    btn = await page.wait_for_selector(selector, timeout=7000, state='visible')
                    if btn and await btn.is_enabled():
                        await btn.click(timeout=3000)
                        logger.info(f"공유 버튼 클릭 성공 (선택자: {selector}).")
                        share_button_found = True
                        break
                except Exception:
                    continue
            if not share_button_found:
                return orig_url, "공유 버튼을 찾을 수 없음"

            await asyncio.sleep(random.uniform(1.5, 3.0))
            link_elem_selectors = [
                "button[data-url^='https://naver.me/']",
                "span[data-url^='https://naver.me/']",
                "a.link_sns[href^='https://naver.me/']",
                "#spiButton a", ".spi_sns_list .link_sns", "#clipBtn",
                "._clipUrlBtn", "input[readonly][value^='https://naver.me/']",
                "div.share_url_area .url_item", "div.url_copy_area input[type='text']"
            ]
            short_link = None
            for selector in link_elem_selectors:
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
                            break
                except Exception:
                    continue
            if short_link:
                return short_link, ""
            else:
                return orig_url, "naver.me 주소를 찾을 수 없음"
    except Exception as e:
        logger.error(f"Playwright 오류 발생 (naver_me_shorten): {e}", exc_info=True)
        return orig_url, f"Playwright 오류: {str(e)}"
    finally:
        if browser:
            await browser.close()

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
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
    video_only: str = Form("")
):
    logger.info(f"POST / 요청 수신. 키워드: '{keywords}', 2개 키워드: {checked_two_keywords}, 검색 모드: {search_mode}, 동영상만: {video_only}")
    kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS
    query = " OR ".join(kw_list)
    logger.info(f"네이버 API 검색 쿼리: '{query}'")

    final_results = []
    error_message = None
    msg = ""

    try:
        news_items = await search_naver_news(query)
        filtered_news_items_by_domain = []
        for item in news_items:
            link = item.get("link", "")
            if link.startswith("https://n.news.naver.com/") or link.startswith("https://m.entertain.naver.com/"):
                filtered_news_items_by_domain.append(item)
        processed_results = []
        for item in filtered_news_items_by_domain:
            title = item.get("title", "").replace("<b>", "").replace("</b>", "")
            press = item.get("publisher", "")
            url = item.get("link", "")
            desc = item.get("description", "").replace("<b>", "").replace("</b>", "")
            pubdate_str = item.get("pubDate", "")
            # 키워드 매칭 및 카운트
            kwcnt = {}
            for kw in kw_list:
                pat = re.compile(re.escape(kw), re.IGNORECASE)
                c = pat.findall(title + " " + desc)
                if c: kwcnt[kw] = len(c)
            # 2개 이상 키워드 포함 필터링
            if checked_two_keywords == "on" and len(kwcnt) < 2:
                continue
            if search_mode == "major" and press:
                if press.lower() not in [p.lower() for p in PRESS_MAJOR]:
                    continue
            if video_only == "on":
                pass
            parsed_pubdate = parse_api_pubdate(pubdate_str)
            # <== KEY: keywords 리스트를 [(kw, cnt)] 로 보내기
            keywords_list = sorted([(k, v) for k, v in kwcnt.items()], key=lambda x:(-x[1], x[0]))
            processed_results.append({
                "title": title,
                "press": press,
                "pubdate": parsed_pubdate,
                "pubdate_display": parsed_pubdate.strftime('%Y-%m-%d %H:%M') if parsed_pubdate else pubdate_str,
                "url": url,
                "desc": desc,
                "keywords": keywords_list,   # <- 여기가 포인트!
                "kw_count": sum(kwcnt.values())
            })
        processed_results.sort(key=lambda x: (-x['kw_count'], x['pubdate'] if x['pubdate'] else datetime.min), reverse=False)
        final_results = processed_results
        msg = f"총 {len(final_results)}건의 뉴스가 검색되었습니다."
        if not final_results:
            msg = "검색된 뉴스가 없습니다. 키워드나 필터링 조건을 다시 확인해주세요."
    except HTTPException as e:
        error_message = f"뉴스 검색 중 오류 발생: {e.detail}"
        msg = f"오류 발생: {e.detail}"
    except Exception as e:
        error_message = f"예상치 못한 오류 발생: {e}"
        msg = f"오류 발생: {e}"

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
            'error_message': error_message
        }
    )

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: list = Form(...),
    final_results_json: str = Form(...),
    keyword_input: str = Form(''),
    checked_two_keywords: str = Form(""),
    search_mode: str = Form("major"),
    video_only: str = Form("")
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
                    item['pubdate'] = None
            else:
                item['pubdate'] = None
        final_results = parsed_json_results
    except json.JSONDecodeError as e:
        error_message = f"검색 결과 JSON 파싱 오류: {e}"
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
                shorten_fail_list.append(f"유효하지 않은 뉴스 선택 (인덱스: {idx_str})")
        except ValueError:
            shorten_fail_list.append(f"선택된 뉴스 인덱스 형식이 잘못됨 (값: {idx_str})")
        except Exception as e:
            shorten_fail_list.append(f"URL 선택 처리 중 오류: {e}")

    if not tasks and not shorten_fail_list:
        error_message = "단축할 뉴스를 선택해주세요."

    if tasks:
        shorten_results = await asyncio.gather(*tasks)
        for i, (short_url, fail_reason) in enumerate(shorten_results):
            art = selected_articles_info[i]
            if fail_reason:
                shorten_fail_list.append(f"'{art['title']}': {fail_reason}")
            else:
                line = f"■ {art['title']} ({art['press']})\n{short_url}"
                shortened_list.append(line)

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
