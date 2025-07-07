import os
import json
import random, string
from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
import httpx

NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID", "YOUR_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET", "YOUR_CLIENT_SECRET")
NAVER_NEWS_API_URL = "https://openapi.naver.com/v1/search/news.json"

app = FastAPI(title="뉴스검색기 (FastAPI+NaverAPI)")
templates = Jinja2Templates(directory="templates")

DEFAULT_KEYWORDS = [
    '육군', '국방', '외교', '안보', '북한', '신병', '교육대',
    '훈련', '간부', '장교', '부사관', '병사', '용사', '군무원'
]

async def search_naver_news(query: str, display: int = 10):
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET,
    }
    params = {
        "query": query,
        "display": display,
        "sort": "date",
    }
    async with httpx.AsyncClient() as client:
        res = await client.get(NAVER_NEWS_API_URL, headers=headers, params=params)
        res.raise_for_status()
        return res.json().get("items", [])

async def naver_me_shorten(orig_url: str) -> str:
    # 실제 naver.me 단축주소 크롤링은 필요시 구현
    short = "https://naver.me/" + ''.join(random.choices(string.ascii_letters + string.digits, k=7))
    print(f">> [naver_me_shorten] {orig_url} -> {short}")
    return short

@app.get("/", include_in_schema=False)
async def get_index(request: Request):
    print(">> [GET /] index")
    return templates.TemplateResponse(
        "index.html",
        {
            'request': request,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'keyword_input': '',
            'final_results': None,
            'shortened': None
        }
    )

@app.post("/", include_in_schema=False)
async def post_search(
    request: Request,
    keywords: str = Form(...),
):
    print(f">> [POST /] keywords={keywords}")
    kw_list = [k.strip() for k in keywords.split(',') if k.strip()]
    if not kw_list:
        kw_list = DEFAULT_KEYWORDS
    query = " ".join(kw_list)
    news_items = await search_naver_news(query)
    # API 결과를 기존 파싱 결과와 맞춰서 구조 변환
    final_results = []
    for item in news_items:
        final_results.append({
            "title": item.get("title"),
            "press": item.get("originallink", ""),  # 언론사 정보가 없어서 링크로 대체
            "pubdate": item.get("pubDate", ""),
            "url": item.get("link"),
            "desc": item.get("description"),
            "keywords": [],  # API 결과에는 키워드 카운트 없음
            "kw_count": 0
        })
    print(">> [POST /] search_naver_news results:", len(final_results))
    return templates.TemplateResponse(
        "index.html",
        {
            'request': request,
            'final_results': final_results,
            'keyword_input': keywords,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
            'shortened': None
        }
    )

@app.post("/shorten", include_in_schema=False)
async def post_shorten(
    request: Request,
    selected_urls: list = Form(...),
    final_results_json: str = Form(...),
    keyword_input: str = Form('')
):
    print(">> [POST /shorten] selected_urls:", selected_urls)
    final_results = json.loads(final_results_json)
    print(">> [POST /shorten] final_results loaded:", len(final_results))
    shortened_list = []
    for idx in selected_urls:
        try:
            orig = final_results[int(idx)]['url']
            short = await naver_me_shorten(orig)
            shortened_list.append(short)
        except Exception as e:
            print("!! [POST /shorten] Error:", e)
    print(">> [POST /shorten] shortened_list:", shortened_list)
    return templates.TemplateResponse(
        "index.html",
        {
            'request': request,
            'final_results': final_results,
            'shortened': '\n'.join(shortened_list),
            'keyword_input': keyword_input,
            'default_keywords': ', '.join(DEFAULT_KEYWORDS),
        }
    )

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
