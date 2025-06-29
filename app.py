from flask import Flask, request, jsonify
import os
import requests
import urllib.parse
import html
from datetime import datetime, timedelta, timezone
import email.utils as eut
from bs4 import BeautifulSoup
import feedparser
from langdetect import detect
import asyncio
from playwright.async_api import async_playwright

app = Flask(__name__)

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

# Playwright로 naver.me 단축주소 받아오기 예시 함수
async def get_naver_short_url(long_url):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        # 네이버 단축주소 생성 페이지 접속
        await page.goto("https://me2.do/")
        # 실제 네이버 단축 주소를 만드는 자동화 절차를 여기 구현해야 함
        # (아래는 예시입니다. 실제 구현에 맞게 직접 작성)
        # 예시: input에 URL 입력, 버튼 클릭, 결과 복사 등
        # await page.fill("input[name='url']", long_url)
        # await page.click("button[type='submit']")
        # await page.wait_for_selector(".short-url")
        # short_url = await page.input_value(".short-url")
        # ------
        short_url = "https://naver.me/xxxx"  # 예시, 실제 구현 필요
        await browser.close()
        return short_url

def sync_get_naver_short_url(long_url):
    # 동기 방식으로 Playwright 호출
    return asyncio.run(get_naver_short_url(long_url))

# 네이버 뉴스 검색 API
def search_news(query):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=3&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    return []

@app.route('/')
def index():
    return "Flask 뉴스검색+Playwright 단축주소 API 정상 실행 중!"

@app.route('/news')
def news():
    query = request.args.get("query", "군대")
    items = search_news(query)
    result = []
    for item in items:
        title = html.unescape(item["title"]).replace("<b>", "").replace("</b>", "")
        url = item["link"]
        # 단축주소 생성 (실제로는 Playwright 동작)
        short_url = sync_get_naver_short_url(url)
        result.append({
            "title": title,
            "url": url,
            "short_url": short_url
        })
    return jsonify(result)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
