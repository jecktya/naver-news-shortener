# app.py
# -*- coding: utf-8 -*-

import os
import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict
from fastapi import FastAPI, HTTPException, Query
import uvicorn

# 기본 키워드와 주요 언론사 목록
DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한',
    '신병', '교육대', '훈련', '간부',
    '장교', '부사관', '병사', '용사', '군무원'
]
PRESS_MAJOR = {
    '연합뉴스', '조선일보', '한겨레', '중앙일보',
    'MBN', 'KBS', 'SBS', 'YTN',
    '동아일보', '세계일보', '문화일보', '뉴시스',
    '국민일보', '국방일보', '이데일리',
    '뉴스1', 'JTBC'
}

def parse_time(timestr: str) -> datetime:
    now = datetime.now()
    if '분 전' in timestr:
        try:
            m = int(timestr.split('분')[0])
            return now - timedelta(minutes=m)
        except:
            return None
    if '시간 전' in timestr:
        try:
            h = int(timestr.split('시간')[0])
            return now - timedelta(hours=h)
        except:
            return None
    m = re.match(r'(\d{4})\.(\d{2})\.(\d{2})\.', timestr)
    if m:
        y, mm, d = map(int, m.groups())
        return datetime(y, mm, d)
    return None

def parse_newslist(
    html: str,
    keywords: List[str],
    search_mode: str,
    video_only: bool
) -> List[Dict]:
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('ul.list_news > li')
    now = datetime.now()
    results: List[Dict] = []

    for li in items:
        a = li.select_one('a.news_tit')
        if not a:
            continue
        title = a.get('title', '').strip()
        url   = a.get('href', '').strip()

        press_elem = li.select_one('a.info.press')
        press = press_elem.get_text(strip=True).replace('언론사 선정','') if press_elem else ''

        date_elem = li.select_one('span.info.date')
        pubstr = date_elem.get_text(strip=True) if date_elem else ''
        pubtime = parse_time(pubstr)
        if not pubtime or (now - pubtime) > timedelta(hours=4):
            continue

        if search_mode == 'major' and press and press not in PRESS_MAJOR:
            continue

        if video_only:
            if not li.select_one("a.news_tit[href*='tv.naver.com'], span.video"):
                continue

        desc_elem = li.select_one('div.news_dsc, div.api_txt_lines.dsc')
        desc = desc_elem.get_text(' ', strip=True) if desc_elem else ''

        hay = (title + ' ' + desc).lower()
        kw_source = keywords if keywords is not None else DEFAULT_KEYWORDS
        kwcnt = {kw: hay.count(kw.lower()) for kw in kw_source if hay.count(kw.lower())}
        if not kwcnt:
            continue

        results.append({
            'title':    title,
            'url':      url,
            'press':    press,
            'pubdate':  pubtime.strftime('%Y-%m-%d %H:%M'),
            'keywords': sorted(kwcnt.items(), key=lambda x: (-x[1], x[0])),
            'kw_count': sum(kwcnt.values())
        })

    results.sort(key=lambda x: (-x['kw_count'], x['pubdate']), reverse=False)
    return results

def fetch_html(url: str) -> str:
    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.text

app = FastAPI(title="Naver Mobile News Analyzer")

# 헬스체크
@app.get("/", include_in_schema=False)
async def health_check():
    return {"status": "ok"}

# 분석 엔드포인트
@app.get("/analyze")
async def analyze(
    url: str = Query(..., description="모바일 뉴스 검색 URL"),
    mode: str = Query("all", regex="^(all|major)$", description="all 또는 major"),
    video: bool = Query(False, description="동영상 뉴스만 필터링"),
    kws: str = Query("", description="콤마로 구분된 키워드(strings)")
):
    try:
        html = fetch_html(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"URL 요청 실패: {e}")

    user_keywords = [k.strip() for k in kws.split(',') if k.strip()]
    keywords = user_keywords if user_keywords else None

    articles = parse_newslist(
        html=html,
        keywords=keywords,
        search_mode=mode,
        video_only=video
    )

    return {
        "query_url":    url,
        "mode":         mode,
        "video_only":   video,
        "keyword_list": keywords or DEFAULT_KEYWORDS,
        "count":        len(articles),
        "articles":     articles
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
