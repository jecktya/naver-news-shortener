import os
import re
from collections import Counter, defaultdict
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse
import httpx
import urllib.parse
from playwright.async_api import async_playwright

NAVER_CLIENT_ID = os.getenv("NAVER_CLIENT_ID", "")
NAVER_CLIENT_SECRET = os.getenv("NAVER_CLIENT_SECRET", "")

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# 기본 키워드
DEFAULT_KEYWORDS = ["육군", "국방", "외교", "안보", "북한", "신병", "교육대", "훈련", "간부", "장교", "부사관", "병사", "용사", "군무원"]

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
MAJOR_PRESS = set(press_name_map.values())

def extract_press_name(url):
    try:
        domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        for key, name in press_name_map.items():
            if domain == key or domain.endswith("." + key):
                return name
        return domain
    except:
        return "?"

def convert_to_mobile_link(url):
    if "n.news.naver.com/article" in url:
        return url.replace("n.news.naver.com/article", "n.news.naver.com/mnews/article")
    return url

async def shorten_url_playwright(orig_url):
    # 모바일 환경에서 네이버 공유 버튼 누르고 naver.me 추출
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width':390, 'height':844}, user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1')
        try:
            await page.goto(orig_url, timeout=8000)
            # 공유버튼 탐색 (대표 selector, 필요시 추가 개선)
            try:
                await page.click('button[aria-label="공유"], #spiButton > span > span, span.u_hc', timeout=5000)
            except:
                # 여러 selector 시도
                share_found = False
                selectors = ['#spiButton > span > span', 'span.u_hc', 'button[aria-label="공유"]', '[aria-label="공유"]']
                for sel in selectors:
                    try:
                        await page.click(sel, timeout=2000)
                        share_found = True
                        break
                    except:
                        continue
                if not share_found:
                    await browser.close()
                    return None, "공유버튼 selector 찾지 못함"
            # 1. URL 복사 버튼(텍스트: '링크 복사' or 'URL복사') 클릭
            await page.wait_for_selector('button[aria-label*="복사"], span:has-text("링크 복사"), span:has-text("URL복사")', timeout=4000)
            # naver.me 주소 찾기
            naver_me_url = None
            # html에서 naver.me 주소 찾기
            content = await page.content()
            for match in re.findall(r'https://naver\.me/\w+', content):
                naver_me_url = match
                break
            await browser.close()
            if naver_me_url:
                return naver_me_url, None
            return None, "naver.me 주소를 찾지 못함"
        except Exception as e:
            await browser.close()
            return None, f"Playwright 오류: {str(e)}"

async def naver_news_search(query, count=20):
    url = f"https://openapi.naver.com/v1/search/news.json?query={urllib.parse.quote(query)}&display={count}&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    async with httpx.AsyncClient() as client:
        res = await client.get(url, headers=headers)
        if res.status_code == 200:
            return res.json().get("items", [])
        else:
            return []

def count_keywords_in_text(text, keywords):
    kw_counts = Counter()
    for kw in keywords:
        # *키워드* 포함(띄어쓰기 상관없이)
        cnt = len(re.findall(re.escape(kw), text))
        if cnt > 0:
            kw_counts[kw] += cnt
    return kw_counts

@app.get("/", response_class=HTMLResponse)
async def main(request: Request):
    # 기본 진입
    return await render_news_page(request)

@app.post("/", response_class=HTMLResponse)
async def main_post(
    request: Request,
    keywords: str = Form(""),
    checked_two_keywords: str = Form(""),
    search_mode: str = Form("major"),
    selected_urls: list = Form(None)
):
    return await render_news_page(request, keywords, checked_two_keywords, search_mode, selected_urls)

async def render_news_page(request, keywords="", checked_two_keywords="", search_mode="major", selected_urls=None, final_results=None, msg=""):
    keywords_list = [k.strip() for k in (keywords or ",".join(DEFAULT_KEYWORDS)).split(",") if k.strip()]
    if "신병교육대" in keywords_list:
        keywords_list.remove("신병교육대")
        keywords_list.extend(["신병", "교육대"])

    # 뉴스 검색 및 키워드 카운트
    news_articles = []
    url_to_data = {}
    all_items = []
    for kw in keywords_list:
        items = await naver_news_search(kw, count=20)
        for a in items:
            url = convert_to_mobile_link(a["link"])
            press = extract_press_name(a.get("originallink") or url)
            title = re.sub(r"<\/?b>", "", a["title"])
            desc = re.sub(r"<\/?b>", "", a.get("description", ""))
            # 중복기사 제거
            if url in url_to_data:
                url_to_data[url]["matched"].append(kw)
            else:
                url_to_data[url] = {
                    "title": title,
                    "url": url,
                    "press": press,
                    "desc": desc,
                    "matched": [kw]
                }
    # 2개 이상 키워드만 필터링
    final_results = list(url_to_data.values())
    for r in final_results:
        r["kw_counts"] = count_keywords_in_text(r["title"] + r["desc"], keywords_list)
        r["kw_count"] = sum(r["kw_counts"].values())

    if checked_two_keywords:
        final_results = [a for a in final_results if a["kw_count"] >= 2]

    # 주요언론사 필터(기본)
    if search_mode == "major":
        final_results = [a for a in final_results if a["press"] in MAJOR_PRESS]
    # 키워드 많은순 정렬
    final_results.sort(key=lambda x: (-x["kw_count"], x["title"]))

    # 선택항목
    if selected_urls is None:
        selected_urls = [a["url"] for a in final_results]

    # 최종 copy_area 텍스트 생성
    copy_area = ""
    for a in final_results:
        kw_label = ", ".join([f"{k}({v})" for k, v in a["kw_counts"].most_common() if v > 0])
        copy_area += f"■ {a['title']} ({a['press']})\n키워드: {kw_label}\n{a['url']}\n\n"

    return templates.TemplateResponse("news_search.html", {
        "request": request,
        "final_results": final_results,
        "selected_urls": selected_urls,
        "copy_area": copy_area.strip(),
        "default_keywords": ", ".join(DEFAULT_KEYWORDS),
        "checked_two_keywords": checked_two_keywords,
        "search_mode": search_mode,
        "msg": msg
    })

@app.post("/shorten", response_class=HTMLResponse)
async def shorten(request: Request,
                  keywords: str = Form(""),
                  checked_two_keywords: str = Form(""),
                  search_mode: str = Form("major"),
                  selected_urls: list = Form(None),
                  copy_area: str = Form("")):
    # 주소변환 버튼: 선택된 기사만
    lines = copy_area.split("\n")
    url_map = {}
    url_list = []
    for i, l in enumerate(lines):
        url_match = re.search(r"(https://n\.news\.naver\.com/mnews/article/\d+/\d+[\w\?=]*)", l)
        if url_match:
            url = url_match.group(1)
            url_map[url] = i
            url_list.append(url)
    success, fail = {}, {}
    for url in url_list:
        try:
            short_url, err = await shorten_url_playwright(url)
            if short_url:
                success[url] = short_url
            else:
                fail[url] = err or "원인불명"
        except Exception as e:
            fail[url] = str(e)
    # copy_area에서 변환
    new_lines = []
    for l in lines:
        nline = l
        for orig, short in success.items():
            nline = nline.replace(orig, short)
        new_lines.append(nline)
    # 실패 사유
    fail_msgs = []
    for url, reason in fail.items():
        fail_msgs.append(f"- {url}: {reason}")
    msg = ""
    if fail_msgs:
        msg = "주소 변환 실패 목록:<br>" + "<br>".join(fail_msgs)
    return await render_news_page(request, keywords, checked_two_keywords, search_mode, selected_urls, msg=msg)

# (선택적) 디버그 경로
@app.get("/debug", response_class=HTMLResponse)
async def debug(request: Request):
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return f"서버시간(UTC+9): {now}<br>env: NAVER_CLIENT_ID={NAVER_CLIENT_ID[:6]}***, NAVER_CLIENT_SECRET={NAVER_CLIENT_SECRET[:6]}***"

