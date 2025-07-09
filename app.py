# app.py
# -*- coding: utf-8 -*-

import os
import json
import random
import string
import logging
import asyncio # asyncio 임포트 추가 (Playwright 사용을 위해)
import re # re (정규 표현식) 모듈 임포트. 'NameError' 발생 시 이 줄을 확인하십시오.
from fastapi import FastAPI, Request, Form, HTTPException, status
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import httpx
from datetime import datetime, timedelta # datetime, timedelta 임포트 추가
from typing import List, Dict, Optional # Optional 임포트 추가

# ... (중략: 위쪽은 동일)

async def naver_me_shorten(orig_url: str) -> tuple[str, str]:
    """
    Playwright를 사용하여 naver.me 단축 URL을 생성합니다.
    이 함수는 웹 자동화에 의존하므로 불안정할 수 있습니다.
    성공 시 (단축 URL, ""), 실패 시 (원본 URL, 실패 이유 문자열) 튜플 반환.
    """
    from playwright.async_api import async_playwright 

    logger.info(f"naver.me 단축 URL 변환 시도 시작. 원본 URL: {orig_url}")
    
    # ... (중략: 도메인 검사, 브라우저 설정 등 동일)

    browser = None
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True, 
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-accelerated-2d-canvas',
                    '--disable-gpu',
                    '--start-maximized'
                ]
            )
            iphone_13_user_agent = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
            iphone_13_viewport = {"width": 428, "height": 926}

            page = await browser.new_page(
                viewport=iphone_13_viewport, 
                user_agent=iphone_13_user_agent
            )
            logger.info(f"Playwright 페이지 생성 완료. User-Agent: {iphone_13_user_agent}, Viewport: {iphone_13_viewport}")

            await page.goto(orig_url, timeout=20000)
            # [오류 수정] 잘못된 메서드명을 아래와 같이 수정!
            await page.wait_for_load_state('networkidle')  # ← [FIX]
            logger.info(f"페이지 로드 완료 및 networkidle 상태 대기 완료: {orig_url}")
            await asyncio.sleep(random.uniform(2.0, 4.0))

            # ... (이하 동일, 버튼 클릭/단축주소 추출 등)
            # (아래 코드는 변경 사항 없음)
            # ...
    except Exception as e:
        logger.error(f"Playwright 오류 발생 (naver_me_shorten): {e}", exc_info=True)
        return orig_url, f"Playwright 오류: {str(e)}"
    finally:
        if browser:
            await browser.close()

# ... (이하 코드 동일. 추가 수정 없음)

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8080))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
