import os
import random
import logging
from scrapingbee import ScrapingBeeClient
from bs4 import BeautifulSoup
from django.utils import timezone
from textblob import TextBlob
from profiles.models import Profile, RawPost

logger = logging.getLogger(__name__)

# --- Fallback Nitter mirrors (fastest first) ---
NITTER_MIRRORS = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.lucabased.xyz",
]


def scrape_twitter_profile(username: str):
    """
    Scrape Twitter profile using ScrapingBee with Nitter fallback.
    Performs sentiment analysis and saves posts in RawPost.
    """

    api_key = os.getenv("SCRAPINGBEE_API_KEY")
    if not api_key:
        logger.error("❌ Missing SCRAPINGBEE_API_KEY in environment.")
        return {"error": "Missing API key"}

    client = ScrapingBeeClient(api_key=api_key)
    twitter_url = f"https://mobile.twitter.com/{username}"
    html = None

    params = {
        "render_js": "true",
        "stealth_proxy": "true",
        "premium_proxy": "true",
        "country_code": random.choice(["us", "de", "fr"]),
        "wait_browser": "10000",
    }

    logger.info(f"🕵️ Trying ScrapingBee for Twitter user: {username}")

    try:
        resp = client.get(twitter_url, params=params)
        if resp.status_code == 200 and b"data-testid" in resp.content:
            html = resp.content.decode("utf-8", errors="ignore")
            logger.info(f"✅ ScrapingBee succeeded for {username}")
        else:
            logger.warning(f"⚠️ ScrapingBee returned {resp.status_code} for {username}")
    except Exception as e:
        logger.error(f"❌ ScrapingBee request failed for {username}: {e}")

    # --- Fallback to Nitter mirrors if Twitter blocks JS render ---
    if not html:
        logger.warning(f"⚠️ Falling back to Nitter for {username}")
        random.shuffle(NITTER_MIRRORS)
        for mirror in NITTER_MIRRORS:
            try:
                nitter_url = f"{mirror}/{username}"
                r = client.get(nitter_url)
                if r.status_code == 200:
                    html = r.content.decode("utf-8", errors="ignore")
                    logger.info(f"✅ Using Nitter mirror: {mirror}")
                    break
            except Exception as e:
                logger.warning(f"⚠️ Failed Nitter mirror {mirror}: {e}")
                continue

    if not html:
        logger.error(f"❌ All Nitter mirrors failed for {username}")
        return {"error": f"All sources failed for {username}"}

    # --- Parse tweets from HTML ---
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title else username

    # Twitter uses 'div[data-testid="tweetText"]' — Nitter uses 'div.tweet-content'
    tweet_selectors = [
        "div[data-testid='tweetText']",
        "div.tweet-content",
    ]
    tweets = []
    for selector in tweet_selectors:
        elements = soup.select(selector)
        if elements:
            tweets = [div.get_text(" ", strip=True) for div in elements]
            break

    if not tweets:
        logger.warning(f"⚠️ No tweets found for {username}")
        return {"error": "No tweets found"}

    # --- Get or create Profile ---
    profile, created = Profile.objects.get_or_create(
        username=username,
        platform="Twitter",
        defaults={
            "full_name": title,
            "bio": "",
            "followers": 0,
            "following": 0,
        },
    )

    # --- Save new RawPosts with sentiment analysis ---
    saved_count = 0
    for text in tweets[:20]:  # limit to first 20 tweets
        if not RawPost.objects.filter(profile=profile, content=text).exists():
            blob = TextBlob(text)
            polarity = round(blob.sentiment.polarity, 3)  # -1.0 = negative, +1.0 = positive

            RawPost.objects.create(
                profile=profile,
                content=text,
                timestamp=timezone.now(),
                sentiment_score=polarity,
            )
            saved_count += 1

    source_type = "nitter" if any(m in html for m in NITTER_MIRRORS) else "twitter"
    logger.info(
        f"✅ {username}: saved {saved_count} new tweets "
        f"(total scraped {len(tweets)}, source={source_type})"
    )

    return {
        "success": True,
        "source": source_type,
        "username": username,
        "title": title,
        "tweets_saved": saved_count,
        "total_tweets_scraped": len(tweets),
    }
