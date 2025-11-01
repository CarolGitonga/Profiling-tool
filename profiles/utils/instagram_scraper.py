import logging
import instaloader
import os
import tempfile
from django.conf import settings
from django.utils import timezone
from textblob import TextBlob
from profiles.models import Profile, RawPost, SocialMediaAccount

# ✅ Import your ScrapingBee fallback
from profiles.utils.instagram_scrapingbee_scraper import scrape_instagram_posts_scrapingbee

logger = logging.getLogger(__name__)


# =========================================================
#  Session Loader
# =========================================================
def get_instaloader() -> instaloader.Instaloader:
    """Initialize Instaloader with session from file or environment."""
    L = instaloader.Instaloader(
        download_videos=False,
        download_comments=False,
        save_metadata=False,
        compress_json=False,
        quiet=True,
    )

    session_loaded = False
    try:
        # 1️⃣ Load local session
        if hasattr(settings, "SESSION_FILE") and os.path.exists(settings.SESSION_FILE):
            L.load_session_from_file(settings.IG_LOGIN, filename=settings.SESSION_FILE)
            logger.info("💻 Loaded local Instagram session file.")
            session_loaded = True

        # 2️⃣ Load from environment (Render)
        elif os.getenv("INSTAGRAM_SESSION_DATA"):
            session_data = os.getenv("INSTAGRAM_SESSION_DATA")
            tmpfile = tempfile.NamedTemporaryFile(delete=False)
            tmpfile.write(session_data.encode())
            tmpfile.close()
            L.load_session_from_file("iamcarolgitonga", filename=tmpfile.name)
            logger.info("🔐 Loaded Instagram session from environment.")
            session_loaded = True

        if not session_loaded:
            logger.warning("⚠️ No Instagram session found. Anonymous scraping may be limited.")

    except Exception as e:
        logger.exception(f"❌ Failed to load Instagram session: {e}")

    return L


# =========================================================
#  Profile Scraper with Auto-Fallback
# =========================================================
def scrape_instagram_profile(username: str, max_posts: int = 10) -> dict | None:
    """
    Scrape full Instagram profile info including latest posts.
    Falls back to ScrapingBee if Instaloader fails (rate-limit / unauthorized).
    """
    try:
        L = get_instaloader()
        profile = instaloader.Profile.from_username(L.context, username)

        # --- Profile metadata ---
        try:
            profile_pic_url = str(profile.profile_pic_url)
        except AttributeError:
            profile_pic_url = None
            logger.warning(f"No profile picture found for {username}")

        # --- Collect posts ---
        posts_data = []
        count = 0
        for post in profile.get_posts():
            if count >= max_posts:
                break

            caption = post.caption or ""
            likes = getattr(post, "likes", 0)
            comments = getattr(post, "comments", 0)
            timestamp = post.date_utc or timezone.now()
            sentiment = round(TextBlob(caption).sentiment.polarity, 3) if caption else 0.0

            posts_data.append({
                "post_id": post.shortcode,
                "caption": caption[:120],
                "likes": likes,
                "comments": comments,
                "sentiment": sentiment,
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            })
            count += 1

        logger.info(f"✅ Scraped {len(posts_data)} posts for {username} via Instaloader")

        return {
            "full_name": profile.full_name,
            "bio": profile.biography,
            "followers": profile.followers,
            "following": profile.followees,
            "posts": posts_data,  # ✅ always list
            "is_verified": profile.is_verified,
            "external_url": profile.external_url,
            "profile_pic_url": profile_pic_url,
            "source": "instaloader",
        }

    except instaloader.exceptions.ConnectionException as e:
        msg = str(e).lower()
        if "please wait" in msg or "401" in msg or "403" in msg or "rate" in msg:
            logger.warning(f"🚨 Instaloader blocked or rate-limited for {username}. Using ScrapingBee fallback.")
            return scrape_instagram_fallback(username, max_posts)
        logger.exception(f"Instaloader connection error for {username}: {e}")
        return None

    except instaloader.exceptions.ProfileNotExistsException:
        logger.warning(f"Instagram profile '{username}' not found.")
        return None

    except Exception as e:
        logger.exception(f"Error scraping Instagram for {username}: {e}")
        # Auto-fallback if anything else unexpected happens
        return scrape_instagram_fallback(username, max_posts)


# =========================================================
#  Fallback Handler
# =========================================================
def scrape_instagram_fallback(username: str, max_posts: int = 10) -> dict:
    """
    Use ScrapingBee to fetch Instagram posts when Instaloader fails.
    Returns the same structure for consistency.
    """
    try:
        posts = scrape_instagram_posts_scrapingbee(username, max_posts=max_posts)
        logger.info(f"🐝 Fallback ScrapingBee fetched {len(posts)} posts for {username}")

        return {
            "full_name": username,   # Minimal info
            "bio": "",
            "followers": 0,
            "following": 0,
            "posts": posts or [],
            "is_verified": False,
            "external_url": None,
            "profile_pic_url": None,
            "source": "scrapingbee",
        }
    except Exception as e:
        logger.exception(f"❌ ScrapingBee fallback also failed for {username}: {e}")
        return {"error": str(e), "posts": [], "source": "error"}


# =========================================================
#  Unscrape / Cleanup
# =========================================================
def unscrape_instagram_profile(username: str) -> bool:
    """Delete profile and related Instagram data from DB."""
    try:
        profile = Profile.objects.get(username=username, platform="Instagram")
        SocialMediaAccount.objects.filter(profile=profile, platform="Instagram").delete()
        RawPost.objects.filter(profile=profile, platform="Instagram").delete()
        profile.delete()
        logger.info(f"🧹 Removed Instagram profile and posts for {username}")
        return True
    except Profile.DoesNotExist:
        return False
