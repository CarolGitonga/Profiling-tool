import logging
import os
import json
import re
import requests
from django.conf import settings
from profiles.models import Profile, SocialMediaAccount

# ✅ Load ScrapingBee API key from environment
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))

def _fetch_tiktok_info(username: str):
    """
    Fetch TikTok user info using ScrapingBee API.
    Works on Render — no Playwright or Chromium required.
    """
    if not SCRAPINGBEE_API_KEY:
        return {"error": "Missing SCRAPINGBEE_API_KEY in environment variables."}

    url = f"https://www.tiktok.com/@{username}"

    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": url,
        "render_js": "true",        # Ensures JavaScript content is loaded
        "block_resources": "false", # Loads all data for better reliability
        "country_code": "us",       # Optional: can change to 'ke' for Kenya
    }

    try:
        response = requests.get("https://app.scrapingbee.com/api/v1/", params=params, timeout=60)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.exception(f"ScrapingBee request failed for {username}")
        return {"error": f"ScrapingBee request failed: {e}"}

    html = response.text

    # ✅ Extract embedded TikTok JSON
    match = re.search(
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__" type="application/json">(.*?)</script>',
        html
    )

    if not match:
        return {"error": f"Could not find TikTok JSON script for {username}"}

    try:
        raw_json = match.group(1)
        data = json.loads(raw_json)
    except Exception as e:
        return {"error": f"Failed to parse TikTok JSON: {e}"}

    # ✅ Extract relevant fields
    try:
        user_info = data.get("__DEFAULT_SCOPE__", {}).get("webapp.user-detail", {}).get("userInfo", {})
        user = user_info.get("user", {})
        stats = user_info.get("stats", {})

        if not user:
            return {"error": f"No user data found for {username}"}

        return {
            "username": user.get("uniqueId"),
            "nickname": user.get("nickname"),
            "bio": user.get("signature"),
            "followers": stats.get("followerCount"),
            "following": stats.get("followingCount"),
            "likes": stats.get("heartCount"),
            "posts_count": int(stats.get("videoCount") or 0),
            "verified": user.get("verified"),
            "avatar": user.get("avatarLarger"),
            "success": True,
        }

    except KeyError as e:
        return {"error": f"JSON structure changed: missing {e}"}
    except Exception as e:
        logging.exception(f"Unexpected error while parsing TikTok data for {username}")
        return {"error": str(e)}


def scrape_tiktok_profile(username: str):
    """
    Synchronous wrapper that fetches and optionally saves TikTok profile data.
    """
    try:
        result = _fetch_tiktok_info(username)

        if result.get("success"):
            profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
            profile.full_name = result.get("nickname")
            profile.bio = result.get("bio")
            profile.followers = result.get("followers")
            profile.following = result.get("following")
            profile.posts = result.get("video_count")
            profile.avatar_url = result.get("avatar")
            profile.save()

            # Also update SocialMediaAccount table if present
            SocialMediaAccount.objects.update_or_create(
                profile=profile,
                platform="TikTok",
                defaults={
                    "username": username,
                    "url": f"https://www.tiktok.com/@{username}",
                    "followers": result.get("followers"),
                },
            )

            return {"success": True, "username": username}

        else:
            return {"success": False, "reason": result.get("error")}

    except Exception as e:
        logging.exception(f"Error scraping TikTok profile for {username}")
        return {"success": False, "reason": str(e)}


def unscrape_tiktok_profile(username: str):
    """
    Deletes TikTok-related social media records for the given username.
    """
    try:
        profile = Profile.objects.get(username=username, platform="TikTok")
        SocialMediaAccount.objects.filter(profile=profile, platform="TikTok").delete()
        profile.delete()
        return True
    except Profile.DoesNotExist:
        return False
