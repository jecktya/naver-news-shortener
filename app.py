# -*- coding: utf-8 -*-
import os
import asyncio
import html
import urllib.parse
import requests
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from playwright.async_api import async_playwright

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

press_name_map = {
    "chosun.com": "조선일보", "yna.co.kr": "연합뉴스", "hani.co.kr": "한겨레",
    "joongang.co.kr": "중앙일보", "mbn.co.kr": "MBN", "kbs.co.kr": "KBS",
    "sbs.co.kr": "SBS", "ytn.co.kr": "YTN", "donga.com": "동아일보",
    "segye.com": "세계일보", "munhwa.com": "문화일보", "newsis.com": "뉴시스",
    "naver.com": "네이버", "daum.net": "다음", "kukinews.com": "국민일보",
    "kookbang.dema.mil.kr": "국방일보", "edaily.co.kr": "이데일리",
    "news1.kr": "뉴스1", "mbnmoney.mbn.co.kr": "MBN", "news.kmib.co.kr": "국민일보",
    "jtbc.co.kr": "JTBC"
}
major_press = set(press_name_map.values())
default_keywords = ["육군", "국방", "외교", "안보", "북한", "신병", "교육대", "훈련", "간부", "장교", "부사관", "병사", "용사", "군무원"]

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# static 폴더 미사용이면 아래 주석 처리
# app.mount("/static", StaticFiles(directory="static"), name="static")

def extract_press_name(url):
    try:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        for key, name in press_name_map.items():
            if domain == key or domain.endswith("." + key):
                return domain, name
        return domain, domain
    except Exception:
        return None, None

def convert_to_mobile_link(url):
    if "n.news.naver.com/article" in url:
        return url.replace("n.news.naver.com/article", "n.news.naver.com/mnews/article")
    return url

def parse_pubdate(pubdate_str):
    try:
        import email.utils as eut
        dt = datetime(*eut.parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except Exception:
        return None

def search_news(query):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=50&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    return []

# Playwright로 naver.me 주소 변환
async def get_naver_short_url(news_url):
    # naver 모바일 뉴스만 변환
    if not news_url.startswith("https://n.news.naver.com/"):
        return news_url, "지원 안함"
    try:
        async with async_playwright() as p:
            iphone = p.devices["iPhone 13 Pro"]
            browser = await p.webkit.launch(headless=True)
            context = await browser.new_context(**iphone)
            page = await context.new_page()
            await page.goto(convert_to_mobile_link(news_url), timeout=15000, wait_until="networkidle")
            await page.wait_for_selector("#spiButton", timeout=7000)
            await page.click("#spiButton")
            # 공유 페이지 전환 또는 팝업 탐색
            # 네이버는 보통 새 창을 띄움
            pages = context.pages
            if len(pages) < 2:
                await asyncio.sleep(2)
                pages = context.pages
            target = pages[-1]
            # input[type='text'] 안에 naver.me 주소 노출
            input_box = await target.query_selector("input[type='text']")
            if input_box:
                short_url = await input_box.input_value()
                await context.close()
                await browser.close()
                return short_url, None
            # 대체로 span.u_hc 안에 주소 노출
            span_url = await target.query_selector("span.u_hc")
            if span_url:
                short_url = await span_url.inner_text()
                await context.close()
                await browser.close()
                return short_url, None
            await context.close()
            await browser.close()
            return news_url, "공유 버튼 selector를 찾지 못함"
    except Exception as e:
        return news_url, f"Playwright 오류: {str(e)}"

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    now = datetime.now(timezone(timedelta(hours=9)))
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "msg": "",
        "default_keywords": ', '.join(default_keywords),
        "final_results": [],
        "copy_text": "",
        "checked_two_keywords": False,
        "search_mode": "major",
        "selected_urls": [],
        "fail_msgs": [],
        "now": now.strftime('%Y-%m-%d %H:%M:%S'),
        "kw_counts": []
    })

@app.post("/", response_class=HTMLResponse)
async def main_post(
    request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    selected_urls: list = Form(None)
):
    now = datetime.now(timezone(timedelta(hours=9)))
    msg = ""
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not kw_list:
        kw_list = default_keywords

    # 신병교육대 => 신병, 교육대 분리
    kw_expanded = []
    for k in kw_list:
        if k in ("신병교육대",):
            kw_expanded.extend(["신병", "교육대"])
        else:
            kw_expanded.append(k)
    kw_list = kw_expanded

    # 기사 크롤링
    url_map = {}
    count_map = defaultdict(lambda: [0]*len(kw_list))  # URL -> [count by kw]
    raw_articles = []
    for idx, kw in enumerate(kw_list):
        items = search_news(kw)
        for a in items:
            title = html.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
            desc = html.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
            url = a.get("originallink") or a["link"]
            pub = parse_pubdate(a.get("pubDate", "")) or datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))
            domain, press = extract_press_name(url)
            if not pub or (now - pub > timedelta(hours=4)):
                continue
            if search_mode == "major" and press not in major_press:
                continue
            # 기사 중복 방지
            if url not in url_map:
                url_map[url] = {
                    "title": title,
                    "url": url,
                    "press": press,
                    "pubdate": pub,
                    "matched": [],
                }
            url_map[url]["matched"].append(kw)
            # 키워드 카운트용
            count_map[url][idx] += title.count(kw) + desc.count(kw)
            raw_articles.append((title, url, press, pub, kw))

    # 2개 이상 키워드 포함 필터
    results = []
    for u, art in url_map.items():
        kw_counter = Counter(art["matched"])
        # 한 키워드 여러번도 2개로 인정
        if checked_two_keywords:
            if sum(kw_counter.values()) < 2:
                continue
        results.append({
            **art,
            "kw_counter": kw_counter,
            "kw_cnt": sum(kw_counter.values())
        })

    # 키워드 카운트 내림차순 정렬
    results = sorted(results, key=lambda x: (-x["kw_cnt"], x['pubdate']), reverse=False)
    for r in results:
        kw_names = []
        for k, c in r['kw_counter'].most_common():
            kw_names.append(f"{k}({c})" if c > 1 else k)
        r['matched_str'] = ', '.join(kw_names)

    # 결과 text
    copy_text = '\n\n'.join(
        f"■ {r['title']} ({r['press']})\n{convert_to_mobile_link(r['url'])}"
        for r in results
    )

    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "msg": f"총 {len(results)}건 검색됨",
        "default_keywords": ', '.join(kw_list),
        "final_results": results,
        "copy_text": copy_text,
        "checked_two_keywords": checked_two_keywords,
        "search_mode": search_mode,
        "selected_urls": [r['url'] for r in results],
        "fail_msgs": [],
        "now": now.strftime('%Y-%m-%d %H:%M:%S'),
        "kw_counts": [r['matched_str'] for r in results],
    })

@app.post("/shorten", response_class=HTMLResponse)
async def shorten(request: Request, keywords: str = Form(""), search_mode: str = Form("major"),
                  checked_two_keywords: str = Form(None),
                  selected_urls: list = Form(None),
                  copy_text: str = Form(""),
                  **data):
    now = datetime.now(timezone(timedelta(hours=9)))
    msg = ""
    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not kw_list:
        kw_list = default_keywords

    # 신병교육대 => 신병, 교육대 분리
    kw_expanded = []
    for k in kw_list:
        if k in ("신병교육대",):
            kw_expanded.extend(["신병", "교육대"])
        else:
            kw_expanded.append(k)
    kw_list = kw_expanded

    # 기사 크롤링 (copy_text로 재생성)
    lines = [line for line in copy_text.strip().split('\n\n') if line.strip()]
    url_title_map = {}
    for l in lines:
        try:
            title_line, url_line = l.split('\n', 1)
            url = url_line.strip()
            url_title_map[url] = title_line
        except Exception:
            continue

    # 선택된 URL만 변환
    if isinstance(selected_urls, str):
        selected_urls = [selected_urls]
    new_results = []
    fail_msgs = []
    for url in url_title_map.keys():
        if url in selected_urls:
            short_url, fail = await get_naver_short_url(url)
            if fail:
                fail_msgs.append(f"{url}: {fail}")
                new_results.append(f"{url_title_map[url]}\n{url}")
            else:
                new_results.append(f"{url_title_map[url]}\n{short_url}")
        else:
            new_results.append(f"{url_title_map[url]}\n{url}")

    copy_text_new = "\n\n".join(new_results)
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "msg": "주소변환 완료" if not fail_msgs else "일부 변환 실패",
        "default_keywords": ', '.join(kw_list),
        "final_results": [],
        "copy_text": copy_text_new,
        "checked_two_keywords": checked_two_keywords,
        "search_mode": search_mode,
        "selected_urls": selected_urls or [],
        "fail_msgs": fail_msgs,
        "now": now.strftime('%Y-%m-%d %H:%M:%S'),
        "kw_counts": [],
    })
