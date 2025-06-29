import streamlit as st
import requests
import urllib.parse
import html
from datetime import datetime, timedelta, timezone
import email.utils as eut
from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
st.write("🔍 st.secrets 내용:", dict(st.secrets))
# NAVER API 키
NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET")

def convert_to_short_url_playwright(original_url):
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 375, "height": 812}, is_mobile=True)
            page = context.new_page()
            mobile_url = original_url.replace("n.news.", "n.news.m")

            page.goto(mobile_url, timeout=10000)
            page.wait_for_timeout(2000)

            page.locator("text=공유").click()
            page.wait_for_timeout(2000)

            short_input = page.locator("input.copy_url")
            short_url = short_input.input_value()

            browser.close()
            return short_url
    except Exception as e:
        print("단축주소 생성 실패:", e)
        return original_url

def search_news(query):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=5&sort=date"
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

st.title("📰 네이버 뉴스 검색기 (단축주소 포함)")
query = st.text_input("검색어를 입력하세요", "국방")

if st.button("뉴스 검색"):
    with st.spinner("검색 중..."):
        results = search_news(query)
        for item in results:
            title = html.unescape(item["title"]).replace("<b>", "").replace("</b>", "")
            url = item["link"]
            short_url = convert_to_short_url_playwright(url)
            st.write(f"**{title}**")
            st.markdown(f"[단축주소로 보기]({short_url})")
