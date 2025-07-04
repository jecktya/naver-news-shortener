from fastapi import FastAPI, Query
from news_analyzer import fetch_html, parse_newslist

app = FastAPI()

@app.get("/analyze")
async def analyze(url: str = Query(..., description="네이버 모바일 뉴스 URL")):
    html = fetch_html(url)
    articles = parse_newslist(html)
    return {"count": len(articles), "articles": articles}
