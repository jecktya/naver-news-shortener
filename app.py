from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os, requests, html, urllib.parse, asyncio
from datetime import datetime, timedelta, timezone
from playwright.async_api import async_playwright

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

app = FastAPI()
templates = Jinja2Templates(directory="templates")

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

def search_news(query):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=10&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    r = requests.get(url, headers=headers)
    if r.status_code == 200:
        return r.json().get("items", [])
    return []

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    return templates.TemplateResponse("index.html", {"request": request, "articles": None})

@app.post("/", response_class=HTMLResponse)
async def search(request: Request, query: str = Form(...)):
    items = search_news(query)
    news = []
    for item in items:
        title = html.unescape(item["title"]).replace("<b>", "").replace("</b>", "")
        url = item["link"]
        try:
            short_url = await get_short_url(url)
        except Exception as e:
            short_url = url
        news.append({"title": title, "url": short_url})
    return templates.TemplateResponse("index.html", {"request": request, "articles": news, "query": query})
