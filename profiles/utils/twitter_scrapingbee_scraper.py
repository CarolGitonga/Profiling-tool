import os
import json
import logging
from datetime import datetime, timezone
from scrapingbee import ScrapingBeeClient
from django.conf import settings

logger = logging.getLogger(__name__)

# Retrieve ScrapingBee API key from environment
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))
BASE_TWITTER_URL = "https://twitter.com/{}"

def fetch_twitter_profile(username: str) -> dict:
    """
    Fetch a Twitter user's public profile data using ScrapingBee.
    Returns a dict with name, bio, followers, following, etc.
    """

    if not SCRAPINGBEE_API_KEY:
        logger.error("SCRAPINGBEE_API_KEY missing in environment.")
        return {"error": "Missing API key"}

    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)
    target_url = BASE_TWITTER_URL.format(username)

    try:
        response = client.get(
            target_url,
            params={
                "render_js": "true",
                "country_code": "US",
                "wait": "3000",  # wait for JS content
                "block_resources": "false",
                "extract_rules": json.dumps({
                    "username": "meta[property='og:title']::attr(content)",
                    "description": "meta[property='og:description']::attr(content)",
                    "profile_image": "meta[property='og:image']::attr(content)"
                }),
            },
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


def fetch_twitter_posts(username: str, limit: int = 5) -> list:
    """
    Fetch recent tweets for a given user (public profile).
    Returns a list of tweet dicts.
    """

    if not SCRAPINGBEE_API_KEY:
        return [{"error": "Missing API key"}]

    client = ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)
    target_url = BASE_TWITTER_URL.format(username)

    try:
        response = client.get(
            target_url,
            params={
                "render_js": "true",
                "country_code": "US",
                "wait": "5000",
                "extract_rules": json.dumps({
                    "tweets": {
                        "_items": "article div[lang]",
                        "text": "div[lang]::text",
                        "timestamp": "time::attr(datetime)"
                    }
                }),
            },
        )

        if response.status_code != 200:
            logger.warning(f"Twitter post scrape failed with {response.status_code} for {username}")
            return []

        tweets_data = json.loads(response.content.decode("utf-8"))
        tweets = tweets_data.get("tweets", [])[:limit]
        for t in tweets:
            t["fetched_at"] = datetime.now(timezone.utc).isoformat()
            t["source_url"] = target_url

        return tweets

    except Exception as e:
        logger.exception(f"Twitter post scrape failed for {username}: {e}")
        return []


def scrape_twitter_profile(username: str):
    """
    Orchestrator — combines profile info + posts.
    """
    profile_data = fetch_twitter_profile(username)
    posts = fetch_twitter_posts(username)

    return {
        "profile": profile_data,
        "recent_posts": posts,
    }
