import os
import re
import random
import logging
from bs4 import BeautifulSoup
from textblob import TextBlob
from scrapingbee import ScrapingBeeClient
from django.utils import timezone
from profiles.models import Profile, SocialMediaAccount, RawPost

logger = logging.getLogger(__name__)

# ✅ Active Nitter mirrors (as of 2025)
NITTER_MIRRORS = [
    "https://nitter.net",
    "https://nitter.privacydev.net",
    "https://nitter.freedit.eu",
    "https://nitter.catsarch.com",
]


# ============================================================
# 🧩 Helper: ScrapingBee client & value parsing
# ============================================================
def _get_client():
    api_key = os.getenv("SCRAPINGBEE_API_KEY")
    if not api_key:
        logger.error("❌ SCRAPINGBEE_API_KEY missing in environment.")
        return None
    return ScrapingBeeClient(api_key=api_key)


def _extract_int(text: str) -> int:
    """Convert follower counts like '3.2K' or '1,024' into integers."""
    text = text.replace(",", "").strip().upper()
    try:
        if "K" in text:
            return int(float(text.replace("K", "")) * 1_000)
        elif "M" in text:
            return int(float(text.replace("M", "")) * 1_000_000)
        return int(text)
    except ValueError:
        return 0


# ============================================================
# 🧩 Universal Fallback: Search visible text near labels
# ============================================================
def _extract_stat_from_text(soup, label: str):
    """Fallback: detect patterns like 'Followers 4,512' in raw text."""
    text = " ".join(soup.stripped_strings)
    match = re.search(rf"([\d,\.KM]+)\s+{label}", text, re.IGNORECASE)
    if match:
        return _extract_int(match.group(1))
    return 0


# ============================================================
# 🧩 Main Scraper
# ============================================================
def scrape_twitter_profile(username: str):
    """
    Scrape a Twitter profile via ScrapingBee (fallback to Nitter).
    Saves tweets, computes sentiment, and updates database records.
    """
    client = _get_client()
    if not client:
        return {"error": "Missing API key"}

    html, source_type = None, "twitter"
    twitter_url = f"https://mobile.twitter.com/{username}"

    params = {
        "render_js": "true",
        "stealth_proxy": "true",
        "premium_proxy": "true",
        "country_code": random.choice(["us", "de", "fr"]),
        "wait_browser": "10000",
    }

    # --- Try ScrapingBee (mobile.twitter.com)
    logger.info(f"🕵️ Trying ScrapingBee for {username} ...")
    try:
        resp = client.get(twitter_url, params=params)
        if resp.status_code == 200 and b"data-testid" in resp.content:
            html = resp.content.decode("utf-8", errors="ignore")
            logger.info(f"✅ ScrapingBee succeeded for {username}")
        else:
            logger.warning(f"⚠️ ScrapingBee returned {resp.status_code} for {username}")
    except Exception as e:
        logger.error(f"❌ ScrapingBee error for {username}: {e}")

    # --- Fallback to Nitter mirrors
    if not html:
        logger.warning(f"⚠️ Falling back to Nitter for {username}")
        for mirror in random.sample(NITTER_MIRRORS, len(NITTER_MIRRORS)):
            try:
                nitter_url = f"{mirror}/{username}"
                r = client.get(nitter_url)
                if r.status_code == 200:
                    html = r.content.decode("utf-8", errors="ignore")
                    source_type = "nitter"
                    logger.info(f"✅ Using Nitter mirror: {mirror}")
                    break
            except Exception as e:
                logger.warning(f"⚠️ Mirror failed {mirror}: {e}")
                continue

    if not html:
        logger.error(f"❌ All sources failed for {username}")
        return {"error": f"All sources failed for {username}"}

    # ============================================================
    # 🧩 Parse HTML (Works for both layouts)
    # ============================================================
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.string.strip() if soup.title else username

    # --- Bio
    bio_el = soup.select_one(".profile-bio, div[data-testid='UserDescription']")
    bio = bio_el.get_text(" ", strip=True) if bio_el else ""

    # --- Avatar
    avatar_el = soup.select_one("img.avatar, img[alt*='Image']")
    avatar_url = avatar_el["src"] if avatar_el and avatar_el.has_attr("src") else ""
    if avatar_url.startswith("/"):
        avatar_url = f"{NITTER_MIRRORS[0]}{avatar_url}"

    # ============================================================
    # 🧩 Followers / Following (universal detection)
    # ============================================================
    followers = 0
    following = 0

    # Try multiple HTML patterns
    for selector in [
        'a[href*="/followers"] .profile-stat-num',
        'a[href*="/followers"] span',
        'a[href*="/followers"] div',
        'span:contains("Followers")',
        'div:contains("Followers")',
    ]:
        el = soup.select_one(selector)
        if el:
            followers = _extract_int(el.get_text())
            logger.debug(f"🧩 Followers element match: {selector} -> {followers}")
            break

    for selector in [
        'a[href*="/following"] .profile-stat-num',
        'a[href*="/following"] span',
        'a[href*="/following"] div',
        'span:contains("Following")',
        'div:contains("Following")',
    ]:
        el = soup.select_one(selector)
        if el:
            following = _extract_int(el.get_text())
            logger.debug(f"🧩 Following element match: {selector} -> {following}")
            break

    # Fallback text parsing if still 0
    if followers == 0:
        followers = _extract_stat_from_text(soup, "Followers")
    if following == 0:
        following = _extract_stat_from_text(soup, "Following")

    logger.info(f"📊 Stats parsed robustly: followers={followers}, following={following}")

    # ============================================================
    # 🧩 Tweets
    # ============================================================
    tweet_selectors = [
        "div[data-testid='tweetText']",
        "div.tweet-content",
        "div.tweet-content.media-body",
        "div.main-tweet > p",
    ]
    tweets = []
    for selector in tweet_selectors:
        els = soup.select(selector)
        if els:
            tweets = [div.get_text(" ", strip=True) for div in els if div.get_text(strip=True)]
            break

    if not tweets:
        logger.warning(f"⚠️ No tweets found for {username}")
        return {"error": "No tweets found"}

    # ============================================================
    # 🧩 Save to Database
    # ============================================================
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

    # --- Save tweets + sentiment
    saved_count = 0
    for text in tweets[:20]:
        text = text.strip()
        if not text:
            continue
        if not RawPost.objects.filter(profile=profile, platform="Twitter", content__icontains=text[:50]).exists():
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

    logger.info(
        f"💾 {username}: saved {saved_count}/{len(tweets)} tweets, followers={followers}, following={following}, source={source_type}"
    )

    # ============================================================
    # 🧩 Return Summary
    # ============================================================
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
