# app.py
# -*- coding: utf-8 -*-
import os, re, asyncio, logging, urllib.parse
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_NAVER_CLIENT_ID_HERE")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_NAVER_CLIENT_SECRET_HERE")
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

# 주요 언론사 도메인 매핑
PRESS_DOMAIN_MAP = {
    "chosun.com": "조선일보", "yna.co.kr": "연합뉴스", "hani.co.kr": "한겨레",
    "joongang.co.kr": "중앙일보", "mbn.co.kr": "MBN", "kbs.co.kr": "KBS",
    "sbs.co.kr": "SBS", "ytn.co.kr": "YTN", "donga.com": "동아일보",
    "segye.com": "세계일보", "munhwa.com": "문화일보", "newsis.com": "뉴시스",
    "naver.com": "네이버", "daum.net": "다음", "kukinews.com": "국민일보",
    "kookbang.dema.mil.kr": "국방일보", "edaily.co.kr": "이데일리",
    "news1.kr": "뉴스1", "jtbc.co.kr": "JTBC"
}
PRESS_MAJOR_SET = set(PRESS_DOMAIN_MAP.values())

DEFAULT_KEYWORDS = [
    "육군", "국방", "외교", "안보", "북한", "신병", "교육대", "훈련", "간부",
    "장교", "부사관", "병사", "용사", "군무원"
]

def extract_press(item):
    pub = item.get("publisher", "")
    url = item.get("originallink") or item.get("link", "")
    try:
        netloc = urllib.parse.urlparse(url).netloc.replace("www.", "")
        for key, name in PRESS_DOMAIN_MAP.items():
            if netloc == key or netloc.endswith("." + key):
                return name
        return pub or netloc
    except Exception:
        return pub or ""

def parse_pubdate(pubdate_str):
    try:
        dt = parsedate_to_datetime(pubdate_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone(timedelta(hours=9)))
        return dt
    except Exception:
        return None

def clean_html_tags(text):
    # <b>제목</b>, &quot; 등 처리
    t = re.sub(r"<[^>]+>", "", text or "")
    t = t.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    return t

async def search_news_naver(keyword, display=20, max_retries=3):
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {"query": keyword, "display": display, "sort": "date"}
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
                res.raise_for_status()
                return res.json().get("items", [])
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                await asyncio.sleep(2 ** attempt)
            else:
                raise
        except Exception:
            raise
    return []

app = FastAPI()
templates = Jinja2Templates(directory="templates")

@app.get("/", response_class=HTMLResponse)
async def get_index(request: Request):
    now = datetime.now(timezone(timedelta(hours=9)))
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "keyword_input": ', '.join(DEFAULT_KEYWORDS),
            "final_articles": [],
            "search_mode": "전체",
            "video_only": False,
            "now": now.strftime('%Y-%m-%d %H:%M:%S'),
            "msg": None,
        }
    )

@app.post("/", response_class=HTMLResponse)
async def post_search(
    request: Request,
    keywords: str = Form(""),
    search_mode: str = Form("전체"),
    video_only: str = Form(""),
):
    now = datetime.now(timezone(timedelta(hours=9)))
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]
    if not keyword_list:
        keyword_list = DEFAULT_KEYWORDS

    url_map = {}
    semaphore = asyncio.Semaphore(4)
    async def limited_search(kw):
        async with semaphore:
            return await search_news_naver(kw, display=15)

    tasks = [limited_search(kw) for kw in keyword_list]
    result_lists = await asyncio.gather(*tasks)

    for idx, items in enumerate(result_lists):
        kw = keyword_list[idx]
        for a in items:
            title = clean_html_tags(a.get("title", ""))
            desc = clean_html_tags(a.get("description", ""))
            url = a.get("link", "")
            press = extract_press(a)
            pub = parse_pubdate(a.get("pubDate", ""))
            if not url: continue
            if url not in url_map:
                url_map[url] = {
                    "title": title, "desc": desc, "url": url, "press": press,
                    "pubdate": pub, "matched": set(),
                }
            haystack = f"{title} {desc}"
            if kw in haystack:
                url_map[url]["matched"].add(kw)
    articles = []
    for v in url_map.values():
        if not v["pubdate"] or (now - v["pubdate"] > timedelta(hours=4)):
            continue
        if len(v["matched"]) < 2:
            continue
        if search_mode == "주요언론사만" and v["press"] not in PRESS_MAJOR_SET:
            continue
        if search_mode == "동영상만":
            video_keys = ["영상", "동영상", "영상보기", "보러가기", "뉴스영상", "영상뉴스", "클릭하세요", "바로보기"]
            if v["press"] not in PRESS_MAJOR_SET:
                continue
            if not (any(k in v["desc"] for k in video_keys) or any(k in v["title"] for k in video_keys)):
                continue
        articles.append(v)
    sorted_articles = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
    for art in sorted_articles:
        art["pubdate_str"] = art["pubdate"].strftime('%Y-%m-%d %H:%M') if art["pubdate"] else ""
        art["matched_list"] = sorted(list(art["matched"]), key=lambda x: x)
        art["matched_count"] = len(art["matched"])
        art["copy_text"] = f"■ {art['title']} ({art['press']})\n{art['url']}"

    msg = f"검색 결과: {len(sorted_articles)}건 (4시간 이내, 2개 이상 키워드 포함)"
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "keyword_input": ', '.join(keyword_list),
            "final_articles": sorted_articles,
            "search_mode": search_mode,
            "video_only": video_only == "on",
            "now": now.strftime('%Y-%m-%d %H:%M:%S'),
            "msg": msg,
        }
    )
