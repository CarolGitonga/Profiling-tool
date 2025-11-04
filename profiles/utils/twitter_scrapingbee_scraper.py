import os
import json
import logging
from datetime import datetime, timezone
from scrapingbee import ScrapingBeeClient
from django.conf import settings

logger = logging.getLogger(__name__)

# Load API key safely
SCRAPINGBEE_API_KEY = os.getenv(
    "SCRAPINGBEE_API_KEY",
    getattr(settings, "SCRAPINGBEE_API_KEY", None)
)

BASE_TWITTER_URL = "https://twitter.com/{}"


def _get_scrapingbee_client():
    """Return initialized ScrapingBeeClient or log error."""
    if not SCRAPINGBEE_API_KEY:
        logger.error("SCRAPINGBEE_API_KEY missing in environment or settings.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)


def fetch_twitter_profile(username: str) -> dict:
    """
    Fetch Twitter profile metadata (name, bio, avatar, etc.)
    using ScrapingBee's JS rendering.
    """
    client = _get_scrapingbee_client()
    if not client:
        return {"error": "Missing API key"}

    target_url = BASE_TWITTER_URL.format(username)
    extract_rules = {
        "username": "meta[property='og:title']::attr(content)",
        "bio": "meta[property='og:description']::attr(content)",
        "avatar_url": "meta[property='og:image']::attr(content)"
    }

    try:
        response = client.get(
            target_url,
            params={
                "render_js": "true",
                "country_code": "US",
                "wait": "5000",
                "block_resources": "false",
                "extract_rules": json.dumps(extract_rules)
            },
        )

        if response.status_code != 200:
            logger.error(f"Twitter scrape returned {response.status_code} for {username}")
            return {"error": f"Bad HTTP status: {response.status_code}"}

        try:
            data = json.loads(response.content.decode("utf-8"))
        except json.JSONDecodeError:
            logger.warning(f"Unable to parse JSON response for {username}")
            return {"error": "Invalid JSON returned by ScrapingBee"}

        # Normalize fields
        data["fetched_at"] = datetime.now(timezone.utc).isoformat()
        data["url"] = target_url
        data["name"] = data.get("username", "").replace("(@", "").rstrip(")")
        return data

    except Exception as e:
        logger.exception(f"Twitter profile scraping failed for {username}: {e}")
        return {"error": str(e)}


def fetch_twitter_posts(username: str, limit: int = 10) -> list:
    """
    Fetch a user's latest visible tweets using ScrapingBee JS rendering.
    Returns a list of dicts with text + timestamp.
    """
    client = _get_scrapingbee_client()
    if not client:
        return [{"error": "Missing API key"}]

    target_url = BASE_TWITTER_URL.format(username)
    extract_rules = {
        "tweets": {
            "_items": "article[data-testid='tweet']",
            "text": "div[lang]::text",
            "timestamp": "time::attr(datetime)",
            "likes": "div[data-testid='like'] span::text",
            "comments": "div[data-testid='reply'] span::text"
        }
    }

    try:
        response = client.get(
            target_url,
            params={
                "render_js": "true",
                "country_code": "US",
                "wait": "7000",
                "extract_rules": json.dumps(extract_rules),
            },
        )

        if response.status_code != 200:
            logger.warning(f"Twitter post scrape failed with {response.status_code} for {username}")
            return []

        try:
            tweets_data = json.loads(response.content.decode("utf-8"))
        except json.JSONDecodeError:
            logger.error(f"Could not parse tweets JSON for {username}")
            return []

        tweets = tweets_data.get("tweets", [])[:limit]
        for t in tweets:
            t["fetched_at"] = datetime.now(timezone.utc).isoformat()
            t["source_url"] = target_url
            t["platform"] = "Twitter"

        logger.info(f"✅ Fetched {len(tweets)} tweets for {username}")
        return tweets

    except Exception as e:
        logger.exception(f"Twitter post scrape failed for {username}: {e}")
        return []


def scrape_twitter_profile(username: str) -> dict:
    """
    Orchestrator — combines profile metadata + recent tweets
    into one unified response for the Celery task to persist.
    """
    logger.info(f"Starting Twitter scrape for {username}")
    profile_data = fetch_twitter_profile(username)
    posts = fetch_twitter_posts(username)

    if "error" in profile_data:
        logger.warning(f"Profile scrape returned error for {username}: {profile_data['error']}")

    result = {
        "success": "error" not in profile_data,
        "username": username,
        "platform": "Twitter",
        "profile": profile_data,
        "posts": posts,
    }

    logger.info(f"✅ Completed Twitter scrape for {username} ({len(posts)} posts)")
    return result
