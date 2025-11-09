import os
import re
import json
import random
import logging
from datetime import datetime, timezone as dt_timezone
from textblob import TextBlob
from bs4 import BeautifulSoup
from scrapingbee import ScrapingBeeClient
from django.utils import timezone
from django.conf import settings
from profiles.models import Profile, SocialMediaAccount, RawPost

logger = logging.getLogger(__name__)

# ============================================================
# 🧩 ScrapingBee client setup
# ============================================================
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))

def _get_client():
    if not SCRAPINGBEE_API_KEY:
        logger.error("❌ SCRAPINGBEE_API_KEY missing in environment.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)


# ============================================================
# 🧩 TikTok Scraper
# ============================================================
def scrape_tiktok_profile(username: str):
    """
    Scrape TikTok user info + posts using ScrapingBee and save results to DB.
    """
    client = _get_client()
    if not client:
        return {"error": "Missing API key"}

    tiktok_url = f"https://www.tiktok.com/@{username}"

    params = {
        "render_js": "true",
        "wait_browser": "networkidle",
        "block_resources": "true",
        "country_code": random.choice(["us", "fr", "de"]),
        "device": "desktop",
    }

    # --- Try ScrapingBee
    logger.info(f"🕵️ Trying ScrapingBee for TikTok user {username} ...")
    html = None
    try:
        resp = client.get(tiktok_url, params=params)
        if resp.status_code == 200 and "SIGI_STATE" in resp.text:
            html = resp.text
            logger.info(f"✅ ScrapingBee succeeded for {username}")
        else:
            logger.warning(f"⚠️ ScrapingBee returned {resp.status_code} for {username}")
    except Exception as e:
        logger.error(f"❌ ScrapingBee request failed for {username}: {e}")

    if not html:
        logger.error(f"❌ Could not retrieve HTML for {username}")
        return {"error": f"Failed to scrape {username}"}

    # ============================================================
    # 🧩 Extract JSON payload
    # ============================================================
    match = re.search(r'<script id="SIGI_STATE"[^>]*>(.*?)</script>', html)
    if not match:
        logger.warning(f"⚠️ No SIGI_STATE JSON block found for {username}")
        return {"error": "No TikTok JSON found"}

    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError as e:
        logger.error(f"❌ JSON decode error for {username}: {e}")
        return {"error": "Invalid TikTok JSON"}

    # ============================================================
    # 🧩 Extract Profile Information
    # ============================================================
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
            user = users.get(username, {})
            stats = stats_module.get(username, {})

        if not user:
            logger.warning(f"⚠️ No TikTok user data found for {username}")
            return {"error": "User data missing"}

        avatar = (
            user.get("avatarLarger")
            or user.get("avatarMedium")
            or user.get("avatarThumb")
            or ""
        )

        # ============================================================
        # 🧩 Extract Posts
        # ============================================================
        posts = []
        items = data.get("ItemModule", {})
        for vid_id, vid in list(items.items())[:20]:
            stats_obj = vid.get("stats", {})
            caption = vid.get("desc", "").strip()
            ts = vid.get("createTime")
            timestamp = (
                datetime.fromtimestamp(int(ts), tz=dt_timezone.utc)
                if ts else datetime.now(dt_timezone.utc)
            )
            polarity = round(TextBlob(caption).sentiment.polarity, 3)
            posts.append({
                "caption": caption,
                "likes": int(stats_obj.get("diggCount", 0)),
                "comments": int(stats_obj.get("commentCount", 0)),
                "timestamp": timestamp,
                "sentiment": polarity,
            })

        # ============================================================
        # 🧩 Save to Database
        # ============================================================
        profile, _ = Profile.objects.get_or_create(
            username=username,
            platform="TikTok",
            defaults={"full_name": user.get("nickname", ""), "avatar_url": avatar},
        )
        profile.avatar_url = avatar
        profile.save(update_fields=["avatar_url"])

        sm_account, _ = SocialMediaAccount.objects.get_or_create(profile=profile, platform="TikTok")
        sm_account.bio = user.get("signature", "")
        sm_account.followers = int(stats.get("followerCount", 0))
        sm_account.following = int(stats.get("followingCount", 0))
        sm_account.posts_collected = len(posts)
        sm_account.external_url = user.get("bioLink", {}).get("link", "")
        sm_account.is_private = user.get("privateAccount", False)
        sm_account.verified = user.get("verified", False)
        sm_account.save()

        # --- Save posts
        saved_count = 0
        for post in posts:
            if not RawPost.objects.filter(
                profile=profile,
                platform="TikTok",
                content__icontains=post["caption"][:50]
            ).exists():
                RawPost.objects.create(
                    profile=profile,
                    platform="TikTok",
                    content=post["caption"],
                    timestamp=post["timestamp"],
                    sentiment_score=post["sentiment"],
                )
                saved_count += 1

        total_posts = RawPost.objects.filter(profile=profile, platform="TikTok").count()
        profile.posts_count = total_posts
        sm_account.posts_collected = total_posts
        profile.save(update_fields=["posts_count"])
        sm_account.save(update_fields=["posts_collected"])

        logger.info(f"💾 {username}: saved {saved_count}/{len(posts)} TikToks successfully.")

        # ============================================================
        # 🧩 Return Summary
        # ============================================================
        return {
            "success": True,
            "username": username,
            "full_name": user.get("nickname", ""),
            "bio": user.get("signature", ""),
            "followers": sm_account.followers,
            "following": sm_account.following,
            "avatar_url": avatar,
            "posts_saved": saved_count,
            "posts_total": len(posts),
            "verified": sm_account.verified,
            "is_private": sm_account.is_private,
            "platform": "TikTok",
        }

    except Exception as e:
        logger.exception(f"❌ Unexpected error parsing TikTok profile {username}: {e}")
        return {"error": str(e)}


# ============================================================
# 🧩 Un-Scrape Function
# ============================================================
def unscrape_tiktok_profile(username: str) -> bool:
    """Delete TikTok-related social media records."""
    try:
        profile = Profile.objects.get(username=username, platform="TikTok")
        SocialMediaAccount.objects.filter(profile=profile, platform="TikTok").delete()
        RawPost.objects.filter(profile=profile, platform="TikTok").delete()
        profile.delete()
        logger.info(f"🗑️ Deleted TikTok profile {username}")
        return True
    except Profile.DoesNotExist:
        return False
