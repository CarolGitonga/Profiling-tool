import os
import random
import logging
from scrapingbee import ScrapingBeeClient
from bs4 import BeautifulSoup
from django.utils import timezone
from textblob import TextBlob
from profiles.models import Profile, SocialMediaAccount, RawPost

logger = logging.getLogger(__name__)

# --- Fallback Nitter mirrors ---
NITTER_MIRRORS = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacydev.net",
    "https://nitter.lucabased.xyz",
]


def scrape_twitter_profile(username: str):
    """
    Scrape Twitter profile using ScrapingBee (fallback to Nitter if blocked).
    Integrates with Profile, SocialMediaAccount, and RawPost models.
    Performs sentiment analysis and updates post count.
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

    # --- Attempt ScrapingBee ---
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

    # --- Parse tweets ---
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title else username

    # detect which selector works
    tweet_selectors = [
        "div[data-testid='tweetText']",  # Twitter mobile layout
        "div.tweet-content",             # Nitter layout
    ]
    tweets = []
    for selector in tweet_selectors:
        els = soup.select(selector)
        if els:
            tweets = [div.get_text(" ", strip=True) for div in els]
            break

    if not tweets:
        logger.warning(f"⚠️ No tweets found for {username}")
        return {"error": "No tweets found"}

    # --- Get or create Profile ---
    profile, _ = Profile.objects.get_or_create(
        username=username,
        platform="Twitter",
        defaults={
            "full_name": title,
            "avatar_url": "",
        },
    )

    # --- Get or create SocialMediaAccount ---
    sm_account, _ = SocialMediaAccount.objects.get_or_create(
        profile=profile,
        platform="Twitter",
        defaults={
            "bio": "",
            "followers": 0,
            "following": 0,
            "posts_collected": 0,
        },
    )

    # --- Parse basic info (if available in Nitter) ---
    bio_el = soup.select_one(".profile-bio, div[data-testid='UserDescription']")
    followers_el = soup.select_one("a[href$='/followers'] span")
    following_el = soup.select_one("a[href$='/following'] span")
    avatar_el = soup.select_one("img.avatar, img[alt*='Image']")

    sm_account.bio = bio_el.text.strip() if bio_el else sm_account.bio
    sm_account.followers = (
        _extract_int(followers_el.text) if followers_el else sm_account.followers
    )
    sm_account.following = (
        _extract_int(following_el.text) if following_el else sm_account.following
    )
    profile.avatar_url = avatar_el["src"] if avatar_el and avatar_el.has_attr("src") else profile.avatar_url
    sm_account.save()
    profile.save(update_fields=["avatar_url"])

    # --- Save tweets to RawPost ---
    saved_count = 0
    for text in tweets[:20]:
        if not RawPost.objects.filter(profile=profile, platform="Twitter", content=text).exists():
            blob = TextBlob(text)
            polarity = round(blob.sentiment.polarity, 3)

            RawPost.objects.create(
                profile=profile,
                platform="Twitter",
                content=text,
                timestamp=timezone.now(),
                sentiment_score=polarity,
            )
            saved_count += 1

    # Update post metrics
    total_posts = RawPost.objects.filter(profile=profile, platform="Twitter").count()
    profile.posts_count = total_posts
    sm_account.posts_collected = total_posts
    profile.save(update_fields=["posts_count"])
    sm_account.save(update_fields=["posts_collected"])

    source_type = "nitter" if any(m in html for m in NITTER_MIRRORS) else "twitter"
    logger.info(
        f"✅ {username}: saved {saved_count} new tweets "
        f"(total scraped {len(tweets)}, source={source_type})"
    )

    return {
        "success": True,
        "source": source_type,
        "username": username,
        "full_name": title,
        "tweets_saved": saved_count,
        "total_tweets_scraped": len(tweets),
        "followers": sm_account.followers,
        "following": sm_account.following,
        "bio": sm_account.bio,
    }


# --- Helper ---
def _extract_int(text):
    """Convert follower text like '3.2K' into an integer."""
    text = text.replace(",", "").strip().upper()
    try:
        if "K" in text:
            return int(float(text.replace("K", "")) * 1000)
        elif "M" in text:
            return int(float(text.replace("M", "")) * 1_000_000)
        return int(text)
    except ValueError:
        return 0
