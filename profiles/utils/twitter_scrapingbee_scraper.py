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
            },
            extract_rules=extract_rules,  # ✅ pass dict here, not JSON string
        )

        if response.status_code != 200:
            logger.error(f"Twitter scrape returned {response.status_code} for {username}")
            return {"error": f"Bad HTTP status: {response.status_code}"}

        data = json.loads(response.content.decode("utf-8"))
        data["fetched_at"] = datetime.now(timezone.utc).isoformat()
        data["url"] = target_url
        return data

    except Exception as e:
        logger.exception(f"Twitter scraping failed for {username}: {e}")
        return {"error": str(e)}


def fetch_twitter_posts(username: str, limit: int = 10) -> list:
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
            },
            extract_rules=extract_rules,  # ✅ proper dict, not json.dumps()
        )

        if response.status_code != 200:
            logger.warning(f"Twitter post scrape failed with {response.status_code} for {username}")
            return []

        tweets_data = json.loads(response.content.decode("utf-8"))
        tweets = tweets_data.get("tweets", [])[:limit]
        for t in tweets:
            t["fetched_at"] = datetime.now(timezone.utc).isoformat()
            t["source_url"] = target_url

        logger.info(f"✅ Fetched {len(tweets)} tweets for {username}")
        return tweets

    except Exception as e:
        logger.exception(f"Twitter post scrape failed for {username}: {e}")
        return []
