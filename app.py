# news_analyzer.py
# -*- coding: utf-8 -*-

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict

# —————————————————————————————————————————————————————————————————————————————
# 설정: 기본 키워드와 주요 언론사 목록
# —————————————————————————————————————————————————————————————————————————————
DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]

PRESS_MAJOR = {
    '연합뉴스', '조선일보', '한겨레', '중앙일보', 'MBN', 'KBS', 'SBS', 'YTN',
    '동아일보', '세계일보', '문화일보', '뉴시스', '국민일보', '국방일보',
    '이데일리', '뉴스1', 'JTBC'
}

# —————————————————————————————————————————————————————————————————————————————
# 시간 문자열을 datetime으로 변환 (예: "5분 전", "2시간 전", "2025.06.29.")
# —————————————————————————————————————————————————————————————————————————————
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
    # 날짜 형식 YYYY.MM.DD.
    m = re.match(r'(\d{4})\.(\d{2})\.(\d{2})\.', timestr)
    if m:
        y, mm, d = map(int, m.groups())
        return datetime(y, mm, d)
    return None

# —————————————————————————————————————————————————————————————————————————————
# HTML 파싱: 모바일 뉴스 리스트에서 기사 정보 추출
# —————————————————————————————————————————————————————————————————————————————
def parse_newslist(
    html: str,
    keywords: List[str] = DEFAULT_KEYWORDS,
    search_mode: str = 'all',   # 'all' 또는 'major'
    video_only: bool = False
) -> List[Dict]:
    soup = BeautifulSoup(html, 'html.parser')
    items = soup.select('ul.list_news > li')
    now = datetime.now()
    results = []

    for li in items:
        a = li.select_one('a.news_tit')
        if not a:
            continue
        title = a['title'].strip()
        url   = a['href'].strip()

        press_elem = li.select_one('a.info.press')
        press = press_elem.get_text(strip=True).replace('언론사 선정', '') if press_elem else ''

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
        kwcnt = {kw: hay.count(kw.lower()) for kw in keywords if hay.count(kw.lower())}
        if not kwcnt:
            continue

        results.append({
            'title': title,
            'url': url,
            'press': press,
            'pubdate': pubtime.strftime('%Y-%m-%d %H:%M'),
            'keywords': sorted(kwcnt.items(), key=lambda x: (-x[1], x[0])),
            'kw_count': sum(kwcnt.values()),
        })

    # 키워드 출현 수, 최신순 정렬
    results.sort(key=lambda x: (-x['kw_count'], x['pubdate']), reverse=False)
    return results

# —————————————————————————————————————————————————————————————————————————————
# HTML 가져오기 (requests 사용)
# —————————————————————————————————————————————————————————————————————————————
def fetch_html(url: str) -> str:
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/126.0.0.0 Safari/537.36'
        )
    }
    resp = requests.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return resp.text

# —————————————————————————————————————————————————————————————————————————————
# 메인 실행부
# —————————————————————————————————————————————————————————————————————————————
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print('Usage: python news_analyzer.py <네이버 모바일 뉴스 URL>')
        sys.exit(1)

    url = sys.argv[1]
    print(f'Fetching: {url}\n')
    html = fetch_html(url)

    articles = parse_newslist(html, DEFAULT_KEYWORDS, search_mode='all', video_only=False)
    if not articles:
        print('>> 최근 4시간 이내 키워드 매칭 뉴스가 없습니다.')
    else:
        for i, art in enumerate(articles, 1):
            print(f"{i}. [{art['pubdate']}] {art['press']} - {art['title']}")
            print(f"   키워드출현: {art['keywords']}  링크: {art['url']}\n")
