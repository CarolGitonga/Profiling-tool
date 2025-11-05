import os
import json
import logging
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from scrapingbee import ScrapingBeeClient
from django.conf import settings
import time

logger = logging.getLogger(__name__)

# ==========================================================
# 🔧 CONFIGURATION
# ==========================================================
SCRAPINGBEE_API_KEY = os.getenv(
    "SCRAPINGBEE_API_KEY",
    getattr(settings, "SCRAPINGBEE_API_KEY", None)
)
BASE_TWITTER_URL = "https://twitter.com/{}"
REGIONS = ["US", "FR", "DE"]  # fallback sequence


# ==========================================================
# 🧩 HELPER — Initialize client
# ==========================================================
def _get_client() -> ScrapingBeeClient | None:
    if not SCRAPINGBEE_API_KEY:
        logger.error("Missing SCRAPINGBEE_API_KEY in environment.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)


# ==========================================================
# 🐦 PROFILE SCRAPING
# ==========================================================
def fetch_twitter_profile(username: str) -> dict:
    """
    Scrape Twitter profile metadata (name, bio, join date, avatar)
    using ScrapingBee's July 2024 approach.
    """
    client = _get_client()
    if not client:
        return {"error": "Missing API key"}

    target_url = BASE_TWITTER_URL.format(username)

    extract_rules = {
        "profile": {
            "name": "div[data-testid='UserName'] span::text",
            "bio": "div[data-testid='UserDescription']::text",
            "join_date": "div[data-testid='UserJoinDate'] time::attr(datetime)",
            "avatar": "img[alt*='Image']::attr(src)"
        }
    }

    for region in REGIONS:
        try:
            response = client.get(
                target_url,
                params={
                    "render_js": "true",
                    "scroll_page": "false",
                    "country_code": region,
                    "wait": "8000",
                    "extract_rules": json.dumps(extract_rules),
                },
            )

            if response.status_code != 200:
                logger.warning(f"❌ {region} region returned {response.status_code} for {username}")
                continue

            # Try JSON response
            try:
                data = json.loads(response.content.decode("utf-8"))
                profile_data = data.get("profile", {})
                profile_data["url"] = target_url
                profile_data["fetched_at"] = datetime.now(timezone.utc).isoformat()
                logger.info(f"✅ Profile scraped successfully for {username} ({region})")
                return profile_data
            except json.JSONDecodeError:
                logger.warning(f"⚠️ JSON decode failed for {username} ({region}), trying fallback parser")
                # BeautifulSoup fallback
                return _parse_profile_html(response.text, username)

        except Exception as e:
            logger.warning(f"❌ {region} region failed for {username}: {e}")
            time.sleep(2)

    return {"error": f"All ScrapingBee regions failed for {username}"}


def _parse_profile_html(html: str, username: str) -> dict:
    """Fallback parser if ScrapingBee doesn't return JSON."""
    soup = BeautifulSoup(html, "html.parser")
    profile = {}
    try:
        name_tag = soup.select_one("div[data-testid='UserName'] span")
        bio_tag = soup.select_one("div[data-testid='UserDescription']")
        join_tag = soup.select_one("div[data-testid='UserJoinDate'] time")
        avatar_tag = soup.select_one("img[alt*='Image']")

        profile["name"] = name_tag.get_text(strip=True) if name_tag else username
        profile["bio"] = bio_tag.get_text(strip=True) if bio_tag else ""
        profile["join_date"] = join_tag.get("datetime") if join_tag else None
        profile["avatar"] = avatar_tag.get("src") if avatar_tag else None
        profile["fetched_at"] = datetime.now(timezone.utc).isoformat()
        profile["url"] = BASE_TWITTER_URL.format(username)
        logger.info(f"🧩 Parsed profile HTML for {username}")
    except Exception as e:
        logger.error(f"Failed HTML parse for {username}: {e}")
    return profile


# ==========================================================
# 🧵 POSTS SCRAPING
# ==========================================================
def fetch_twitter_posts(username: str, limit: int = 10) -> list[dict]:
    """
    Scrape latest visible tweets (text, timestamp, likes, replies, retweets)
    with ScrapingBee + BeautifulSoup fallback.
    """
    client = _get_client()
    if not client:
        return [{"error": "Missing API key"}]

    target_url = BASE_TWITTER_URL.format(username)

    extract_rules = {
        "tweets": {
            "_items": "article[data-testid='tweet']",
            "text": "div[lang]::text",
            "timestamp": "time::attr(datetime)",
            "likes": "div[data-testid='like'] span::text",
            "replies": "div[data-testid='reply'] span::text",
            "retweets": "div[data-testid='retweet'] span::text",
        }
    }

    for region in REGIONS:
        try:
            response = client.get(
                target_url,
                params={
                    "render_js": "true",
                    "scroll_page": "true",
                    "country_code": region,
                    "wait": "8000",
                    "extract_rules": json.dumps(extract_rules),
                },
            )

            if response.status_code != 200:
                logger.warning(f"❌ {region} region failed ({response.status_code}) for tweets of {username}")
                continue

            try:
                data = json.loads(response.content.decode("utf-8"))
                tweets = data.get("tweets", [])[:limit]
                for t in tweets:
                    t["fetched_at"] = datetime.now(timezone.utc).isoformat()
                    t["source_url"] = target_url
                    t["platform"] = "Twitter"
                logger.info(f"✅ Collected {len(tweets)} tweets for {username} ({region})")
                return tweets
            except json.JSONDecodeError:
                logger.warning(f"⚠️ JSON decode failed for tweets of {username} ({region}), using HTML parser")
                return _parse_tweets_html(response.text, username, limit)

        except Exception as e:
            logger.warning(f"❌ {region} region failed for {username} tweets: {e}")
            time.sleep(2)

    return []


def _parse_tweets_html(html: str, username: str, limit: int) -> list[dict]:
    """Fallback BeautifulSoup parser for tweets."""
    soup = BeautifulSoup(html, "html.parser")
    tweets = []
    try:
        for article in soup.select("article[data-testid='tweet']")[:limit]:
            text = " ".join([n.get_text(strip=True) for n in article.select("div[lang]")])
            timestamp_tag = article.select_one("time")
            likes_tag = article.select_one("div[data-testid='like'] span")
            replies_tag = article.select_one("div[data-testid='reply'] span")
            retweets_tag = article.select_one("div[data-testid='retweet'] span")

            tweets.append({
                "text": text,
                "timestamp": timestamp_tag.get("datetime") if timestamp_tag else None,
                "likes": likes_tag.get_text(strip=True) if likes_tag else "0",
                "replies": replies_tag.get_text(strip=True) if replies_tag else "0",
                "retweets": retweets_tag.get_text(strip=True) if retweets_tag else "0",
                "platform": "Twitter",
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source_url": BASE_TWITTER_URL.format(username),
            })
        logger.info(f"🧩 Parsed {len(tweets)} tweets via fallback for {username}")
    except Exception as e:
        logger.error(f"Failed to parse tweets HTML for {username}: {e}")
    return tweets


# ==========================================================
# 🎯 ORCHESTRATOR
# ==========================================================
def scrape_twitter_profile(username: str) -> dict:
    """
    Orchestrator combining profile metadata + tweets.
    """
    logger.info(f"🚀 Starting Twitter scrape for {username}")
    profile_data = fetch_twitter_profile(username)
    tweets = fetch_twitter_posts(username)

    success = "error" not in profile_data
    result = {
        "success": success,
        "username": username,
        "platform": "Twitter",
        "profile": profile_data,
        "posts": tweets,
    }
    logger.info(f"✅ Finished Twitter scrape for {username} ({len(tweets)} tweets)")
    return result
