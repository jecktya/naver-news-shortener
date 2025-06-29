import os
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from typing import List, Dict, Any
import requests
import urllib.parse
import html as htmlmod
from datetime import datetime, timedelta, timezone
import email.utils as eut
import asyncio
from playwright.async_api import async_playwright

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

TEMPLATE_KWS = [
    "육군", "국방", "외교", "안보", "북한",
    "신병", "교육대", "훈련", "간부", "장교",
    "부사관", "병사", "용사", "군무원"
]
MAJOR_PRESS = {
    "chosun.com": "조선일보", "yna.co.kr": "연합뉴스", "hani.co.kr": "한겨레",
    "joongang.co.kr": "중앙일보", "mbn.co.kr": "MBN", "kbs.co.kr": "KBS",
    "sbs.co.kr": "SBS", "ytn.co.kr": "YTN", "donga.com": "동아일보",
    "segye.com": "세계일보", "munhwa.com": "문화일보", "newsis.com": "뉴시스",
    "naver.com": "네이버", "daum.net": "다음", "kukinews.com": "국민일보",
    "kookbang.dema.mil.kr": "국방일보", "edaily.co.kr": "이데일리",
    "news1.kr": "뉴스1", "mbnmoney.mbn.co.kr": "MBN", "news.kmib.co.kr": "국민일보",
    "jtbc.co.kr": "JTBC"
}
MAJOR_PRESS_DOMAINS = list(MAJOR_PRESS.keys())

# Press별 공유버튼 Selector
PRESS_SELECTOR_MAP = {
    "chosun.com": 'button[aria-label="공유"], #spiButton, span.u_hc',
    "hani.co.kr": 'button[aria-label="공유"], #spiButton, span.u_hc',
    "yna.co.kr": 'button[aria-label="공유"], #spiButton, span.u_hc',
    "joongang.co.kr": 'button[aria-label="공유"], #spiButton, span.u_hc',
    "donga.com": 'button[aria-label="공유"], #spiButton, span.u_hc',
    "n.news.naver.com": '#spiButton, span.u_hc, [data-tiara-action-name="공유하기"], button[aria-label="공유"], span:has-text("SNS 보내기")',
    # 필요한 경우 추가
}
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "")

def extract_press_name(url: str):
    try:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        for key, name in MAJOR_PRESS.items():
            if domain == key or domain.endswith("." + key):
                return domain, name
        return domain, domain
    except:
        return None, None

def parse_pubdate(pubdate_str):
    try:
        dt = datetime(*eut.parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except:
        return None

def count_keywords_in_text(text, keywords):
    # 키워드별 출현 수 (동일 키워드 여러번 등장도 포함)
    result = []
    for k in keywords:
        result.extend([k]*text.count(k))
    return result

def is_major_press(domain):
    return domain in MAJOR_PRESS_DOMAINS

def make_mobile_link(url):
    if "n.news.naver.com/article" in url:
        return url.replace("n.news.naver.com/article", "n.news.naver.com/mnews/article")
    return url

def get_press_selector(url):
    # 도메인별 selector map
    domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
    for d, selector in PRESS_SELECTOR_MAP.items():
        if domain == d or domain.endswith(d):
            return selector
    # 네이버뉴스 전용
    if "n.news.naver.com" in url:
        return PRESS_SELECTOR_MAP["n.news.naver.com"]
    return '#spiButton, span.u_hc, button[aria-label="공유"], span:has-text("SNS 보내기")'

# --- Playwright 비동기 단축주소 변환 함수 ---
async def get_naver_short_url(news_url, selectors=None):
    short_url = None
    error_msg = None
    selectors = selectors or get_press_selector(news_url)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Linux; Android 10; SM-G975N) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/88.0.4324.93 Mobile Safari/537.36"
            )
            page = await context.new_page()
            await page.goto(news_url, timeout=15000)
            try:
                btn = await page.wait_for_selector(selectors, timeout=7000)
                await btn.click()
                await asyncio.sleep(0.8) # 네이버는 버튼 누르면 공유메뉴 띄움
                # 모바일 네이버 기준으로 input[type=text] 나 .share_layer input 등
                # input 안의 value가 단축주소
                input_sel = 'input[type="text"], .share_layer input'
                inp = await page.wait_for_selector(input_sel, timeout=4000)
                val = await inp.get_attribute('value')
                if val and val.startswith("https://naver.me/"):
                    short_url = val
            except Exception as ex:
                error_msg = f"Playwright 오류: 공유버튼 selector를 찾지 못함 ({ex})"
            await browser.close()
    except Exception as e:
        error_msg = f"Playwright 오류: {str(e)}"
    return short_url, error_msg

# --- FastAPI 엔드포인트 ---

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(TEMPLATE_KWS),
        "final_results": [],
        "selected_urls": [],
        "msg": "",
        "checked_two_keywords": False,
        "search_mode": "major"
    })

@app.post("/", response_class=HTMLResponse)
async def search_news(
    request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    selected_urls: List[str] = Form(None)
):
    msg = ""
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    final_articles = []
    now = datetime.now(timezone(timedelta(hours=9)))
    url_map = {}
    for kw in keyword_list:
        enc = urllib.parse.quote(kw)
        url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
        headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            continue
        items = r.json().get("items", [])
        for a in items:
            title = htmlmod.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
            desc = htmlmod.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
            news_url = a["link"]
            pub = parse_pubdate(a.get("pubDate", "")) or datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))
            domain, press = extract_press_name(a.get("originallink") or news_url)
            # 4시간 이내만
            if not pub or (now - pub > timedelta(hours=4)):
                continue
            if search_mode == "major" and press not in MAJOR_PRESS.values():
                continue
            # 키워드 출현수 (동일키워드 여러번도 포함)
            matched = []
            matched += count_keywords_in_text(title, keyword_list)
            matched += count_keywords_in_text(desc, keyword_list)
            if not matched:
                continue
            if news_url not in url_map:
                url_map[news_url] = {
                    "title": title,
                    "url": news_url,
                    "press": press,
                    "pubdate": pub,
                    "matched": matched
                }
            else:
                url_map[news_url]["matched"] += matched

    articles = []
    for v in url_map.values():
        # 2개 이상 체크시
        if checked_two_keywords and len(v["matched"]) < 2:
            continue
        v["matched"] = sorted(v["matched"])
        articles.append(v)
    sorted_list = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
    msg = f"최종 기사 수: {len(sorted_list)}"
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(TEMPLATE_KWS),
        "final_results": sorted_list,
        "selected_urls": [a['url'] for a in sorted_list],
        "msg": msg,
        "checked_two_keywords": bool(checked_two_keywords),
        "search_mode": search_mode
    })

@app.post("/shorten", response_class=HTMLResponse)
async def shorten_urls(
    request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(None),
    search_mode: str = Form("major"),
    selected_urls: List[str] = Form(None)
):
    msg = ""
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    selected_urls = selected_urls if selected_urls else []
    # 검색결과 재구성 (일관성 위해)
    url_map = {}
    now = datetime.now(timezone(timedelta(hours=9)))
    for kw in keyword_list:
        enc = urllib.parse.quote(kw)
        url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
        headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            continue
        items = r.json().get("items", [])
        for a in items:
            title = htmlmod.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
            desc = htmlmod.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
            news_url = a["link"]
            pub = parse_pubdate(a.get("pubDate", "")) or datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))
            domain, press = extract_press_name(a.get("originallink") or news_url)
            if not pub or (now - pub > timedelta(hours=4)):
                continue
            if search_mode == "major" and press not in MAJOR_PRESS.values():
                continue
            matched = []
            matched += count_keywords_in_text(title, keyword_list)
            matched += count_keywords_in_text(desc, keyword_list)
            if not matched:
                continue
            if news_url not in url_map:
                url_map[news_url] = {
                    "title": title,
                    "url": news_url,
                    "press": press,
                    "pubdate": pub,
                    "matched": matched
                }
            else:
                url_map[news_url]["matched"] += matched

    articles = []
    for v in url_map.values():
        if checked_two_keywords and len(v["matched"]) < 2:
            continue
        v["matched"] = sorted(v["matched"])
        articles.append(v)
    sorted_list = sorted(articles, key=lambda x: x['pubdate'], reverse=True)

    # 선택된 기사만 변환
    url_to_short = {a["url"]: a for a in sorted_list if a["url"] in selected_urls}
    results_texts = []
    for art in sorted_list:
        url = art["url"]
        orig_link = url
        short_url = url
        short_msg = ""
        # 네이버 뉴스일 때만 변환 시도
        if url in url_to_short and url.startswith("https://n.news.naver.com/"):
            su, err = await get_naver_short_url(url)
            if su:
                short_url = su
                short_msg = "(단축 성공)"
            else:
                short_msg = f"(변환실패: {err or '공유 버튼 미탐색'})"
        results_texts.append(f"■ {art['title']} ({art['press']})\n{short_url} {short_msg}")
    final_txt = "\n\n".join(results_texts)
    msg = f"주소 단축 처리 완료. 변환 결과 {len(results_texts)}건"
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "default_keywords": ", ".join(TEMPLATE_KWS),
        "final_results": sorted_list,
        "selected_urls": selected_urls,
        "msg": msg,
        "checked_two_keywords": bool(checked_two_keywords),
        "search_mode": search_mode,
        "final_txt": final_txt
    })

# 디버그 엔드포인트
@app.get("/debug", response_class=PlainTextResponse)
async def debug():
    import os
    from datetime import datetime
    now = datetime.now(timezone(timedelta(hours=9))).isoformat()
    files = os.listdir(".")
    NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
    NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")
    return f"NAVER_CLIENT_ID: {NAVER_CLIENT_ID}\nNAVER_CLIENT_SECRET: {NAVER_CLIENT_SECRET}\n서버시간: {now}\n[현재폴더 파일 목록]\n" + "\n".join(files)

