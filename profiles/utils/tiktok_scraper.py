import logging
import asyncio
import json
import re
from playwright.async_api import async_playwright
from profiles.models import Profile, SocialMediaAccount
from django.conf import settings

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
