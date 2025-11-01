import logging
import instaloader
import os
import tempfile
from django.conf import settings
from django.utils import timezone
from textblob import TextBlob
from profiles.models import Profile, RawPost, SocialMediaAccount

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
        # 1️⃣ Load local session for development
        if hasattr(settings, "SESSION_FILE") and os.path.exists(settings.SESSION_FILE):
            L.load_session_from_file(settings.IG_LOGIN, filename=settings.SESSION_FILE)
            logger.info("💻 Loaded local Instagram session file.")
            session_loaded = True

        # 2️⃣ Load from environment for production (Render)
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
#  Profile Scraper
# =========================================================
def scrape_instagram_profile(username: str, max_posts: int = 10) -> dict | None:
    """
    Scrape full Instagram profile info including latest posts.
    Returns a dictionary with user data + posts list.
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

        # --- Collect recent posts ---
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

        logger.info(f"✅ Scraped {len(posts_data)} posts for {username}")

        return {
            "full_name": profile.full_name,
            "bio": profile.biography,
            "followers": profile.followers,
            "following": profile.followees,
            "posts": posts_data,  # ✅ fixed: now a list, not an int
            "is_verified": profile.is_verified,
            "external_url": profile.external_url,
            "profile_pic_url": profile_pic_url,
        }

    except instaloader.exceptions.ProfileNotExistsException:
        logger.warning(f"Instagram profile '{username}' not found.")
        return None
    except Exception as e:
        logger.exception(f"Error scraping Instagram for {username}: {e}")
        return None


# =========================================================
#  Save Posts to Database (Optional standalone)
# =========================================================
def scrape_instagram_posts(username: str, max_posts: int = 10) -> list[dict]:
    """
    Fetch recent Instagram posts and save them to RawPost.
    """
    posts_saved = []
    try:
        L = get_instaloader()
        profile = instaloader.Profile.from_username(L.context, username)
        db_profile = Profile.objects.filter(username=username, platform="Instagram").first()

        if not db_profile:
            logger.warning(f"No Profile found for {username} — skipping post save.")
            return []

        count = 0
        for post in profile.get_posts():
            if count >= max_posts:
                break

            caption = (post.caption or "").replace("\n", " ").strip()
            likes = getattr(post, "likes", 0)
            comments = getattr(post, "comments", 0)
            timestamp = post.date_utc or timezone.now()
            sentiment = round(TextBlob(caption).sentiment.polarity, 3) if caption else 0.0

            RawPost.objects.update_or_create(
                profile=db_profile,
                platform="Instagram",
                post_id=post.shortcode,
                defaults={
                    "content": caption[:500],
                    "timestamp": timestamp,
                    "likes": likes,
                    "comments": comments,
                    "sentiment_score": sentiment,
                },
            )

            posts_saved.append({
                "post_id": post.shortcode,
                "caption": caption[:120],
                "likes": likes,
                "comments": comments,
                "sentiment": sentiment,
                "timestamp": timestamp.strftime("%Y-%m-%d %H:%M"),
            })
            count += 1

        logger.info(f"✅ Saved {len(posts_saved)} Instagram posts for {username}")
        return posts_saved

    except instaloader.exceptions.ConnectionException as e:
        logger.warning(f"Connection error fetching posts for {username}: {e}")
        return []
    except Exception as e:
        logger.exception(f"Error scraping posts for {username}: {e}")
        return []


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
