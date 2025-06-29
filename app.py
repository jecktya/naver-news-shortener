import os, requests, html, urllib.parse, asyncio
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
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

def extract_press_name(url):
    try:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        for key, name in press_name_map.items():
            if domain == key or domain.endswith("." + key):
                return name
        return domain
    except:
        return None

def convert_to_mobile_link(url):
    if "n.news.naver.com/article" in url:
        return url.replace("n.news.naver.com/article", "n.news.naver.com/mnews/article")
    return url

def parse_pubdate(pubdate_str):
    try:
        import email.utils as eut
        dt = datetime(*eut.parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except:
        return None

def search_news(query):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    return []

async def get_short_url(long_url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://me2.do/")
        await page.fill('input[type="text"]', long_url)
        await page.click('button[type="submit"]')
        await page.wait_for_selector('input[readonly]')
        short_url = await page.input_value('input[readonly]')
        await browser.close()
        return short_url

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "articles": None,
        "search_mode": "전체",
        "keywords": "육군, 국방, 외교, 안보, 북한, 신병교육대, 훈련, 간부, 장교, 부사관, 병사, 용사, 군무원"
    })

@app.post("/", response_class=HTMLResponse)
async def news(
    request: Request,
    search_mode: str = Form(...),
    keywords: str = Form(...)
):
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
            press = extract_press_name(a.get("originallink") or url)

            # 4시간 이내 필터
            if not pub or (now - pub > timedelta(hours=4)):
                continue
            # 모드별 필터
            if search_mode == "주요언론사만" and press not in press_name_map.values():
                continue
            if search_mode == "동영상만":
                if press not in press_name_map.values():
                    continue
                video_keys = ["영상", "동영상", "영상보기", "보러가기", "뉴스영상", "영상뉴스", "클릭하세요", "바로보기"]
                video_text = any(k in desc for k in video_keys) or any(k in title for k in video_keys)
                video_url = any(p in url for p in ["/v/", "/video/", "vid="])
                if not (video_text or video_url):
                    continue

            # 중복 관리 및 키워드 매핑
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

    # 결과 정리 및 단축주소 변환
    articles = []
    for v in url_map.values():
        v["matched"] = sorted(v["matched"])
        # Playwright로 단축주소 변환
        try:
            v["short_url"] = await get_short_url(convert_to_mobile_link(v["url"]))
        except Exception:
            v["short_url"] = convert_to_mobile_link(v["url"])
        articles.append(v)
    sorted_list = sorted(articles, key=lambda x: x['pubdate'], reverse=True)

    return templates.TemplateResponse("index.html", {
        "request": request,
        "articles": sorted_list,
        "search_mode": search_mode,
        "keywords": keywords
    })
