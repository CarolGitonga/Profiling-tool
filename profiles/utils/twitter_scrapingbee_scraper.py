import os
import json
import logging
from datetime import datetime, timezone
from scrapingbee import ScrapingBeeClient
from bs4 import BeautifulSoup
from django.conf import settings

logger = logging.getLogger(__name__)

# --- API Setup ---
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))
BASE_TWITTER_URL = "https://twitter.com/{}"


def _get_client():
    """Initialize ScrapingBee client."""
    if not SCRAPINGBEE_API_KEY:
        logger.error("❌ SCRAPINGBEE_API_KEY missing from environment or settings.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)


# ---------------------------------------------------------------------
# 🧩 1️⃣ FETCH PROFILE METADATA
# ---------------------------------------------------------------------
def fetch_twitter_profile(username: str) -> dict:
    """
    Fetch basic Twitter profile info using ScrapingBee, with fallback.
    Returns a dict with name, bio, followers, avatar, etc.
    """
    client = _get_client()
    if not client:
        return {"error": "Missing API key"}

    url = BASE_TWITTER_URL.format(username)
    regions = ["US", "FR", "DE"]

    # Extraction rules as per ScrapingBee docs
    extract_rules = {
        "name": "div[data-testid='UserName'] span::text",
        "handle": "div[data-testid='UserName'] div span::text",
        "bio": "div[data-testid='UserDescription']::text",
        "join_date": "span[data-testid='UserJoinDate']::text",
        "followers": {"selector": "a[href$='/followers'] span::text"},
        "following": {"selector": "a[href$='/following'] span::text"},
        "avatar": "img[alt*='Image']::attr(src)"
    }

    for region in regions:
        try:
            response = client.get(
                url,
                params={
                    "render_js": "true",
                    "country_code": region,
                    "wait": "7000",
                    "scroll_page": "false",
                },
                extract_rules=extract_rules,  # ✅ proper placement
            )

            if response.status_code != 200:
                logger.warning(f"⚠️ {region} returned HTTP {response.status_code} for {username}")
                continue

            try:
                data = json.loads(response.content.decode("utf-8"))
                data["url"] = url
                data["fetched_at"] = datetime.now(timezone.utc).isoformat()
                logger.info(f"✅ Profile scraped successfully for {username} ({region})")
                return data

            except json.JSONDecodeError:
                # Fallback: parse manually using BeautifulSoup
                logger.warning(f"⚠️ JSON decode failed for {username} ({region}), trying fallback parser")
                return _fallback_parse_profile(response.text, username)

        except Exception as e:
            logger.warning(f"❌ {region} region failed for {username}: {e}")
            continue

    return {"error": f"All ScrapingBee regions failed for {username}"}


def _fallback_parse_profile(html: str, username: str) -> dict:
    """Fallback parser for profile info when ScrapingBee doesn’t return valid JSON."""
    soup = BeautifulSoup(html, "html.parser")
    name_el = soup.select_one("div[data-testid='UserName'] span")
    bio_el = soup.select_one("div[data-testid='UserDescription']")
    avatar_el = soup.select_one("img[alt*='Image']")
    followers_el = soup.select_one("a[href$='/followers'] span")
    following_el = soup.select_one("a[href$='/following'] span")

    return {
        "name": name_el.text.strip() if name_el else "",
        "bio": bio_el.text.strip() if bio_el else "",
        "avatar": avatar_el["src"] if avatar_el and avatar_el.has_attr("src") else "",
        "followers": followers_el.text.strip() if followers_el else "",
        "following": following_el.text.strip() if following_el else "",
        "url": BASE_TWITTER_URL.format(username),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "parsed_with": "BeautifulSoup",
    }


# ---------------------------------------------------------------------
# 🧩 2️⃣ FETCH RECENT POSTS
# ---------------------------------------------------------------------
def fetch_twitter_posts(username: str, limit: int = 10) -> dict:
    """
    Fetch recent tweets using ScrapingBee, with fallback.
    Returns a list of tweet dictionaries.
    """
    client = _get_client()
    if not client:
        return {"tweets": [], "error": "Missing API key"}

    url = BASE_TWITTER_URL.format(username)
    regions = ["US", "FR", "DE"]

    extract_rules = {
        "tweets": {
            "_items": "article[data-testid='tweet']",
            "text": "div[data-testid='tweetText']::text",
            "timestamp": "time::attr(datetime)",
            "likes": "div[data-testid='like'] span::text",
            "replies": "div[data-testid='reply'] span::text",
            "retweets": "div[data-testid='retweet'] span::text",
        }
    }

    for region in regions:
        try:
            response = client.get(
                url,
                params={
                    "render_js": "true",
                    "country_code": region,
                    "wait": "8000",
                    "scroll_page": "true",
                },
                extract_rules=extract_rules,
            )

            if response.status_code != 200:
                logger.warning(f"⚠️ {region} returned HTTP {response.status_code} for {username} tweets")
                continue

            try:
                data = json.loads(response.content.decode("utf-8"))
                tweets = data.get("tweets", [])[:limit]
                for t in tweets:
                    t["source_url"] = url
                    t["fetched_at"] = datetime.now(timezone.utc).isoformat()
                logger.info(f"✅ Collected {len(tweets)} tweets for {username} ({region})")
                return {"tweets": tweets}

            except json.JSONDecodeError:
                logger.warning(f"⚠️ JSON decode failed for {username} ({region}), trying fallback parser")
                return _fallback_parse_tweets(response.text, username, limit)

        except Exception as e:
            logger.warning(f"❌ {region} region failed for {username} tweets: {e}")
            continue

    return {"tweets": [], "error": f"All ScrapingBee regions failed for {username} tweets"}


def _fallback_parse_tweets(html: str, username: str, limit: int) -> dict:
    """Fallback parser for tweets using BeautifulSoup."""
    soup = BeautifulSoup(html, "html.parser")
    tweets = []
    for article in soup.select("article[data-testid='tweet']")[:limit]:
        text_el = article.select_one("div[data-testid='tweetText']")
        time_el = article.select_one("time")
        likes_el = article.select_one("div[data-testid='like'] span")
        replies_el = article.select_one("div[data-testid='reply'] span")
        retweets_el = article.select_one("div[data-testid='retweet'] span")

        tweets.append({
            "text": text_el.text.strip() if text_el else "",
            "timestamp": time_el["datetime"] if time_el and time_el.has_attr("datetime") else "",
            "likes": likes_el.text.strip() if likes_el else "0",
            "replies": replies_el.text.strip() if replies_el else "0",
            "retweets": retweets_el.text.strip() if retweets_el else "0",
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "source_url": BASE_TWITTER_URL.format(username),
            "parsed_with": "BeautifulSoup",
        })
    logger.info(f"🧩 Parsed {len(tweets)} tweets via fallback for {username}")
    return {"tweets": tweets}


# ---------------------------------------------------------------------
# 🧩 3️⃣ ORCHESTRATOR
# ---------------------------------------------------------------------
def scrape_twitter_profile(username: str) -> dict:
    """Combine profile metadata + recent tweets."""
    logger.info(f"🚀 Starting Twitter scrape for {username}")

    profile_data = fetch_twitter_profile(username)
    posts_data = fetch_twitter_posts(username)

    if "error" in profile_data:
        logger.warning(f"⚠️ Profile scrape returned error for {username}: {profile_data['error']}")

    result = {
        "success": "error" not in profile_data,
        "username": username,
        "platform": "Twitter",
        "profile": profile_data,
        "posts": posts_data.get("tweets", []),
    }

    logger.info(f"✅ Finished Twitter scrape for {username} ({len(result['posts'])} tweets)")
    return result
