# -*- coding: utf-8 -*-

from flask import Flask, request, jsonify
import os, requests, html, urllib.parse, asyncio
from datetime import datetime, timedelta, timezone
import email.utils as eut
from langdetect import detect
from bs4 import BeautifulSoup
import feedparser
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
                return domain, name
        return domain, domain
    except Exception:
        return None, None

def convert_to_mobile_link(url):
    if "n.news.naver.com/article" in url:
        return url.replace("n.news.naver.com/article", "n.news.naver.com/mnews/article")
    return url

def search_news(query, display=10):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display={display}&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    return []

def parse_pubdate(pubdate_str):
    try:
        dt = datetime(*eut.parsedate(pubdate_str)[:6], tzinfo=timezone(timedelta(hours=9)))
        return dt
    except:
        return None

# Playwright로 네이버 단축주소 변환
async def get_naver_short_url(long_url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("https://me2.do/")
        # 실제 네이버 단축주소 생성 페이지의 구조를 참고해서 수정 필요!
        await page.fill('input[type="text"]', long_url)
        await page.click('button[type="submit"]')
        await page.wait_for_selector('input[readonly]')
        short_url = await page.input_value('input[readonly]')
        await browser.close()
        return short_url

def sync_get_naver_short_url(long_url):
    try:
        return asyncio.run(get_naver_short_url(long_url))
    except Exception as e:
        return f"생성실패: {e}"

# Flask 앱
app = Flask(__name__)

@app.route("/")
def home():
    return "Flask + Playwright 네이버 뉴스검색 및 단축주소 API 정상동작!"

@app.route("/news", methods=["GET"])
def news():
    query = request.args.get("query", "군대")
    search_mode = request.args.get("mode", "전체")  # 전체/동영상만/주요언론사만
    now = datetime.now(timezone(timedelta(hours=9)))
    def_keywords = ["육군", "국방", "외교", "안보", "북한",
                    "신병교육대", "훈련", "간부", "장교",
                    "부사관", "병사", "용사", "군무원"]
    keyword_list = request.args.get("keywords")
    if keyword_list:
        keyword_list = [k.strip() for k in keyword_list.split(",") if k.strip()]
    else:
        keyword_list = def_keywords

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
                if press not in press_name_map.values():
                    continue
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
        try:
            v["short_url"] = sync_get_naver_short_url(v["url"])
        except Exception as e:
            v["short_url"] = v["url"]
        articles.append(v)
    sorted_list = sorted(articles, key=lambda x: x['pubdate'], reverse=True)
    output = []
    for art in sorted_list:
        output.append({
            "title": art['title'],
            "press": art['press'],
            "pubdate": art['pubdate'].strftime('%Y-%m-%d %H:%M'),
            "matched": art['matched'],
            "url": convert_to_mobile_link(art['url']),
            "short_url": art.get("short_url", "")
        })
    return jsonify(output)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
