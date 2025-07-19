# app.py
# -*- coding: utf-8 -*-
import os
import re
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime # email.utils.parsedate_to_datetime 임포트 추가

from fastapi import FastAPI, Request, Form, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx

# --- 로깅 설정 ---
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
    return re.sub(r'<[^>]+>', '', text or "")

async def search_news_naver(keyword, display=30, max_retries=3):
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
                logger.info(f"[API 호출] 시도 {attempt + 1}/{max_retries} | 쿼리: '{keyword}'")
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
            "video_only": False,
            "now": now.strftime('%Y-%m-%d %H:%M:%S'),
            "msg": None
        }
    )

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(""),
    search_mode: str = Form("전체"),
    video_only: str = Form(""),
):
    now = datetime.now(timezone(timedelta(hours=9)))
    # 키워드 전처리
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keyword_list:
        keyword_list = DEFAULT_KEYWORDS

    logger.info(f"[검색] POST | 키워드={keywords} | 검색모드={search_mode} | 동영상만={video_only}")

    url_map = dict()
    try:
        # 네이버 API에 키워드별로 각각 요청
        # display 값을 줄여서 API 호출 부하를 줄이는 것을 고려해볼 수 있습니다.
        # 예: tasks = [search_news_naver(kw, display=10) for kw in keyword_list]
        tasks = [search_news_naver(kw) for kw in keyword_list]
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
                        "pubdate": pub,
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
            # 2개 이상 키워드 포함 필터
            if len(v["matched"]) < 2:
                continue
            # 주요언론사, 동영상 필터
            if search_mode == "주요언론사만" and v["press"] not in PRESS_MAJOR:
                continue
            if search_mode == "동영상만":
                video_keys = ["영상", "동영상", "영상보기", "보러가기", "뉴스영상", "영상뉴스", "클릭하세요", "바로보기"]
                # 언론사도 주요만, 영상 키워드 포함만
                if v["press"] not in PRESS_MAJOR:
                    continue
                if not (any(k in v["desc"] for k in video_keys) or any(k in v["title"] for k in video_keys)):
                    continue
            articles.append(v)
        # 정렬: 시간순
        sorted_articles = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
        msg = f"검색 결과: {len(sorted_articles)}건 (4시간 이내, 2개 이상 키워드 포함)"
        logger.info(f"[검색] 최종 기사수: {len(sorted_articles)}")
        # 날짜 표시용 추가
        for art in sorted_articles:
            art["pubdate_str"] = art["pubdate"].strftime('%Y-%m-%d %H:%M') if art["pubdate"] else ""
            art["matched_list"] = sorted(list(art["matched"]), key=lambda x: x)
            art["matched_count"] = len(art["matched"])
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "keyword_input": ', '.join(keyword_list),
                "final_articles": sorted_articles,
                "search_mode": search_mode,
                "video_only": video_only == "on",
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
                "video_only": video_only == "on",
                "now": now.strftime('%Y-%m-%d %H:%M:%S'),
                "msg": f"오류: {e}"
            }
        )
