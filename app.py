# app.py

import os, re, requests
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from typing import List, Dict
from fastapi import FastAPI, HTTPException, Query
import uvicorn

app = FastAPI(title="Naver Mobile News Analyzer")

# 1) 헬스체크 엔드포인트
@app.get("/", include_in_schema=False)
async def health_check():
    return {"status": "ok"}

# 2) /analyze 엔드포인트 (기존 로직)
DEFAULT_KEYWORDS = [ … ]
PRESS_MAJOR = { … }

def parse_time(timestr): … 
def parse_newslist(html, keywords, search_mode, video_only): …
def fetch_html(url): …

@app.get("/analyze")
async def analyze(
    url: str = Query(...),
    mode: str = Query("all", regex="^(all|major)$"),
    video: bool = Query(False),
    kws: str = Query("")
):
    try:
        html = fetch_html(url)
    except Exception as e:
        raise HTTPException(400, f"URL 요청 실패: {e}")
    user_keywords = [k.strip() for k in kws.split(",") if k.strip()]
    keywords = user_keywords or None
    articles = parse_newslist(html, keywords, mode, video)
    return {
        "count": len(articles),
        "articles": articles
    }

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
