import os
import json
import logging
from datetime import datetime, timezone
from scrapingbee import ScrapingBeeClient
from django.conf import settings

__all__ = ["scrape_twitter_profile", "fetch_twitter_profile", "fetch_twitter_posts"]

logger = logging.getLogger(__name__)

# --- ScrapingBee setup ---
SCRAPINGBEE_API_KEY = os.getenv(
    "SCRAPINGBEE_API_KEY",
    getattr(settings, "SCRAPINGBEE_API_KEY", None)
)
BASE_TWITTER_URL = "https://twitter.com/{}"


def _get_client():
    """Initialize ScrapingBee client."""
    if not SCRAPINGBEE_API_KEY:
        logger.error("SCRAPINGBEE_API_KEY missing in environment or settings.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)


# ---------------------------------------------------------------------
# 1️⃣ FETCH PROFILE METADATA (aligned with docs)
# ---------------------------------------------------------------------
def fetch_twitter_profile(username: str) -> dict:
    """Fetch basic Twitter profile info with region fallback."""
    client = _get_client()
    if not client:
        return {"error": "Missing API key"}

    regions = ["US", "FR", "DE"]  # fallback countries
    for region in regions:
        target_url = BASE_TWITTER_URL.format(username)
        try:
            response = client.get(
                target_url,
                params={
                    # ✅ The official ScrapingBee syntax: stringified extract_rules
                    "extract_rules": json.dumps({
                        "username": "meta[property='og:title']::attr(content)",
                        "bio": "meta[property='og:description']::attr(content)",
                        "avatar_url": "meta[property='og:image']::attr(content)",
                    }),
                    "render_js": "true",
                    "country_code": region,
                    "wait": "5000",
                },
            )

            if response.status_code != 200:
                logger.warning(f"⚠️ {region} returned HTTP {response.status_code} for {username}")
                continue

            try:
                data = json.loads(response.content.decode("utf-8"))
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON for {username} ({region})")
                continue

            data["url"] = target_url
            data["region"] = region
            data["fetched_at"] = datetime.now(timezone.utc).isoformat()
            data["name"] = data.get("username", "").replace("(@", "").rstrip(")")
            logger.info(f"✅ Twitter profile fetched for {username} ({region})")
            return data

        except Exception as e:
            logger.warning(f"❌ {region} region failed for {username}: {e}")

    return {"error": f"All ScrapingBee regions failed for {username}"}


# ---------------------------------------------------------------------
# 2️⃣ FETCH RECENT POSTS
# ---------------------------------------------------------------------
def fetch_twitter_posts(username: str, limit: int = 10) -> list:
    """Fetch latest visible tweets for a given user."""
    client = _get_client()
    if not client:
        return [{"error": "Missing API key"}]

    regions = ["US", "FR", "DE"]
    for region in regions:
        target_url = BASE_TWITTER_URL.format(username)
        try:
            response = client.get(
                target_url,
                params={
                    "extract_rules": json.dumps({
                        "tweets": {
                            "_items": "article[data-testid='tweet']",
                            "text": "div[lang]::text",
                            "timestamp": "time::attr(datetime)",
                            "likes": "div[data-testid='like'] span::text",
                            "comments": "div[data-testid='reply'] span::text",
                        }
                    }),
                    "render_js": "true",
                    "country_code": region,
                    "wait": "7000",
                },
            )

            if response.status_code != 200:
                logger.warning(f"⚠️ {region} returned HTTP {response.status_code} for posts of {username}")
                continue

            try:
                tweets_data = json.loads(response.content.decode("utf-8"))
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in tweets for {username} ({region})")
                continue

            tweets = tweets_data.get("tweets", [])[:limit]
            for t in tweets:
                t["fetched_at"] = datetime.now(timezone.utc).isoformat()
                t["source_url"] = target_url
                t["platform"] = "Twitter"

            logger.info(f"✅ Collected {len(tweets)} tweets for {username} ({region})")
            return tweets

        except Exception as e:
            logger.warning(f"❌ {region} region failed for {username} tweets: {e}")

    return []


# ---------------------------------------------------------------------
# 3️⃣ ORCHESTRATOR
# ---------------------------------------------------------------------
def scrape_twitter_profile(username: str) -> dict:
    """Orchestrator — combines profile metadata + posts."""
    logger.info(f"🚀 Starting Twitter scrape for {username}")
    profile_data = fetch_twitter_profile(username)
    posts = fetch_twitter_posts(username)

    result = {
        "success": "error" not in profile_data,
        "username": username,
        "platform": "Twitter",
        "profile": profile_data,
        "posts": posts,
    }

    logger.info(f"✅ Completed Twitter scrape for {username} ({len(posts)} posts)")
    return result
