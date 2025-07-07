import streamlit as st
import requests
import urllib.parse
import html
from datetime import datetime, timedelta, timezone
import email.utils as eut

# 환경변수(Secrets) 확인
NAVER_CLIENT_ID = st.secrets.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = st.secrets.get("NAVER_CLIENT_SECRET")
if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
    st.error("❌ NAVER_CLIENT_ID / NAVER_CLIENT_SECRET가 제대로 등록되지 않았습니다.")
else:
    st.info(f"NAVER_CLIENT_ID: {NAVER_CLIENT_ID[:4]}***")

def_keywords = ["육군", "국방", "외교", "안보", "북한",
                "신병교육대", "훈련", "간부", "장교",
                "부사관", "병사", "용사", "군무원"]
input_keywords = st.text_input("🔍 키워드 입력 (쉼표 또는 띄어쓰기로 구분)", ", ".join(def_keywords))
# 쉼표 또는 공백 기준 분리
keyword_list = [k.strip() for k in input_keywords.replace(",", " ").split() if k.strip()]

def search_news(query):
    enc = urllib.parse.quote(query)
    url = f"https://openapi.naver.com/v1/search/news.json?query={enc}&display=30&sort=date"
    headers = {"X-Naver-Client-Id": NAVER_CLIENT_ID, "X-Naver-Client-Secret": NAVER_CLIENT_SECRET}
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            return r.json().get("items", [])
        elif r.status_code == 401:
            st.error("❌ 네이버 API 인증 오류! 환경변수를 다시 확인하세요.")
        elif r.status_code == 429:
            st.error("❌ 네이버 뉴스 API 쿼터 초과! 잠시 후 시도하세요.")
        else:
            st.error(f"❌ 네이버 뉴스 API 오류({r.status_code})")
    except Exception as e:
        st.error(f"❌ API 요청 중 오류: {e}")
    return []

st.write("뉴스 검색 예시: 키워드 하나(예: 육군), 또는 '육군, 국방' 처럼 1~2개만 권장 (너무 많으면 결과 0건 가능)")

if st.button("🔍 뉴스 검색"):
    with st.spinner("뉴스 검색 중..."):
        if not keyword_list:
            st.warning("검색할 키워드를 입력하세요.")
        else:
            # 여러 키워드를 OR 조건으로 묶기
            query = " OR ".join(keyword_list)
            items = search_news(query)
            if not items:
                st.warning("🔎 해당 키워드로 최근 뉴스 결과가 없습니다. 키워드를 1~2개로 줄여 다시 시도해 보세요!")
            else:
                for a in items:
                    title = html.unescape(a["title"]).replace("<b>", "").replace("</b>", "")
                    desc = html.unescape(a.get("description", "")).replace("<b>", "").replace("</b>", "")
                    st.write(f"**{title}**")
                    st.write(desc)
                    st.write(a["link"])
                    st.write("---")
