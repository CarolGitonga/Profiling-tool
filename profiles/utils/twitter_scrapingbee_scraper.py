import os
import re
import random
import logging
from scrapingbee import ScrapingBeeClient
from bs4 import BeautifulSoup
from django.utils import timezone
from textblob import TextBlob
from profiles.models import Profile, SocialMediaAccount, RawPost

logger = logging.getLogger(__name__)

# 🌍 Nitter fallback mirrors
NITTER_MIRRORS = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.lucabased.xyz",
]


# -------------------------------------------------------------
# 🧩 Helper functions
# -------------------------------------------------------------
def _extract_int(text: str) -> int:
    """Convert string like '3.2K' or '1.4M' to int."""
    if not text:
        return 0
    text = text.replace(",", "").strip().upper()
    try:
        if "K" in text:
            return int(float(text.replace("K", "")) * 1_000)
        if "M" in text:
            return int(float(text.replace("M", "")) * 1_000_000)
        return int(re.sub(r"\D", "", text))
    except Exception:
        return 0


def _get_client() -> ScrapingBeeClient | None:
    """Initialize ScrapingBee client."""
    api_key = os.getenv("SCRAPINGBEE_API_KEY")
    if not api_key:
        logger.error("❌ Missing SCRAPINGBEE_API_KEY in environment.")
        return None
    return ScrapingBeeClient(api_key=api_key)


# -------------------------------------------------------------
# 🧩 Main scraper
# -------------------------------------------------------------
def scrape_twitter_profile(username: str):
    """
    Scrape Twitter profile (ScrapingBee → Nitter fallback),
    integrate with Profile, SocialMediaAccount, and RawPost models,
    perform sentiment analysis, and update stats.
    """
    client = _get_client()
    if not client:
        return {"error": "Missing API key"}

    html = None
    twitter_url = f"https://mobile.twitter.com/{username}"

    params = {
        "render_js": "true",
        "stealth_proxy": "true",
        "premium_proxy": "true",
        "country_code": random.choice(["us", "de", "fr"]),
        "wait_browser": "10000",
    }

    logger.info(f"🕵️ Trying ScrapingBee for Twitter user: {username}")

    # --- Try ScrapingBee ---
    try:
        resp = client.get(twitter_url, params=params)
        if resp.status_code == 200 and b"data-testid" in resp.content:
            html = resp.content.decode("utf-8", errors="ignore")
            logger.info(f"✅ ScrapingBee succeeded for {username}")
        else:
            logger.warning(f"⚠️ ScrapingBee returned {resp.status_code} for {username}")
    except Exception as e:
        logger.error(f"❌ ScrapingBee request failed for {username}: {e}")

    # --- Fallback to Nitter ---
    if not html:
        logger.warning(f"⚠️ Falling back to Nitter for {username}")
        for mirror in random.sample(NITTER_MIRRORS, len(NITTER_MIRRORS)):
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

    # ---------------------------------------------------------
    # 🧩 Parse HTML (works for both mobile & Nitter)
    # ---------------------------------------------------------
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title else username

    # Bio and avatar
    bio_el = soup.select_one(".profile-bio, div[data-testid='UserDescription']")
    avatar_el = soup.select_one("img.avatar, img[alt*='Image']")
    bio = bio_el.get_text(" ", strip=True) if bio_el else ""
    avatar_url = avatar_el["src"] if avatar_el and avatar_el.has_attr("src") else ""

    # Followers & Following
    followers_el = soup.select_one("a[href$='/followers'] span, a[href$='/followers'] .profile-stat-num")
    following_el = soup.select_one("a[href$='/following'] span, a[href$='/following'] .profile-stat-num")
    followers = _extract_int(followers_el.get_text() if followers_el else "")
    following = _extract_int(following_el.get_text() if following_el else "")

    # Tweets
    tweet_selectors = ["div[data-testid='tweetText']", "div.tweet-content"]
    tweets = []
    for selector in tweet_selectors:
        elements = soup.select(selector)
        if elements:
            tweets = [div.get_text(" ", strip=True) for div in elements]
            break

    if not tweets:
        logger.warning(f"⚠️ No tweets found for {username}")
        return {"error": "No tweets found"}

    # ---------------------------------------------------------
    # 🧩 Save Profile + SocialMediaAccount + RawPosts
    # ---------------------------------------------------------
    profile, _ = Profile.objects.get_or_create(
        username=username,
        platform="Twitter",
        defaults={"full_name": title, "avatar_url": avatar_url},
    )
    profile.avatar_url = avatar_url or profile.avatar_url
    profile.save(update_fields=["avatar_url"])

    sm_account, _ = SocialMediaAccount.objects.get_or_create(profile=profile, platform="Twitter")
    sm_account.bio = bio
    sm_account.followers = followers
    sm_account.following = following
    sm_account.save()

    # Save tweets with sentiment
    saved_count = 0
    for text in tweets[:20]:
        if not RawPost.objects.filter(profile=profile, platform="Twitter", content=text).exists():
            polarity = round(TextBlob(text).sentiment.polarity, 3)
            RawPost.objects.create(
                profile=profile,
                platform="Twitter",
                content=text,
                timestamp=timezone.now(),
                sentiment_score=polarity,
            )
            saved_count += 1

    total_posts = RawPost.objects.filter(profile=profile, platform="Twitter").count()
    profile.posts_count = total_posts
    sm_account.posts_collected = total_posts
    profile.save(update_fields=["posts_count"])
    sm_account.save(update_fields=["posts_collected"])

    source_type = "nitter" if any(m in html for m in NITTER_MIRRORS) else "twitter"
    logger.info(
        f"✅ {username}: saved {saved_count} new tweets (followers={followers}, following={following}, source={source_type})"
    )

    # ---------------------------------------------------------
    # 🧩 Return structured summary
    # ---------------------------------------------------------
    return {
        "success": True,
        "source": source_type,
        "username": username,
        "full_name": title,
        "bio": bio,
        "avatar_url": avatar_url,
        "followers": followers,
        "following": following,
        "tweets_saved": saved_count,
        "total_tweets_scraped": len(tweets),
    }
