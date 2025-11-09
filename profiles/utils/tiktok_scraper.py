import os
import re
import json
import random
import logging
from datetime import datetime, timezone as dt_timezone
from textblob import TextBlob
from scrapingbee import ScrapingBeeClient
from django.conf import settings
from profiles.models import Profile, SocialMediaAccount, RawPost
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ============================================================
# 🔑 Config
# ============================================================
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))
REGIONS = ["us", "fr", "de", "gb", "ca", "ke"]


# ============================================================
# 🐝 ScrapingBee Client
# ============================================================
def _get_client():
    if not SCRAPINGBEE_API_KEY:
        logger.error("❌ SCRAPINGBEE_API_KEY missing in environment.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)


# ============================================================
# 🎭 Playwright Fallback
# ============================================================
def _fetch_with_playwright(username: str) -> str:
    """Launch headless Chromium to render TikTok page and return HTML."""
    logger.info(f"🎭 Playwright fallback for TikTok user {username}")
    html = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15"
                ),
                viewport={"width": 1280, "height": 720},
            )
            page = context.new_page()
            url = f"https://www.tiktok.com/@{username}"
            page.goto(url, wait_until="networkidle", timeout=45000)

            # Give TikTok's JS time to render dynamic counters
            page.wait_for_timeout(5000)
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(2000)

            # Ensure counters exist
            try:
                page.wait_for_selector('[data-e2e="followers-count"]', timeout=10000)
            except Exception:
                logger.warning(f"⚠️ Counters not found immediately for {username}")

            html = page.content()
            browser.close()
            logger.info(f"✅ Playwright rendered HTML for {username}")
    except Exception as e:
        logger.exception(f"❌ Playwright failed for {username}: {e}")
    return html


# ============================================================
# 🔄 Primary Fetch (ScrapingBee → Playwright fallback)
# ============================================================
def _fetch_tiktok_html(username: str):
    """Try ScrapingBee first; if fails, fallback to Playwright."""
    client = _get_client()
    if not client:
        return None, "no-client"

    for region in random.sample(REGIONS, len(REGIONS)):
        try:
            resp = client.get(
                f"https://www.tiktok.com/@{username}",
                params={
                    "render_js": "true",
                    "wait_browser": "networkidle",
                    "stealth_proxy": "true",
                    "premium_proxy": "true",
                    "country_code": region,
                    "device": "desktop",
                },
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0.0.0 Safari/537.36"
                    ),
                    "Referer": "https://www.tiktok.com/",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
            if resp.status_code == 200 and "SIGI_STATE" in resp.text:
                logger.info(f"✅ ScrapingBee region={region} succeeded for {username}")
                return resp.text, f"ScrapingBee ({region})"
            else:
                logger.warning(f"⚠️ TikTok returned {resp.status_code} region={region} for {username}")
        except Exception as e:
            logger.warning(f"⚠️ Region {region} fails for {username}: {e}")

    # Fallback to Playwright
    html = _fetch_with_playwright(username)
    return html, "Playwright (fallback)" if html else "Failed"


# ============================================================
# 🧠 Parse TikTok Profile
# ============================================================
def _parse_tiktok_profile(html: str) -> dict:
    """Extract user data from rendered HTML (Playwright or ScrapingBee)."""
    soup = BeautifulSoup(html, "html.parser")

    def safe_text(tag):
        el = soup.select_one(f'[data-e2e="{tag}"]')
        return el.text.strip() if el else ""

    def parse_count(val: str) -> int:
        """Convert 1.2M / 3K / 450 into integer."""
        val = val.replace(",", "").upper()
        if "B" in val: return int(float(val.replace("B", "")) * 1_000_000_000)
        if "M" in val: return int(float(val.replace("M", "")) * 1_000_000)
        if "K" in val: return int(float(val.replace("K", "")) * 1_000)
        return int(val) if val.isdigit() else 0

    username = safe_text("user-title")
    full_name = safe_text("user-subtitle")
    bio = safe_text("user-bio")
    followers = parse_count(safe_text("followers-count"))
    following = parse_count(safe_text("following-count"))
    likes = parse_count(safe_text("likes-count"))
    avatar = (
        soup.select_one('[data-e2e="user-avatar"] img[src]')["src"]
        if soup.select_one('[data-e2e="user-avatar"] img[src]')
        else ""
    )

    return {
        "username": username,
        "full_name": full_name,
        "bio": bio,
        "followers": followers,
        "following": following,
        "likes": likes,
        "avatar": avatar,
    }


# ============================================================
# 🚀 Main Scraper
# ============================================================
def scrape_tiktok_profile(username: str):
    """Fetch TikTok profile, parse, and save to DB."""
    html, source = _fetch_tiktok_html(username)
    if not html:
        return {"success": False, "reason": f"Failed to fetch HTML: {source}"}

    data = _parse_tiktok_profile(html)
    if not data["username"]:
        return {"success": False, "reason": "No valid TikTok profile parsed."}

    # Persist
    profile, _ = Profile.objects.update_or_create(
        username=username,
        platform="TikTok",
        defaults={
            "full_name": data["full_name"],
            "avatar_url": data["avatar"],
        },
    )

    SocialMediaAccount.objects.update_or_create(
        profile=profile,
        platform="TikTok",
        defaults={
            "bio": data["bio"],
            "followers": data["followers"],
            "following": data["following"],
            "posts_collected": 0,
            "is_private": False,
            "external_url": "",
        },
    )

    logger.info(
        f"💾 Saved TikTok profile: {username}, followers={data['followers']}, following={data['following']}, likes={data['likes']}, source={source}"
    )

    return {"success": True, "source": source, **data}


# ============================================================
# ❌ Unscrape Helper
# ============================================================
def unscrape_tiktok_profile(username: str) -> bool:
    """Delete all TikTok-related data for re-scraping."""
    try:
        profile = Profile.objects.get(username=username, platform="TikTok")
        SocialMediaAccount.objects.filter(profile=profile, platform="TikTok").delete()
        RawPost.objects.filter(profile=profile, platform="TikTok").delete()
        profile.delete()
        logger.info(f"🗑️ Removed TikTok data for {username}")
        return True
    except Profile.DoesNotExist:
        return False
    except Exception as e:
        logger.exception(f"❌ Error deleting TikTok profile {username}: {e}")
        return False
