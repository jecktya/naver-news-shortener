import os
import re
import asyncio
import urllib.parse
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright
from collections import Counter
from typing import List

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 기본 키워드
DEFAULT_KEYWORDS = ["육군", "국방", "외교", "안보", "북한", "신병", "교육대",
                    "훈련", "간부", "장교", "부사관", "병사", "용사", "군무원"]

# 주요언론사 도메인(예시)
MAJOR_PRESS = {
    "chosun.com", "yna.co.kr", "hani.co.kr", "joongang.co.kr", "mbn.co.kr",
    "kbs.co.kr", "sbs.co.kr", "ytn.co.kr", "donga.com", "segye.com",
    "munhwa.com", "newsis.com", "naver.com", "daum.net", "kukinews.com",
    "kookbang.dema.mil.kr", "edaily.co.kr", "news1.kr", "jtbc.co.kr"
}

def extract_domain(url):
    from urllib.parse import urlparse
    d = urlparse(url).netloc.replace("www.", "")
    for domain in MAJOR_PRESS:
        if d.endswith(domain):
            return domain
    return d

def count_keywords_in_text(text, keywords):
    counts = Counter()
    for k in keywords:
        cnt = text.count(k)
        if cnt > 0:
            counts[k] += cnt
    return counts

async def search_naver_news(query, limit=20):
    # 모바일 네이버 뉴스에서 검색결과 긁어오기 (간단 HTML 파싱)
    import httpx
    base = "https://m.search.naver.com/search.naver?ssc=tab.m_news.all&where=m_news&sm=mtb_jum&query="
    url = base + urllib.parse.quote(query)
    articles = []
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
        if resp.status_code == 200:
            html = resp.text
            # 네이버 모바일 뉴스 리스트 a태그 파싱
            for match in re.finditer(r'<a[^>]+href="(https://n\.news\.naver\.com/mnews/article/[^"]+)"[^>]*>(.*?)</a>', html):
                news_url = match.group(1)
                title = re.sub('<.*?>', '', match.group(2))
                articles.append({'url': news_url, 'title': title})
    return articles

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "results": [],
        "checked_two_keywords": False,
        "search_mode": "major",
        "msg": "",
        "copy_text": "",
        "failed": []
    })

@app.post("/", response_class=HTMLResponse)
async def search(request: Request, 
    keywords: str = Form(...),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    selected_urls: List[str] = Form(None)
):
    # 키워드 전처리
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    # 기본 다중 검색 - 각 키워드별 결과 모으기
    url_map = {}
    for kw in keyword_list:
        articles = await search_naver_news(kw)
        for a in articles:
            u = a['url']
            if u not in url_map:
                url_map[u] = {
                    "title": a['title'],
                    "url": u,
                    "domain": extract_domain(u),
                    "matched": set([kw]),
                    "title_text": a['title']
                }
            else:
                url_map[u]['matched'].add(kw)
    # 주요언론사 필터
    if search_mode == "major":
        url_map = {k:v for k,v in url_map.items() if v["domain"] in MAJOR_PRESS}

    # 2개 이상 키워드 필터
    if checked_two_keywords:
        url_map = {k:v for k,v in url_map.items() if len(v["matched"]) >= 2}
    # 키워드 매치 수 내림차순
    results = sorted(url_map.values(), key=lambda x: len(x["matched"]), reverse=True)
    for r in results:
        r["matched_str"] = ", ".join([f"{k}({r['title_text'].count(k)})" for k in sorted(r["matched"], key=lambda k: -r["title_text"].count(k))])

    # 선택 체크박스 및 복사 텍스트
    selected_urls = selected_urls or [r['url'] for r in results]
    copy_text = "\n\n".join([f"{r['title']} [{r['matched_str']}]\n{r['url']}" for r in results if r['url'] in selected_urls])
    msg = f"총 {len(results)}건의 뉴스가 검색되었습니다."

    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "results": results,
        "checked_two_keywords": checked_two_keywords,
        "search_mode": search_mode,
        "msg": msg,
        "copy_text": copy_text,
        "selected_urls": selected_urls,
        "failed": []
    })

@app.post("/shorten", response_class=HTMLResponse)
async def shorten(request: Request,
    keywords: str = Form(...),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    selected_urls: List[str] = Form(None),
    results_data: str = Form(None)
):
    import json
    selected_urls = selected_urls or []
    results = json.loads(results_data)
    # Playwright 단축주소화 (선택된 url만)
    short_url_map = {}
    failed = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width":400,"height":700}, user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1")
        for r in results:
            if r['url'] in selected_urls and r['url'].startswith("https://n.news.naver.com/"):
                try:
                    await page.goto(r['url'])
                    await page.wait_for_selector("#spiButton", timeout=7000)
                    await page.click("#spiButton")
                    await page.wait_for_selector("input#spi_short_url_text", timeout=7000)
                    short_url = await page.input_value("input#spi_short_url_text")
                    short_url_map[r['url']] = short_url
                except Exception as e:
                    failed.append((r['title'], r['url'], str(e)))
            else:
                short_url_map[r['url']] = r['url']
        await browser.close()
    # 결과 반영
    for r in results:
        r['final_url'] = short_url_map.get(r['url'], r['url'])
    # 복사 텍스트(단축주소 반영)
    selected_urls = selected_urls or [r['url'] for r in results]
    copy_text = "\n\n".join([f"{r['title']} [{r['matched_str']}]\n{r['final_url']}" for r in results if r['url'] in selected_urls])
    msg = "단축주소 변환 완료" if not failed else "일부 단축주소 변환 실패"
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "results": results,
        "checked_two_keywords": checked_two_keywords,
        "search_mode": search_mode,
        "msg": msg,
        "copy_text": copy_text,
        "selected_urls": selected_urls,
        "failed": failed
    })
