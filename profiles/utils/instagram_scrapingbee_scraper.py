import os
import re
import json
import logging
from bs4 import BeautifulSoup
from datetime import datetime
from scrapingbee import ScrapingBeeClient
from playwright.sync_api import sync_playwright
from django.utils import timezone

logger = logging.getLogger(__name__)
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY")

# ==========================================================
# 🧩 MAIN SCRAPER
# ==========================================================
def scrape_instagram_profile(username: str) -> dict:
    """
    Fetch Instagram profile and recent posts using ScrapingBee (primary)
    and Playwright (fallback).
    """
    logger.info(f"📸 Starting Instagram scrape for {username}")

    try:
        html = _fetch_with_scrapingbee(username)
        if not html:
            html = _fetch_with_playwright(username)

        if not html:
            return {"success": False, "reason": "Failed to fetch HTML"}

        soup = BeautifulSoup(html, "html.parser")
        data = _parse_profile_data(soup)

        logger.info(f"✅ Instagram scrape success for {username}")
        return {"success": True, "source": data.pop("source", "unknown"), **data}

    except Exception as e:
        logger.exception(f"❌ Instagram scrape error for {username}: {e}")
        return {"success": False, "reason": str(e)}

# ==========================================================
# 🕸 ScrapingBee Fetch
# ==========================================================
def _fetch_with_scrapingbee(username: str) -> str:
    if not SCRAPINGBEE_API_KEY:
        logger.warning("⚠️ Missing ScrapingBee API key")
        return None

    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)
    target_url = f"https://www.instagram.com/{username}/"

    try:
        response = client.get(target_url, params={"render_js": "true"})
        if response.status_code == 200:
            logger.info(f"✅ ScrapingBee succeeded for {username}")
            return response.content.decode("utf-8")
        else:
            logger.warning(f"⚠️ ScrapingBee returned {response.status_code} for {username}")
    except Exception as e:
        logger.error(f"ScrapingBee failed for {username}: {e}")
    return None

# ==========================================================
# 🎭 Playwright Fallback
# ==========================================================
def _fetch_with_playwright(username: str) -> str:
    from playwright.sync_api import sync_playwright
    import shutil, subprocess, sys

    PLAYWRIGHT_PATH = "/opt/render/project/src/.playwright"
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_PATH
    PY_EXEC = shutil.which("python") or shutil.which("python3") or sys.executable

    # Ensure Playwright browsers are installed
    if not os.path.exists(os.path.join(PLAYWRIGHT_PATH, "chromium_headless_shell-1187")):
        try:
            os.makedirs(PLAYWRIGHT_PATH, exist_ok=True)
            subprocess.run(
                [PY_EXEC, "-m", "playwright", "install", "chromium", "chromium-headless-shell"],
                check=True,
                env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": PLAYWRIGHT_PATH},
            )
            logger.info(f"✅ Playwright browsers installed at {PLAYWRIGHT_PATH}")
        except Exception as e:
            logger.error(f"❌ Playwright install failed: {e}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"https://www.instagram.com/{username}/", timeout=60000)
            page.wait_for_timeout(5000)
            html = page.content()
            browser.close()
            logger.info(f"✅ Playwright fallback succeeded for {username}")
            return html
    except Exception as e:
        logger.error(f"❌ Playwright fallback failed for {username}: {e}")
        return None

# ==========================================================
# 🧠 Parse Profile Info
# ==========================================================
def _parse_profile_data(soup: BeautifulSoup) -> dict:
    script_tag = soup.find("script", text=re.compile("window._sharedData"))
    if not script_tag:
        return {"source": "HTML", "username": "", "full_name": "", "followers": 0, "following": 0, "bio": "", "avatar": ""}

    json_text = re.search(r"window\._sharedData\s*=\s*(\{.*\});", script_tag.text)
    if not json_text:
        return {"source": "HTML"}

    data = json.loads(json_text.group(1))
    try:
        user = data["entry_data"]["ProfilePage"][0]["graphql"]["user"]
        return {
            "source": "Instagram",
            "username": user.get("username"),
            "full_name": user.get("full_name"),
            "followers": user["edge_followed_by"]["count"],
            "following": user["edge_follow"]["count"],
            "bio": user.get("biography"),
            "avatar": user.get("profile_pic_url_hd"),
        }
    except Exception:
        return {"source": "Instagram", "reason": "JSON parsing failed"}
