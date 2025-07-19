# app.py
# -*- coding: utf-8 -*-
import os
import re
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html # html 모듈 임포트 추가

from fastapi import FastAPI, Request, Form, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx

# --- 로깅 설정 ---
# 기본 로깅 레벨을 INFO로 설정하여 DEBUG 메시지는 출력되지 않도록 합니다.
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__) # 특정 로거 사용

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 주요 언론사 매핑
PRESS_MAJOR = {
    "조선일보", "연합뉴스", "한겨레", "중앙일보", "MBN", "KBS", "SBS", "YTN", "동아일보",
    "세계일보", "문화일보", "뉴시스", "네이버", "다음", "국민일보", "국방일보", "이데일리",
    "뉴스1", "JTBC"
}

DEFAULT_KEYWORDS = [
    "육군", "국방", "외교", "안보", "북한", "신병", "교육대", "훈련", "간부",
    "장교", "부사관", "병사", "용사", "군무원"
]

def extract_press(item):
    # 네이버 뉴스 API는 publisher 필드에 언론사명이 들어있음
    return item.get("publisher") or ""

def parse_pubdate(pubdate_str):
    # 예: "Wed, 09 Jul 2025 12:55:29 +0900"
    try:
        dt = parsedate_to_datetime(pubdate_str)
        if dt.tzinfo is None:
            # 타임존 정보가 없으면 KST (한국 표준시)로 가정
            dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))
        return dt
    except Exception as e:
        logger.warning(f"pubDate '{pubdate_str}' 파싱 실패: {e}")
        return None

def clean_html_tags(text):
    # HTML 태그를 제거하고, 그 후 HTML 엔티티를 디코딩합니다.
    cleaned_text = re.sub(r'<[^>]+>', '', text or "")
    unescaped_text = html.unescape(cleaned_text) # HTML 엔티티 디코딩
    return unescaped_text

async def search_news_naver(keyword, display=10, max_retries=3): # display 기본값 10으로 유지
    """
    네이버 뉴스 API를 호출하여 뉴스 아이템을 가져옵니다.
    429 Too Many Requests 에러 발생 시 재시도 로직을 포함합니다.
    """
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": keyword,
        "display": display,
        "sort": "date"
    }

    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # 이 로그 메시지를 INFO에서 DEBUG로 변경하여 기본적으로 출력되지 않도록 합니다.
                logger.debug(f"[API 호출] 시도 {attempt + 1}/{max_retries} | 쿼리: '{keyword}'")
                res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
                res.raise_for_status() # 200 OK가 아니면 예외 발생 (429 포함)
                return res.json().get("items", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                # 429 에러 발생 시 경고 로깅 및 지수 백오프 대기
                logger.warning(f"[API 오류] 429 Too Many Requests. 재시도 중... (남은 시도: {max_retries - 1 - attempt})")
                await asyncio.sleep(2 ** attempt) # 1, 2, 4초 대기
            else:
                # 다른 HTTP 오류는 즉시 예외 발생
                logger.error(f"[API 오류] HTTP Status Error: {e.response.status_code} - {e.response.text}", exc_info=True)
                raise # 다른 HTTP 오류는 즉시 발생
        except httpx.RequestError as e:
            # 네트워크 요청 오류 (DNS 문제, 연결 끊김 등)
            logger.error(f"[API 오류] Request Error: {e}", exc_info=True)
            raise # 요청 오류는 즉시 발생
        except Exception as e:
            # 그 외 예상치 못한 오류
            logger.error(f"[API 오류] 예상치 못한 오류: {e}", exc_info=True)
            raise # 다른 예외는 즉시 발생
    
    # 모든 재시도 실패 시
    logger.error(f"[API 오류] '{keyword}' 검색, 최대 재시도 횟수 ({max_retries}) 초과. 429 에러 지속.")
    return [] # 모든 재시도 실패 시 빈 리스트 반환

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    now = datetime.now(timezone(timedelta(hours=9)))
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "keyword_input": ', '.join(DEFAULT_KEYWORDS),
            "final_articles": [],
            "search_mode": "전체",
            "now": now.strftime('%Y-%m-%d %H:%M:%S'),
            "msg": None
        }
    )

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(""),
    search_mode: str = Form("전체"),
):
    now = datetime.now(timezone(timedelta(hours=9)))
    # 키워드 전처리
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keyword_list:
        keyword_list = DEFAULT_KEYWORDS

    logger.info(f"[검색] POST | 키워드={keywords} | 검색모드={search_mode}")

    url_map = dict()
    try:
        # --- API 호출 동시성 제어 (Semaphore 사용) ---
        # 한 번에 5개까지만 동시 요청을 보내도록 제한합니다.
        semaphore = asyncio.Semaphore(5) 

        async def limited_search(kw):
            async with semaphore:
                # 각 키워드당 가져오는 기사 수를 10으로 설정합니다.
                return await search_news_naver(kw, display=10) 

        tasks = [limited_search(kw) for kw in keyword_list]
        result_lists = await asyncio.gather(*tasks)

        # 기사 합치기 & 중복 제거 & 키워드 매칭
        for idx, items in enumerate(result_lists):
            kw = keyword_list[idx]
            for a in items:
                title = clean_html_tags(a.get("title", ""))
                desc = clean_html_tags(a.get("description", ""))
                url = a.get("link", "")
                press = extract_press(a)
                pub = parse_pubdate(a.get("pubDate", ""))
                if not url: continue
                if url not in url_map:
                    url_map[url] = {
                        "title": title,
                        "desc": desc,
                        "url": url,
                        "press": press,
                        "pubdate": pub, # datetime 객체 유지
                        "matched": set(),
                    }
                # 제목/내용에 키워드가 포함되어 있으면 추가
                haystack = f"{title} {desc}"
                if kw in haystack:
                    url_map[url]["matched"].add(kw)
        articles = []
        for v in url_map.values():
            # 시간 필터: 4시간 이내만
            if not v["pubdate"] or (now - v["pubdate"] > timedelta(hours=4)):
                continue
            # --- 키워드 필터링 로직 수정: 1개 이상 키워드 포함 ---
            # 변경: if not v["matched"]: continue (최소 1개 키워드 포함)
            if not v["matched"]: # 매칭된 키워드가 없으면 건너뜀 (즉, 1개 이상 매칭 시 통과)
                continue
            # 주요언론사 필터
            if search_mode == "주요언론사만" and v["press"] not in PRESS_MAJOR:
                continue
            
            articles.append(v)

        # 정렬: 시간순 (datetime 객체로 정렬)
        sorted_articles = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
        
        # 템플릿에 전달하기 위한 최종 기사 목록 (pubdate를 문자열로, matched를 리스트로 변환)
        final_articles_for_template = []
        for art in sorted_articles:
            art_copy = art.copy()
            art_copy["pubdate"] = art_copy["pubdate"].strftime('%Y-%m-%d %H:%M') if art_copy["pubdate"] else ""
            art_copy["matched"] = sorted(list(art_copy["matched"]), key=lambda x: x) # set을 list로 변환
            art_copy["matched_list"] = art_copy["matched"] # Jinja2에서 사용하기 위해 추가
            art_copy["matched_count"] = len(art_copy["matched"]) # Jinja2에서 사용하기 위해 추가
            final_articles_for_template.append(art_copy)


        msg = f"검색 결과: {len(final_articles_for_template)}건 (4시간 이내, 1개 이상 키워드 포함)" # 메시지 업데이트
        logger.info(f"[검색] 최종 기사수: {len(final_articles_for_template)}")
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": ', '.join(keyword_list),
                "final_articles": final_articles_for_template, # 변환된 리스트 전달
                "search_mode": search_mode,
                "now": now.strftime('%Y-%m-%d %H:%M:%S'),
                "msg": msg
            }
        )
    except Exception as e:
        logger.error(f"[검색] 오류: {e}", exc_info=True)
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": ', '.join(keyword_list),
                "final_articles": [],
                "search_mode": search_mode,
                "now": now.strftime('%Y-%m-%d %H:%M:%S'),
                "msg": f"오류: {e}"
            }
        )

# --- 네이버미 변환 (실제 Playwright 등 구현 필요, 현재는 더미) ---
@app.post("/naverme", response_class=HTMLResponse) # 경로를 /naverme로 변경
async def post_naverme(request: Request, selected_urls: str = Form(...)):
    # selected_urls는 JSON 리스트(string)
    import json
    urls = json.loads(selected_urls)
    
    naverme_results = []
    for u in urls:
        # 실제 네이버미 변환 로직 (Playwright 등)이 여기에 들어갑니다.
        # 현재는 더미 데이터로 응답합니다.
        # 클라우드 환경에서 Playwright는 리소스 소모 및 봇 감지로 인해 불안정할 수 있습니다.
        logger.info(f"URL 단축 요청: {u}")
        naverme_results.append({"original_url": u, "shortened_url": f"https://naver.me/dummy_{hash(u) % 10000}"})
    
    # HTML의 JavaScript가 JSON 응답을 기대하므로 JSONResponse를 반환합니다.
    # HTML에서 alert() 대신 더 나은 UI (예: 모달, 토스트 메시지)를 사용하는 것을 권장합니다.
    return HTMLResponse(content=json.dumps({"results": naverme_results}), media_type="application/json")


# 애플리케이션 실행 (직접 실행 시 uvicorn 서버 시작)
if __name__ == "__main__":
    # 환경 변수에서 PORT를 가져오거나 기본값 8000 사용
    port = int(os.environ.get("PORT", 8000))
    # app:app은 'app.py' 파일 내의 'app' 객체를 의미합니다.
    # --reload 옵션은 코드 변경 시 자동으로 서버를 재시작합니다.
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
