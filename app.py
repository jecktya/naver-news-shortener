# app.py
# -*- coding: utf-8 -*-

import os
import json
import random
import string
import logging
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx

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

app = FastAPI(title="뉴스검색기 (FastAPI+NaverAPI)")
templates = Jinja2Templates(directory="templates")

DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]

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

async def naver_me_shorten(orig_url: str) -> str:
    """
    (더미 함수) 실제 naver.me 단축 URL을 생성하지 않고 임의의 URL을 반환합니다.
    실제 단축 기능을 구현하려면 별도의 API 연동 또는 웹 자동화가 필요합니다.
    """
    short_code = ''.join(random.choices(string.ascii_letters + string.digits, k=7))
    short_url = f"https://naver.me/{short_code}"
    logger.info(f"더미 naver.me 단축 URL 생성: {orig_url} -> {short_url}")
    return short_url

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    """
    초기 검색 페이지를 렌더링합니다.
    """
    logger.info("GET / 요청 수신. 초기 index.html 렌더링.")
    return templates.TemplateResponse(
        "index.html",
        {
            'request': request,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'keyword_input': '',
            'final_results': [], # 초기에는 빈 리스트
            'shortened': None,
            'error_message': None
        }
    )

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(...),
):
    """
    키워드를 받아 네이버 뉴스 API를 검색하고 결과를 표시합니다.
    """
    logger.info(f"POST / 요청 수신. 키워드: '{keywords}'")
    kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS
        logger.info("키워드가 없어 기본 키워드 사용.")
    
    # 네이버 API는 'OR' 연산자를 지원합니다.
    query = " OR ".join(kw_list) 
    logger.info(f"네이버 API 검색 쿼리: '{query}'")

    final_results = []
    error_message = None
    try:
        news_items = await search_naver_news(query)
        for item in news_items:
            # 네이버 API 응답 필드와 앱의 예상 필드 매핑
            final_results.append({
                "title": item.get("title", "").replace("<b>", "").replace("</b>", ""), # HTML 태그 제거
                "press": item.get("publisher", ""), # API는 'publisher' 필드 사용
                "pubdate": item.get("pubDate", ""), # API는 'pubDate' 필드 사용
                "url": item.get("link", ""),
                "desc": item.get("description", "").replace("<b>", "").replace("</b>", ""), # HTML 태그 제거
                # API 응답에는 키워드 카운트 정보가 없으므로, 필요시 직접 파싱 로직 추가 필요
                "keywords": [], 
                "kw_count": 0 
            })
        logger.info(f"네이버 뉴스 검색 결과: 총 {len(final_results)}건.")
    except HTTPException as e:
        error_message = f"뉴스 검색 중 오류 발생: {e.detail}"
        logger.error(error_message)
    except Exception as e:
        error_message = f"예상치 못한 오류 발생: {e}"
        logger.error(error_message, exc_info=True)

    return templates.TemplateResponse(
        "index.html",
        {
            'request': request,
            'final_results': final_results,
            'keyword_input': keywords,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'shortened': None,
            'error_message': error_message
        }
    )

@app.post("/shorten", response_class=HTMLResponse)
async def post_shorten(
    request: Request,
    selected_urls: list = Form(..., description="선택된 URL의 인덱스 목록"),
    final_results_json: str = Form(..., description="검색 결과 JSON 문자열"),
    keyword_input: str = Form('', description="이전 검색 키워드 입력")
):
    """
    선택된 뉴스 URL들을 더미 naver.me URL로 단축하여 표시합니다.
    """
    logger.info(f"POST /shorten 요청 수신. 선택된 URL 인덱스: {selected_urls}")
    final_results = []
    error_message = None
    try:
        final_results = json.loads(final_results_json)
        logger.info(f"JSON 로드 완료. 총 {len(final_results)}개 결과.")
    except json.JSONDecodeError as e:
        error_message = f"검색 결과 JSON 파싱 오류: {e}"
        logger.error(error_message, exc_info=True)
        # JSON 파싱 실패 시 빈 결과로 진행
        final_results = [] 

    shortened_list = []
    for idx_str in selected_urls:
        try:
            idx = int(idx_str)
            if 0 <= idx < len(final_results):
                orig_url = final_results[idx]['url']
                short_url = await naver_me_shorten(orig_url)
                shortened_list.append(f"■ {final_results[idx]['title']} ({final_results[idx]['press']})\n{short_url}")
            else:
                logger.warning(f"유효하지 않은 인덱스 선택됨: {idx_str}. 총 결과 수: {len(final_results)}")
                error_message = f"유효하지 않은 뉴스 선택이 있었습니다. 인덱스: {idx_str}"
        except ValueError:
            logger.error(f"선택된 URL 인덱스 파싱 오류: '{idx_str}'는 정수가 아닙니다.", exc_info=True)
            error_message = f"선택된 뉴스 인덱스 형식이 잘못되었습니다: {idx_str}"
        except Exception as e:
            logger.error(f"URL 단축 중 예상치 못한 오류 발생: {e}", exc_info=True)
            error_message = f"URL 단축 중 오류 발생: {e}"

    logger.info(f"URL 단축 처리 완료. 성공: {len(shortened_list)}건.")
    return templates.TemplateResponse(
        "index.html",
        {
            'request': request,
            'final_results': final_results,
            'shortened': '\n'.join(shortened_list),
            'keyword_input': keyword_input,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'error_message': error_message
        }
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
