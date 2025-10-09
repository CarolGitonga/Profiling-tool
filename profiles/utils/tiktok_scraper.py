import logging
import os
import json
import re
import requests
from django.conf import settings
from profiles.models import Profile, SocialMediaAccount

SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))


def _fetch_tiktok_info(username: str):
    """
    Fetch TikTok user info using ScrapingBee API (2025-compliant version).
    Fixes BAD REQUEST errors and handles new TikTok page structure.
    """
    if not SCRAPINGBEE_API_KEY:
        return {"error": "Missing SCRAPINGBEE_API_KEY in environment variables."}

    url = f"https://www.tiktok.com/@{username}"
    api_url = "https://app.scrapingbee.com/api/v1/"

    # ✅ Compose parameters (NO bracketed headers)
    params = {
        "api_key": SCRAPINGBEE_API_KEY,
        "url": url,
        "render_js": "true",
        "block_resources": "false",
        "country_code": "us",
        # send custom headers as raw JSON string
        "custom_headers": json.dumps({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        })
    }

    try:
        response = requests.get(api_url, params=params, timeout=60)
        response.raise_for_status()
    except requests.RequestException as e:
        logging.exception(f"ScrapingBee request failed for {username}")
        return {"error": f"ScrapingBee request failed: {e}"}

    html = response.text

    # ✅ Extract embedded JSON (support both formats)
    match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html)
    if not match:
        match = re.search(r'<script id="SIGI_STATE"[^>]*>(.*?)</script>', html)

    if not match:
        return {"error": f"Could not find TikTok JSON script for {username}"}

    try:
        raw_json = match.group(1)
        data = json.loads(raw_json)
    except Exception as e:
        logging.exception(f"Failed to parse TikTok JSON for {username}")
        return {"error": f"Failed to parse TikTok JSON: {e}"}

    # ✅ Handle both old and new TikTok structures
    try:
        user_info = (
            data.get("__DEFAULT_SCOPE__", {})
            .get("webapp.user-detail", {})
            .get("userInfo", {})
        )
        user = user_info.get("user", {})
        stats = user_info.get("stats", {})

        if not user and "UserModule" in data:
            users = data["UserModule"].get("users", {})
            stats_module = data["UserModule"].get("stats", {})
            if username in users:
                user = users[username]
                stats = stats_module.get(username, {})

        if not user:
            return {"error": f"No user data found for {username}"}

        return {
            "username": user.get("uniqueId", "").strip(),
            "nickname": user.get("nickname", "").strip(),
            "bio": user.get("signature", "").strip(),
            "followers": int(stats.get("followerCount") or 0),
            "following": int(stats.get("followingCount") or 0),
            "likes": int(stats.get("heartCount") or 0),
            "posts_count": int(stats.get("videoCount") or 0),
            "verified": bool(user.get("verified", False)),
            "avatar": (
                user.get("avatarLarger")
                or user.get("avatarMedium")
                or user.get("avatarThumb")
                or ""
            ),
            "platform": "TikTok",
            "success": True,
        }

    except Exception as e:
        logging.exception(f"Unexpected error parsing TikTok data for {username}")
        return {"error": str(e)}





def scrape_tiktok_profile(username: str):
    """
    Synchronous wrapper that fetches and saves TikTok profile data.
    """
    try:
        result = _fetch_tiktok_info(username)

        if result.get("success"):
            profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
            profile.full_name = result.get("nickname")
            profile.bio = result.get("bio")
            profile.followers = result.get("followers")
            profile.following = result.get("following")
            profile.posts_count = result.get("posts_count") or 0
            profile.avatar_url = result.get("avatar")
            profile.save()

            # Also update SocialMediaAccount table if present
            SocialMediaAccount.objects.update_or_create(
                profile=profile,
                platform="TikTok",
                defaults={
                    "bio": result.get("bio", ""),
                    "followers": result.get("followers", 0),
                    "following": result.get("following", 0),
                    "hearts": result.get("likes", 0),
                    "videos": result.get("posts_count", 0),
                    "verified": result.get("verified", False),
                    "posts_collected": 0,
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
