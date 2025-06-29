# selector_finder.py

import json
import os
from typing import Optional
from playwright.async_api import Page

CACHE_FILE = "selector_cache.json"

DEFAULT_SELECTORS = [
    'button[aria-label="공유"]',
    'button[aria-label="공유하기"]',
    'button[class*="share"]',
    'button[data-testid*="Share"]',
    'button[title*="공유"]',
    '[role="button"]',
]

def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_cache(cache):
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)

async def find_and_click_share(page: Page, press_name: str) -> Optional[str]:
    cache = load_cache()
    # 1. 캐시 사용
    if press_name in cache:
        sel = cache[press_name]
        try:
            await page.click(sel, timeout=2000)
            return sel
        except:
            pass # 캐시가 실패하면 아래로

    # 2. 후보군에서 탐색
    for sel in DEFAULT_SELECTORS:
        try:
            await page.click(sel, timeout=2000)
            # 성공 시 캐시 저장
            cache[press_name] = sel
            save_cache(cache)
            return sel
        except:
            continue
    return None
