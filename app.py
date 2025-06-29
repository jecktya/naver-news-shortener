# -*- coding: utf-8 -*-
import os
import html
import urllib.parse
import requests
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from playwright.async_api import async_playwright

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

app = FastAPI()
templates = Jinja2Templates(directory="templates")

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

def extract_press_name(url):
    try:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        for key, name in press_name_map.items():
            if domain == key or domain.endswith("." + key):
                return domain, name
        return domain, domain
    except Exception:
        return None, None

def search_news(query):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    return []

def parse_pubdate(pubdate_str):
    import email.utils as eut
    try:
        dt = datetime(*eut.parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except:
        return None

def get_share_button_selector(press):
    selector_map = {
        "조선일보": 'button[aria-label="공유"]',
        "연합뉴스": 'button[aria-label="공유"]',
        "한겨레": 'button[aria-label="공유"]',
        "중앙일보": 'button[aria-label="공유"]',
        "동아일보": 'button[aria-label="공유"]',
        "세계일보": 'button[aria-label="공유"]',
        "문화일보": 'button[aria-label="공유"]',
        "뉴시스": 'button[aria-label="공유"]',
        "네이버": 'button[aria-label="공유"]',
        "다음": 'button[aria-label="공유"]',
        "국민일보": 'button[aria-label="공유"]',
        "국방일보": 'button[aria-label="공유"]',
        "이데일리": 'button[aria-label="공유"]',
        "뉴스1": 'button[aria-label="공유"]',
        "JTBC": 'button[aria-label="공유"]',
        # 필요시 추가
    }
    return selector_map.get(press, 'button[aria-label="공유"]')

async def get_mobile_naverme_url(url, press_name, debug_msgs):
    try:
        async with async_playwright() as p:
            iphone = p.devices['iPhone 12']
            browser = await p.webkit.launch(headless=True)
            context = await browser.new_context(**iphone)
            page = await context.new_page()
            await page.goto(url)
            share_selector = get_share_button_selector(press_name)
            await page.click(share_selector, timeout=5000)
            # 공유창 뜨면 '링크 복사' 또는 단축주소 나타나는 input selector도 조사 필요!
            # 아래는 예시 (수정 필요)
            # await page.click('text=링크 복사')
            # short_url = await page.evaluate('navigator.clipboard.readText()')
            # 또는 화면에 표시된 naver.me 링크 추출
            short_url = None
            try:
                await page.wait_for_selector('input[type="text"]', timeout=3000)
                short_url = await page.input_value('input[type="text"]')
            except Exception:
                pass
            await browser.close()
            if short_url and short_url.startswith('https://naver.me/'):
                return short_url
            else:
                debug_msgs.append(f"[{url}] 단축주소 추출 실패, 원본주소 반환")
                return url
    except Exception as e:
        debug_msgs.append(f"[{url}] Playwright 오류: {e}")
        return url

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    default_keywords = ["육군", "국방", "외교", "안보", "북한",
                "신병교육대", "훈련", "간부", "장교",
                "부사관", "병사", "용사", "군무원"]
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "results": [],
        "selected": [],
        "search_mode": "주요언론사만",
        "keywords": ", ".join(default_keywords),
        "now": datetime.now(timezone(timedelta(hours=9))).strftime("%Y-%m-%d %H:%M"),
        "final_txt": "",
        "short_urls": [],
        "debug_msgs": [],
    })

@app.post("/search", response_class=HTMLResponse)
async def search(request: Request, keywords: str = Form(...), search_mode: str = Form(...)):
    debug_msgs = []
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    now = datetime.now(timezone(timedelta(hours=9)))
    url_map = {}
    for kw in keyword_list:
        items = search_news(kw)
        for a in items:
            title = html.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
            desc = html.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
            url = a["link"]
            pub = parse_pubdate(a.get("pubDate", "")) or datetime.min.replace(tzinfo=timezone(timedelta(hours=9)))
            domain, press = extract_press_name(a.get("originallink") or url)
            if not pub or (now - pub > timedelta(hours=4)):
                continue
            if search_mode == "주요언론사만" and press not in press_name_map.values():
                continue
            if search_mode == "동영상만":
                video_keys = ["영상", "동영상", "영상보기", "보러가기", "뉴스영상", "영상뉴스", "클릭하세요", "바로보기"]
                video_text = any(k in desc for k in video_keys) or any(k in title for k in video_keys)
                video_url = any(p in url for p in ["/v/", "/video/", "vid="])
                if not (video_text or video_url):
                    continue
            if url not in url_map:
                url_map[url] = {
                    "title": title,
                    "url": url,
                    "press": press,
                    "pubdate": pub,
                    "matched": set([kw])
                }
            else:
                url_map[url]["matched"].add(kw)
    articles = []
    for v in url_map.values():
        v["matched"] = sorted(v["matched"])
        articles.append(v)
    sorted_list = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
    final_txt = "\n\n".join(
        [f"■ {a['title']} ({a['press']})\n{a['url']}" for a in sorted_list]
    )
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "results": sorted_list,
        "selected": [a['url'] for a in sorted_list],
        "search_mode": search_mode,
        "keywords": keywords,
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "final_txt": final_txt,
        "short_urls": [],
        "debug_msgs": debug_msgs,
    })

@app.post("/shorten", response_class=HTMLResponse)
async def shorten_urls(request: Request, urls: str = Form(...), presses: str = Form(...), keywords: str = Form(...), search_mode: str = Form(...)):
    url_list = [u.strip() for u in urls.split(',') if u.strip()]
    press_list = [p.strip() for p in presses.split(',') if p.strip()]
    debug_msgs = []
    short_urls = []
    for u, p in zip(url_list, press_list):
        short = await get_mobile_naverme_url(u, p, debug_msgs)
        short_urls.append(short)
    final_txt = "\n\n".join([f"{u} => {s}" for u, s in zip(url_list, short_urls)])
    # 다시 검색 결과 리스트도 같이 출력 (사용자 UX 위해)
    now = datetime.now(timezone(timedelta(hours=9)))
    results = []
    for url, press in zip(url_list, press_list):
        title = url  # 간략하게 처리(생략), 실제로는 기사 데이터도 전달해야 UX가 좋음
        results.append({
            "title": title,
            "url": url,
            "press": press,
            "pubdate": now,
            "matched": [],
        })
    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "results": results,
        "selected": url_list,
        "search_mode": search_mode,
        "keywords": keywords,
        "now": now.strftime("%Y-%m-%d %H:%M"),
        "final_txt": final_txt,
        "short_urls": short_urls,
        "debug_msgs": debug_msgs,
    })
