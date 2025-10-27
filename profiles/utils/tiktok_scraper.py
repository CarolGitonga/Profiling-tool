import logging
import os
import json
import re
from datetime import datetime, timezone as dt_timezone
from scrapingbee import ScrapingBeeClient
from django.conf import settings
from profiles.models import Profile, SocialMediaAccount

logger = logging.getLogger(__name__)
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))


def fetch_tiktok_info(username: str) -> dict:
    """Fetch TikTok user info and recent posts using ScrapingBeeClient."""

    if not SCRAPINGBEE_API_KEY:
        logger.error("SCRAPINGBEE_API_KEY missing in environment.")
        return {"error": "Missing API key"}

    target_url = f"https://www.tiktok.com/@{username}"
    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)

    try:
        # ✅ According to docs: prefer wait_browser='networkidle' and block_resources=True for faster loads
        response = client.get(
            target_url,
            params={
                "render_js": "true",
                "wait_browser": "networkidle",
                "block_resources": "true",
                "premium_proxy": "true",
                "stealth_proxy": "true",
                "device": "desktop",
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
        if response.status_code != 200:
            logger.warning(f"TikTok scrape returned {response.status_code} for {username}")
            return {"error": f"Bad HTTP status: {response.status_code}"}

    except Exception as e:
        logger.exception(f"ScrapingBee request failed for {username}")
        return {"error": f"ScrapingBee request failed: {e}"}

    # ✅ Extract JSON payload safely
    json_patterns = [
        r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>',
        r'<script id="SIGI_STATE"[^>]*>(.*?)</script>',
    ]
    match = None
    for pattern in json_patterns:
        match = re.search(pattern, html)
        if match:
            break

    if not match:
        logger.warning(f"No TikTok JSON script found for {username}")
        return {"error": "No JSON found"}

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        logger.exception(f"JSON decoding error for {username}: {e}")
        return {"error": f"Invalid JSON format: {e}"}

    # ✅ Unified extraction logic
    try:
        user_info = (
            data.get("__DEFAULT_SCOPE__", {})
            .get("webapp.user-detail", {})
            .get("userInfo", {})
        )
        user = user_info.get("user", {})
        stats = user_info.get("stats", {})

        # Fallback if "__DEFAULT_SCOPE__" missing
        if not user and "UserModule" in data:
            users = data["UserModule"].get("users", {})
            stats_module = data["UserModule"].get("stats", {})
            user = users.get(username, {})
            stats = stats_module.get(username, {})

        if not user:
            logger.warning(f"No TikTok user data found for {username}")
            return {"error": "User data missing"}

        # ✅ Extract posts
        posts = []
        items = data.get("ItemModule", {})
        for vid_id, vid in list(items.items())[:10]:
            stats_obj = vid.get("stats", {})
            ts = vid.get("createTime")
            timestamp = (
                datetime.fromtimestamp(int(ts), tz=dt_timezone.utc)
                if ts else datetime.now(dt_timezone.utc)
            )
            posts.append({
                "caption": vid.get("desc", "").strip(),
                "likes": int(stats_obj.get("diggCount", 0)),
                "comments": int(stats_obj.get("commentCount", 0)),
                "timestamp": timestamp,
            })

        return {
            "success": True,
            "username": user.get("uniqueId", "").strip(),
            "full_name": user.get("nickname", "").strip(),
            "bio": user.get("signature", "").strip(),
            "followers": int(stats.get("followerCount", 0)),
            "following": int(stats.get("followingCount", 0)),
            "likes": int(stats.get("heartCount", 0)),
            "posts": posts,
            "posts_count": len(posts),
            "is_private": user.get("privateAccount", False),
            "verified": user.get("verified", False),
            "avatar_url": user.get("avatarLarger") or user.get("avatarMedium") or user.get("avatarThumb") or "",
            "external_url": user.get("bioLink", {}).get("link", ""),
            "platform": "TikTok",
        }

    except Exception as e:
        logger.exception(f"Unexpected parsing error for {username}")
        return {"error": str(e)}


def scrape_tiktok_profile(username: str):
    """Fetch and persist TikTok profile + posts in DB."""
    result = fetch_tiktok_info(username)
    if not result.get("success"):
        return {"success": False, "reason": result.get("error")}

    try:
        profile, _ = Profile.objects.update_or_create(
            username=username,
            platform="TikTok",
            defaults={
                "full_name": result["full_name"],
                "avatar_url": result["avatar_url"],
            },
        )

        SocialMediaAccount.objects.update_or_create(
            profile=profile,
            platform="TikTok",
            defaults={
                "bio": result["bio"],
                "followers": result["followers"],
                "following": result["following"],
                "posts_collected": result["posts_count"],
                "is_private": result["is_private"],
                "external_url": result["external_url"],
                "verified": result["verified"],
            },
        )
        return result

    except Exception as e:
        logger.exception(f"DB update failed for {username}: {e}")
        return {"success": False, "reason": str(e)}


def unscrape_tiktok_profile(username: str) -> bool:
    """Delete TikTok-related social media records."""
    try:
        profile = Profile.objects.get(username=username, platform="TikTok")
        SocialMediaAccount.objects.filter(profile=profile, platform="TikTok").delete()
        profile.delete()
        return True
    except Profile.DoesNotExist:
        return False
