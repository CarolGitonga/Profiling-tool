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

logger = logging.getLogger(__name__)

SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))

def _get_client():
    if not SCRAPINGBEE_API_KEY:
        logger.error("❌ SCRAPINGBEE_API_KEY missing in environment.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)

def _fetch_with_playwright(username: str) -> str:
    """Fallback: Launch real browser to render TikTok page and return HTML."""
    logger.info(f"🎭 Playwright fallback for TikTok user {username}")
    html = None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                ),
                viewport={'width':1280, 'height':720}
            )
            page = context.new_page()
            url = f"https://www.tiktok.com/@{username}"
            page.goto(url, wait_until="networkidle", timeout=40000)
            # Optionally: implement scrolling / delays
            html = page.content()
            browser.close()
            logger.info(f"✅ Playwright rendered HTML for {username}")
    except Exception as e:
        logger.exception(f"❌ Playwright fails for {username}: {e}")
    return html

def _fetch_tiktok_html(username: str) -> (str, str): # type: ignore
    """Try ScrapingBee first; if fails, fallback to Playwright."""
    client = _get_client()
    if not client:
        return None, "no-client"

    regions = ["us", "fr", "de", "gb", "ca"]
    for region in random.sample(regions, len(regions)):
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

    # fallback
    html = _fetch_with_playwright(username)
    return html, "Playwright (fallback)" if html else "Failed"

def scrape_tiktok_profile(username: str):
    """Fetch & persist TikTok profile + posts in DB."""
    html, source = _fetch_tiktok_html(username)
    if not html:
        return {"success": False, "reason": f"Failed to fetch HTML: {source}"}

    # parse HTML using BeautifulSoup or directly search JSON embedded
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")

    # Extract profile stats using data-e2e attributes (as blog suggests)
    try:
        uname = soup.select_one('h1[data-e2e="user-title"]').text.strip()
        full_name = soup.select_one('h2[data-e2e="user-subtitle"]').text.strip()
        followers = int(re.sub(r"[^\d]", "", soup.select_one('strong[data-e2e="followers-count"]').text))
        following = int(re.sub(r"[^\d]", "", soup.select_one('strong[data-e2e="following-count"]').text))
        likes = int(re.sub(r"[^\d]", "", soup.select_one('strong[data-e2e="likes-count"]').text))
        bio = soup.select_one('h2[data-e2e="user-bio"]').text.strip()
    except Exception as e:
        logger.exception(f"Parsing profile stats failed for {username}: {e}")
        # Might fallback to JSON containment

    # Persist
    profile, _ = Profile.objects.update_or_create(
        username=username,
        platform="TikTok",
        defaults={"full_name": full_name, "avatar_url": ""}
    )
    SocialMediaAccount.objects.update_or_create(
        profile=profile,
        platform="TikTok",
        defaults={
            "bio": bio,
            "followers": followers,
            "following": following,
            "posts_collected": 0,
            "is_private": False,
            "external_url": ""
        }
    )

    return {
        "success": True,
        "source": source,
        "username": username,
        "full_name": full_name,
        "followers": followers,
        "following": following,
        "likes": likes,
        "bio": bio
    }
# ============================================================
# ❌ Unscrape TikTok Profile (Safe Delete Helper)
# ============================================================
from profiles.models import Profile, SocialMediaAccount, RawPost

def unscrape_tiktok_profile(username: str) -> bool:
    """
    Delete all TikTok-related records (profile + social media account + raw posts).
    Safe to call when re-scraping or cleaning up data.
    """
    try:
        profile = Profile.objects.get(username=username, platform="TikTok")
        SocialMediaAccount.objects.filter(profile=profile, platform="TikTok").delete()
        RawPost.objects.filter(profile=profile, platform="TikTok").delete()
        profile.delete()
        return True
    except Profile.DoesNotExist:
        return False
    except Exception as e:
        import logging
        logging.exception(f"❌ Error deleting TikTok profile {username}: {e}")
        return False
