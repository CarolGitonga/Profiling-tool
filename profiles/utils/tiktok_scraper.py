import os
import re
import json
import random
import logging
from datetime import datetime, timezone as dt_timezone
from textblob import TextBlob
from scrapingbee import ScrapingBeeClient
from bs4 import BeautifulSoup
from django.utils import timezone
from django.conf import settings
from profiles.models import Profile, SocialMediaAccount, RawPost

logger = logging.getLogger(__name__)

# ============================================================
# 🔑 API Setup
# ============================================================
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))

def _get_client():
    if not SCRAPINGBEE_API_KEY:
        logger.error("❌ SCRAPINGBEE_API_KEY missing in environment.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)

# 🌍 Backup TikTok mirrors (sometimes load faster)
TIKTOK_MIRRORS = [
    "https://www.tiktok.com/@{}",
    "https://m.tiktok.com/@{}",
    "https://www.tiktok.com/embed/@{}",
]


# ============================================================
# 🧩 Core Scraper Logic
# ============================================================
def _fetch_tiktok_html(client, username):
    """Try fetching TikTok HTML using multi-region ScrapingBee and mirrors."""
    REGIONS = ["us", "de", "fr", "gb", "ca"]
    html = None
    source_used = None

    for mirror in TIKTOK_MIRRORS:
        url = mirror.format(username)
        for region in random.sample(REGIONS, len(REGIONS)):
            try:
                logger.info(f"🌐 Trying TikTok mirror={mirror} region={region} for {username} ...")

                resp = client.get(
                    url,
                    params={
                        "render_js": "true",
                        "wait_browser": "networkidle",
                        "block_resources": "true",
                        "country_code": region,
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

                if resp.status_code == 200 and "SIGI_STATE" in resp.text:
                    html = resp.text
                    source_used = f"{mirror} ({region})"
                    logger.info(f"✅ TikTok HTML fetched successfully for {username} from {source_used}")
                    return html, source_used
                else:
                    logger.warning(f"⚠️ {username}: HTTP {resp.status_code} or SIGI_STATE missing (region={region})")

            except Exception as e:
                logger.warning(f"❌ {username}: failed for region {region} -> {e}")
                continue

    logger.error(f"🚨 All TikTok mirrors and regions failed for {username}")
    return None, None


# ============================================================
# 🧩 Main Scraper
# ============================================================
def scrape_tiktok_profile(username: str):
    """
    Scrape TikTok user info and recent posts using multi-region ScrapingBee fallback.
    """
    client = _get_client()
    if not client:
        return {"error": "Missing API key"}

    html, source_used = _fetch_tiktok_html(client, username)
    if not html:
        return {"error": f"Failed to scrape TikTok for {username}"}

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
        # 💾 Save to Database
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

        logger.info(f"💾 {username}: saved {saved_count}/{len(posts)} TikToks from {source_used}")

        # ============================================================
        # 🧾 Return Summary
        # ============================================================
        return {
            "success": True,
            "source": source_used,
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
# 🧩 Clean-up
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
