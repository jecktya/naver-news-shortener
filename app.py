import os
import urllib.parse
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from bs4 import BeautifulSoup
import httpx
import asyncio

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 주요 언론사 리스트 (도메인 또는 이름)
major_press_names = ["조선일보", "연합뉴스", "한겨레", "중앙일보", "MBN", "KBS", "SBS", "YTN", "동아일보", "세계일보", "문화일보", "뉴시스", "JTBC", "국민일보", "이데일리", "뉴스1"]

# 기본 키워드
DEFAULT_KEYWORDS = ["육군", "국방", "외교", "안보", "북한", "신병", "교육대", "훈련", "간부", "장교", "부사관", "병사", "용사", "군무원"]

def get_press_name_from_html(html):
    # 뉴스 기사 html에서 언론사명 추출
    soup = BeautifulSoup(html, "html.parser")
    press_tag = soup.select_one(".press_area .press_logo img[alt]")
    if press_tag and press_tag.get("alt"):
        return press_tag["alt"].strip()
    # 기타 패턴 추가
    return "기타"

async def fetch_news(query):
    """네이버 모바일 뉴스 크롤링"""
    url = f"https://m.search.naver.com/search.naver?ssc=tab.m_news.all&where=m_news&sm=mtb_jum&query={urllib.parse.quote(query)}"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, headers={"User-Agent":"Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for card in soup.select("div.news_wrap"):
            title_tag = card.select_one(".news_tit")
            press_tag = card.select_one(".info_group .press")
            link = title_tag['href'] if title_tag else None
            title = title_tag['title'] if title_tag else None
            press = press_tag.text.strip() if press_tag else "기타"
            if link and title:
                items.append({
                    "title": title,
                    "press": press,
                    "url": link,
                })
        return items

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "keywords": ", ".join(DEFAULT_KEYWORDS),
        "checked_two_keywords": False,
        "search_mode": "major",
        "final_results": [],
        "copy_area": "",
        "failures": []
    })

@app.post("/", response_class=HTMLResponse)
async def post_main(
    request: Request,
    keywords: str = Form(""),
    search_mode: str = Form("major"),
    checked_two_keywords: str = Form(None),
    selected_urls: list[str] = Form([]),
):
    # 1. 키워드 준비
    kwlist = [k.strip() for k in keywords.split(",") if k.strip()]
    query = " | ".join(kwlist)
    # 2. 뉴스 크롤링
    news_items = await fetch_news(query)
    # 3. 키워드 포함 수 집계
    results = []
    for n in news_items:
        kw_cnt = sum(1 for kw in kwlist if kw in n['title'])
        n['kw_count'] = kw_cnt
        n['matched_keywords'] = [kw for kw in kwlist if kw in n['title']]
    # 4. 주요언론사 필터
    if search_mode == "major":
        news_items = [n for n in news_items if n["press"] in major_press_names]
    # 5. 2개 이상 키워드 포함만
    if checked_two_keywords:
        news_items = [n for n in news_items if n['kw_count'] >= 2]
    # 6. 키워드수 내림차순 정렬
    news_items = sorted(news_items, key=lambda n: (-n['kw_count'], n['title']))
    # 7. copy_area 내용
    copy_area = "\n\n".join(
        f"[{n['press']}] {n['title']}\n{n['url']}"
        for n in news_items
    )
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "keywords": keywords,
        "checked_two_keywords": checked_two_keywords,
        "search_mode": search_mode,
        "final_results": news_items,
        "copy_area": copy_area,
        "failures": []
    })

# ---- 주소 단축용 (Playwright 연동 부분은 별도 route에 두는게 안전합니다) ----
@app.post("/shorten", response_class=HTMLResponse)
async def shorten(request: Request, selected_urls: list[str] = Form(...)):
    # 실제로는 선택된 뉴스 url만 변환
    # ... Playwright 코드 생략 ...
    # 실패한 것들은 failures 리스트로
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        # 나머지 context를 복원...
    })

