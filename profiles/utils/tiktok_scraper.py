import logging
import asyncio
import json
import re
from playwright.async_api import async_playwright
from profiles.models import Profile, SocialMediaAccount
from django.conf import settings

#import logging
#import asyncio
#import json
#from playwright.async_api import async_playwright
from django.conf import settings

logger = logging.getLogger(__name__)

# --- Environment Setup ---
# settings.ENV("CHROME_PROFILE_PATH") → incorrect (Django settings has no ENV)
# Instead, use getattr or os.getenv safely
import os

TIKTOK_LOCAL_MODE = os.getenv("TIKTOK_LOCAL_MODE", "False").lower() == "true"

if TIKTOK_LOCAL_MODE:
    CHROME_PROFILE_PATH = r"C:\Users\carol\AppData\Local\Google\Chrome\User Data\Profile 1"
else:
    CHROME_PROFILE_PATH = "/app/chrome-profile"  # for Render (headless)

logger.info(f"🎬 TikTok scraper initialized | LOCAL_MODE={TIKTOK_LOCAL_MODE}")


# --- Async Core Function ---
async def _fetch_tiktok_info(username: str):
    """Internal async scraper that uses Playwright to extract TikTok user info."""

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch_persistent_context(
                user_data_dir=CHROME_PROFILE_PATH,
                headless=not TIKTOK_LOCAL_MODE,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )

            page = await browser.new_page()
            url = f"https://www.tiktok.com/@{username}"
            logger.info(f"🌐 Navigating to {url}")

            await page.goto(url, timeout=60000)

            # Find the embedded JSON element
            element = await page.query_selector('script[id="__UNIVERSAL_DATA_FOR_REHYDRATION__"]')
            if not element:
                logger.warning(f"⚠️ Could not find TikTok JSON script for {username}")
                return {"error": f"Could not find JSON script for {username}"}

            raw_json = await element.inner_text()

            # --- Parse JSON safely ---
            try:
                data = json.loads(raw_json)
            except json.JSONDecodeError as e:
                logger.error(f"❌ Failed to parse TikTok JSON for {username}: {e}")
                return {"error": f"Failed to parse TikTok JSON: {e}"}

            # --- Extract fields ---
            try:
                user_info = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
                user = user_info.get("user", {})
                stats = user_info.get("stats", {})

                scraped_data = {
                    "username": user.get("uniqueId"),
                    "nickname": user.get("nickname"),
                    "bio": user.get("signature"),
                    "followers": stats.get("followerCount"),
                    "following": stats.get("followingCount"),
                    "likes": stats.get("heartCount"),
                    "video_count": stats.get("videoCount"),
                    "verified": user.get("verified", False),
                    "avatar": user.get("avatarLarger"),
                }

                logger.info(f"✅ Scraped TikTok user: {username} | Followers: {scraped_data['followers']}")
                return scraped_data

            except KeyError:
                logger.exception(f"⚠️ TikTok JSON structure changed for {username}")
                return {"error": f"JSON structure changed, could not parse {username}"}

        except Exception as e:
            logger.exception(f"❌ TikTok scraping failed for {username}: {e}")
            return {"error": str(e)}

        finally:
            try:
                await browser.close()
            except Exception as e:
                logger.warning(f"⚠️ Could not close browser context cleanly: {e}")

"""
CHROME_PROFILE_PATH = settings.ENV("CHROME_PROFILE_PATH")

async def _fetch_tiktok_info(username: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=CHROME_PROFILE_PATH,
            headless=False
        )
        page = await browser.new_page()
        url = f"https://www.tiktok.com/@{username}"

        try:
            await page.goto(url, timeout=60000)

            # ✅ Instead of wait_for_selector → query_selector
            element = await page.query_selector('script[id="__UNIVERSAL_DATA_FOR_REHYDRATION__"]')
            if not element:
                return {"error": f"Could not find JSON script for {username}"}

            raw_json = await element.inner_text()

            try:
                data = json.loads(raw_json)
            except Exception as e:
                return {"error": f"Failed to parse TikTok JSON: {e}"}

            try:
                user_info = data["__DEFAULT_SCOPE__"]["webapp.user-detail"]["userInfo"]
                user = user_info["user"]
                stats = user_info["stats"]

                return {
                    "username": user.get("uniqueId"),
                    "nickname": user.get("nickname"),
                    "bio": user.get("signature"),
                    "followers": stats.get("followerCount"),
                    "following": stats.get("followingCount"),
                    "likes": stats.get("heartCount"),
                    "video_count": stats.get("videoCount"),
                    "verified": user.get("verified"),
                    "avatar": user.get("avatarLarger"),
                }
            except KeyError:
                return {"error": f"JSON structure changed, could not parse for {username}"}

        except Exception as e:
            logging.exception(f"TikTok scraping failed for {username}")
            return {"error": str(e)}

        finally:
            await browser.close()

"""



def scrape_tiktok_profile(username: str):
    """Sync wrapper for scraping TikTok profile data."""
    try:
        return asyncio.run(_fetch_tiktok_info(username))
    except Exception as e:
        logging.exception("Error scraping TikTok profile")
        return {"error": str(e)}


def unscrape_tiktok_profile(username: str):
    """Deletes TikTok-related social media records for the given username."""
    try:
        profile = Profile.objects.get(username=username, platform='TikTok')
        SocialMediaAccount.objects.filter(profile=profile, platform='TikTok').delete()
        profile.delete()
        return True
    except Profile.DoesNotExist:
        return False
