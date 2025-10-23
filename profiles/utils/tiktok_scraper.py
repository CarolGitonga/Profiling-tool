import logging
import os
import json
import re
from datetime import datetime, timezone as dt_timezone
from scrapingbee import ScrapingBeeClient
from django.conf import settings
from profiles.models import Profile, SocialMediaAccount

logger = logging.getLogger(__name__)

# ✅ Load API key from environment or settings
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))


def _fetch_tiktok_info(username: str):
    """
    Fetch TikTok user info + recent posts using ScrapingBeeClient.
    Works safely on Render.
    """
    if not SCRAPINGBEE_API_KEY:
        return {"error": "Missing SCRAPINGBEE_API_KEY in environment variables."}

    target_url = f"https://www.tiktok.com/@{username}"
    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)

    try:
        response = client.get(
            target_url,
            params={
                "render_js": "true",
                "block_resources": "false",
                "country_code": "us",
                "wait": "4000"
            },
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        html = response.text
    except Exception as e:
        logger.exception(f"ScrapingBee request failed for {username}")
        return {"error": f"ScrapingBee request failed: {e}"}

    # ✅ Extract embedded JSON
    match = re.search(r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html)
    if not match:
        match = re.search(r'<script id="SIGI_STATE"[^>]*>(.*?)</script>', html)

    if not match:
        logger.warning(f"No TikTok JSON script found for {username}")
        return {"error": f"No TikTok JSON found for {username}"}

    try:
        raw_json = match.group(1)
        data = json.loads(raw_json)
    except Exception as e:
        logger.exception(f"Failed to parse TikTok JSON for {username}")
        return {"error": f"Failed to parse TikTok JSON: {e}"}

    # ✅ Extract user info
    try:
        user_info = (
            data.get("__DEFAULT_SCOPE__", {})
            .get("webapp.user-detail", {})
            .get("userInfo", {})
        )
        user = user_info.get("user", {})
        stats = user_info.get("stats", {})

        # Fallback structure
        if not user and "UserModule" in data:
            users = data["UserModule"].get("users", {})
            stats_module = data["UserModule"].get("stats", {})
            if username in users:
                user = users[username]
                stats = stats_module.get(username, {})

        if not user:
            return {"error": f"No user data found for {username}"}

        # ✅ Extract posts (videos)
        posts_data = []
        if "ItemModule" in data:
            for vid_id, vid in list(data["ItemModule"].items())[:10]:  # limit to 10
                caption = vid.get("desc", "").strip()
                stats_obj = vid.get("stats", {})
                likes = int(stats_obj.get("diggCount") or 0)
                comments = int(stats_obj.get("commentCount") or 0)
                ts = vid.get("createTime")
                try:
                    timestamp = datetime.fromtimestamp(int(ts), tz=dt_timezone.utc) if ts else datetime.now(dt_timezone.utc)
                except Exception:
                    timestamp = datetime.now(dt_timezone.utc)
                posts_data.append({
                    "caption": caption,
                    "likes": likes,
                    "comments": comments,
                    "timestamp": timestamp,
                })

        return {
            "success": True,
            "username": user.get("uniqueId", "").strip(),
            "full_name": user.get("nickname", "").strip(),
            "bio": user.get("signature", "").strip(),
            "followers": int(stats.get("followerCount") or 0),
            "following": int(stats.get("followingCount") or 0),
            "likes": int(stats.get("heartCount") or 0),
            "posts": posts_data,  # ✅ new
            "posts_count": len(posts_data),
            "is_private": bool(user.get("privateAccount", False)),
            "verified": bool(user.get("verified", False)),
            "avatar_url": (
                user.get("avatarLarger")
                or user.get("avatarMedium")
                or user.get("avatarThumb")
                or ""
            ),
            "external_url": user.get("bioLink", {}).get("link", ""),
            "platform": "TikTok",
        }

    except Exception as e:
        logger.exception(f"Unexpected error parsing TikTok data for {username}")
        return {"error": str(e)}


def scrape_tiktok_profile(username: str):
    """
    Wrapper: fetches and saves TikTok user + posts into DB.
    """
    try:
        result = _fetch_tiktok_info(username)

        if result.get("success"):
            profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
            profile.full_name = result.get("full_name")
            profile.avatar_url = result.get("avatar_url")
            profile.save()

            SocialMediaAccount.objects.update_or_create(
                profile=profile,
                platform="TikTok",
                defaults={
                    "bio": result.get("bio", ""),
                    "followers": result.get("followers", 0),
                    "following": result.get("following", 0),
                    "posts_collected": result.get("posts_count", 0),
                    "is_private": result.get("is_private", False),
                    "external_url": result.get("external_url"),
                    "verified": result.get("verified", False),
                },
            )

            return result  # ✅ includes post data now

        else:
            return {"success": False, "reason": result.get("error")}

    except Exception as e:
        logger.exception(f"Error scraping TikTok profile for {username}")
        return {"success": False, "reason": str(e)}


def unscrape_tiktok_profile(username: str):
    """Delete TikTok-related social media records."""
    try:
        profile = Profile.objects.get(username=username, platform="TikTok")
        SocialMediaAccount.objects.filter(profile=profile, platform="TikTok").delete()
        profile.delete()
        return True
    except Profile.DoesNotExist:
        return False
