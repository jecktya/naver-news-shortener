# app.py
# -*- coding: utf-8 -*-

import os
import re
import httpx # requests 대신 httpx 임포트
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from fastapi import FastAPI, HTTPException, Query, status
import uvicorn
import logging

# 로거 설정
# INFO 레벨로 설정하여 중요한 정보만 로깅합니다. 필요시 DEBUG로 변경하여 상세 로그 확인 가능.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 기본 키워드 목록
DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한',
    '신병', '교육대', '훈련', '간부',
    '장교', '부사관', '병사', '용사', '군무원'
]

# 주요 언론사 목록 (대소문자 구분 없이 비교하기 위해 set 사용)
PRESS_MAJOR = {
    '연합뉴스', '조선일보', '한겨레', '중앙일보',
    'MBN', 'KBS', 'SBS', 'YTN',
    '동아일보', '세계일보', '문화일보', '뉴시스',
    '국민일보', '국방일보', '이데일리',
    '뉴스1', 'JTBC'
}

def parse_time(timestr: str) -> Optional[datetime]:
    """
    주어진 시간 문자열을 datetime 객체로 파싱합니다.
    '분 전', '시간 전', 'YYYY.MM.DD.' 형식을 지원합니다.
    """
    if not timestr:
        logger.debug("시간 문자열이 비어 있습니다.")
        return None

    now = datetime.now()

    # 'X분 전' 형식 파싱
    if '분 전' in timestr:
        try:
            minutes_ago = int(timestr.split('분')[0].strip())
            return now - timedelta(minutes=minutes_ago)
        except ValueError:
            logger.warning(f"시간 문자열 '{timestr}'에서 '분 전' 파싱 실패.")
            return None
    # 'X시간 전' 형식 파싱
    if '시간 전' in timestr:
        try:
            hours_ago = int(timestr.split('시간')[0].strip())
            return now - timedelta(hours=hours_ago)
        except ValueError:
            logger.warning(f"시간 문자열 '{timestr}'에서 '시간 전' 파싱 실패.")
            return None
    
    # 'YYYY.MM.DD.' 형식 파싱
    match = re.match(r'(\d{4})\.(\d{2})\.(\d{2})\.', timestr)
    if match:
        try:
            year, month, day = map(int, match.groups())
            return datetime(year, month, day)
        except ValueError:
            logger.warning(f"시간 문자열 '{timestr}'에서 'YYYY.MM.DD.' 파싱 실패.")
            return None
            
    logger.debug(f"알 수 없는 시간 형식: '{timestr}'")
    return None # 어떤 형식도 매칭되지 않거나 파싱 오류 발생 시 None 반환

def parse_newslist(
    html: str,
    keywords: Optional[List[str]], # 키워드가 없을 수 있으므로 Optional
    search_mode: str,
    video_only: bool
) -> List[Dict]:
    """
    네이버 뉴스 검색 결과 HTML을 파싱하여 뉴스 기사 목록을 반환합니다.
    필터링 조건(키워드, 언론사, 동영상 여부)을 적용합니다.
    """
    logger.info("뉴스 HTML 파싱 시작.")
    soup = BeautifulSoup(html, 'html.parser')
    
    # 네이버 모바일 뉴스 검색 결과의 각 기사 항목을 선택
    # .news_area, .bx는 이전 버전에서 사용된 선택자일 수 있으며,
    # 현재 네이버 모바일 뉴스는 'ul.list_news > li' 구조를 주로 사용합니다.
    # 안전을 위해 여러 선택자를 시도합니다.
    news_items = soup.select('ul.list_news > li, .news_area, .bx') 
    now = datetime.now()
    results: List[Dict] = []

    if not news_items:
        logger.warning("뉴스 기사 요소를 찾을 수 없습니다. HTML 구조 변경 또는 검색 결과 없음.")
        logger.debug(f"받은 HTML 미리보기: {html[:1000]}...")
        return []

    for li in news_items:
        # 뉴스 제목과 URL 추출
        a_tag = li.select_one('a.news_tit, a.tit, a[role="text"]') # 다양한 제목 링크 선택자 시도
        if not a_tag:
            logger.debug(f"뉴스 제목/링크 요소를 찾을 수 없습니다. 항목 스킵: {li.prettify()[:200]}...")
            continue
        title = a_tag.get('title', '').strip() or a_tag.get_text(strip=True)
        url = a_tag.get('href', '').strip()

        # 언론사 이름 추출
        press_elem = li.select_one('a.info.press, .press, ._sp_each_info')
        press = press_elem.get_text(strip=True).replace('언론사 선정', '').replace('언론사', '').strip() if press_elem else ''

        # 발행일 추출 및 시간 필터링 (최근 4시간 이내)
        date_elem = li.select_one('span.info.date, .info .date, ._sp_each_date')
        pub_str = date_elem.get_text(strip=True) if date_elem else ''
        pubtime = parse_time(pub_str)
        if not pubtime or (now - pubtime) > timedelta(hours=4):
            logger.debug(f"시간 필터링: '{title}' - {pub_str} ({pubtime}). 4시간 초과 또는 파싱 실패. 제외됨.")
            continue

        # 주요 언론사 필터링
        if search_mode == 'major' and press and press not in PRESS_MAJOR:
            logger.debug(f"주요 언론사 필터링: '{title}' - {press}. 제외됨.")
            continue

        # 동영상 뉴스만 필터링
        if video_only:
            # 동영상 뉴스를 나타내는 특정 요소나 URL 패턴 확인
            if not li.select_one("a.news_tit[href*='tv.naver.com'], span.video, ._playing_area, .sp_thmb_video"):
                logger.debug(f"동영상 필터링: '{title}'. 동영상 아님. 제외됨.")
                continue

        # 뉴스 본문 요약 추출
        desc_elem = li.select_one('div.news_dsc, div.api_txt_lines.dsc, .dsc_wrap, .desc')
        desc = desc_elem.get_text(' ', strip=True) if desc_elem else ''

        # 제목과 요약에서 키워드 카운트
        # 사용자가 키워드를 지정하지 않았다면 기본 키워드 사용
        current_keywords = keywords if keywords else DEFAULT_KEYWORDS
        
        haystack = (title + ' ' + desc).lower() # 검색 대상 텍스트
        kw_counts = {}
        for kw in current_keywords:
            count = haystack.count(kw.lower())
            if count > 0:
                kw_counts[kw] = count
        
        # 키워드 매칭이 없으면 제외
        if not kw_counts:
            logger.debug(f"키워드 매칭 없음: '{title}'. 제외됨.")
            continue

        results.append({
            'title':    title,
            'url':      url,
            'press':    press,
            'pubdate':  pubtime.strftime('%Y-%m-%d %H:%M') if pubtime else None,
            'keywords': sorted(kw_counts.items(), key=lambda x: (-x[1], x[0])), # 키워드 빈도수 내림차순, 키워드명 오름차순 정렬
            'kw_count': sum(kw_counts.values()) # 총 키워드 출현 횟수
        })

    logger.info(f"뉴스 파싱 완료. 총 {len(results)}건의 뉴스 기사 추출.")
    # 총 키워드 출현 횟수 내림차순, 발행일 오름차순으로 최종 정렬
    results.sort(key=lambda x: (-x['kw_count'], x['pubdate'] if x['pubdate'] else ''), reverse=False)
    return results

async def fetch_html(url: str) -> str: # async 키워드 추가
    """
    주어진 URL에서 HTML 내용을 비동기적으로 가져옵니다.
    """
    logger.info(f"HTML 요청 시작: {url}")
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client: # httpx.AsyncClient 사용
            resp = await client.get(url, headers=headers) # await 키워드 추가
            resp.raise_for_status() # HTTP 오류 발생 시 예외 발생
            logger.info(f"HTML 요청 성공. 상태 코드: {resp.status_code}")
            logger.debug(f"응답 HTML 미리보기: {resp.text[:1000]}...")
            return resp.text
    except httpx.RequestError as e: # httpx.RequestError로 변경
        logger.error(f"URL '{url}' 요청 실패: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"URL 요청 실패: {e}")
    except httpx.HTTPStatusError as e: # httpx.HTTPStatusError 추가
        logger.error(f"URL '{url}' HTTP 상태 오류: {e.response.status_code} - {e.response.text[:500]}", exc_info=True)
        raise HTTPException(status_code=e.response.status_code, detail=f"HTTP 상태 오류: {e.response.status_code}")
    except Exception as e:
        logger.error(f"예상치 못한 오류 발생: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"서버 내부 오류: {e}")

# FastAPI 애플리케이션 인스턴스 생성
app = FastAPI(
    title="Naver Mobile News Analyzer API",
    description="네이버 모바일 뉴스 검색 결과를 파싱하고 분석하는 API입니다.",
    version="1.0.0"
)

# 헬스체크 엔드포인트
@app.get("/", include_in_schema=False, summary="API 헬스 체크")
async def health_check():
    """API의 작동 상태를 확인합니다."""
    return {"status": "ok", "message": "Naver Mobile News Analyzer API is running!"}

# 뉴스 분석 엔드포인트
@app.get("/analyze", summary="네이버 모바일 뉴스 검색 결과 분석")
async def analyze_news(
    url: str = Query(
        ...,
        description="분석할 네이버 모바일 뉴스 검색 결과 URL. 예: `https://m.search.naver.com/search.naver?query=육군&sm=mtb_opt&sort=1&photo=0&field=0&pd=0&ds=2024.07.04&de=2024.07.04`"
    ),
    mode: str = Query(
        "all",
        regex="^(all|major)$",
        description="검색 모드: 'all' (모든 언론사) 또는 'major' (주요 언론사만)"
    ),
    video: bool = Query(
        False,
        description="동영상 뉴스만 필터링할지 여부 (True/False)"
    ),
    kws: str = Query(
        "",
        description="콤마(,) 또는 파이프(|)로 구분된 추가 키워드. 비워두면 기본 키워드가 사용됩니다."
    )
):
    """
    제공된 네이버 모바일 뉴스 검색 결과 URL에서 뉴스를 분석하고 필터링합니다.
    """
    logger.info(f"'/analyze' 엔드포인트 호출됨. URL: {url}, 모드: {mode}, 비디오: {video}, 키워드: '{kws}'")
    
    try:
        html_content = await fetch_html(url) # await 키워드 추가
    except HTTPException as e:
        logger.error(f"HTML fetch_html 실패: {e.detail}")
        raise # fetch_html에서 발생한 HTTPException을 그대로 다시 발생시킴

    user_keywords = [k.strip() for k in re.split(r'[,|]', kws) if k.strip()]
    
    # 사용자가 키워드를 제공하지 않으면 None을 전달하여 parse_newslist 내부에서 DEFAULT_KEYWORDS 사용
    keywords_to_use = user_keywords if user_keywords else None 

    articles = parse_newslist(
        html=html_content,
        keywords=keywords_to_use,
        search_mode=mode,
        video_only=video
    )

    logger.info(f"분석 완료. 총 {len(articles)}건의 기사 반환.")
    return {
        "query_url":    url,
        "mode":         mode,
        "video_only":   video,
        "keyword_list": keywords_to_use or DEFAULT_KEYWORDS, # 실제 사용된 키워드 목록 반환
        "count":        len(articles),
        "articles":     articles
    }

# 애플리케이션 실행 (직접 실행 시 uvicorn 서버 시작)
if __name__ == "__main__":
    # 환경 변수에서 PORT를 가져오거나 기본값 8000 사용
    port = int(os.environ.get("PORT", 8000))
    # app:app은 'app.py' 파일 내의 'app' 객체를 의미합니다.
    # --reload 옵션은 코드 변경 시 자동으로 서버를 재시작합니다.
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
