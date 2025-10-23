# raw scraping logic (API calls, parsing, return dicts)
import logging
import instaloader
import os
import tempfile
from profiles.models import Profile, RawPost, SocialMediaAccount
from django.conf import settings
from django.utils import timezone
from textblob import TextBlob

logger = logging.getLogger(__name__)
def get_instaloader() -> instaloader.Instaloader:
    """Initialize Instaloader and load session automatically from local file or env."""
    L = instaloader.Instaloader()
    session_loaded = False

    try:
        # Try to load local session (for development)
        if hasattr(settings, "SESSION_FILE") and os.path.exists(settings.SESSION_FILE):
            L.load_session_from_file(settings.IG_LOGIN, filename=settings.SESSION_FILE)
            logging.info("💻 Loaded local Instagram session file.")
            session_loaded = True

        # Fallback to environment session (for Render)
        elif os.getenv("INSTAGRAM_SESSION_DATA"):
            session_data = os.getenv("INSTAGRAM_SESSION_DATA")
            tmpfile = tempfile.NamedTemporaryFile(delete=False)
            tmpfile.write(session_data.encode())
            tmpfile.close()
            L.load_session_from_file("iamcarolgitonga", filename=tmpfile.name)
            logging.info(" Loaded Instagram session from environment variable.")
            session_loaded = True

        if not session_loaded:
            logging.warning(" No Instagram session available. You may hit login errors.")

    except Exception as e:
        logging.exception(f" Failed to load Instagram session: {e}")

    return L


def scrape_instagram_profile(username: str) -> dict | None:
    try:
        # Initialize Instaloader
        L = instaloader.Instaloader()
        # Fetch the target user profile
        profile = instaloader.Profile.from_username(L.context, username)

        # Try HD picture first, fallback to normal
        try:
            profile_pic_url = str(profile.profile_pic_url)
        except AttributeError:
            logging.warning(f"No profile picture found for {username}")
            profile_pic_url = None

        return {
            'full_name': profile.full_name,
            'bio': profile.biography,
            'followers': profile.followers,
            'following': profile.followees,
            'posts': profile.mediacount,
            'is_verified': profile.is_verified,
            'external_url': profile.external_url,
           "profile_pic_url": profile_pic_url,
            }
    except instaloader.exceptions.ProfileNotExistsException:
        logging.warning(f"Instagram profile '{username}' not found.")
        return None
    
    except Exception as e:
        logging.exception(f"Error scraping Instagram for {username}: {e}")
        return None

def scrape_instagram_posts(username: str, max_posts: int = 10) -> list[dict]:
    """
    Fetch recent Instagram posts for a given user and save to RawPost.
    Each post includes caption, likes, comments, and timestamp.
    """
    posts_saved = []
    try:
        L = instaloader.Instaloader()
        profile = instaloader.Profile.from_username(L.context, username)

        db_profile = Profile.objects.filter(username=username, platform="Instagram").first()
        if not db_profile:
            logger.warning(f"No Profile found for {username} — skipping post save.")
            return []
        
        count = 0
        for post in profile.get_posts():
            if count >= max_posts:
                break
            caption = post.caption or ""
            timestamp = post.date_utc or timezone.now()

            # Sentiment analysis
            sentiment = round(TextBlob(caption).sentiment.polarity, 3) if caption else 0.0
            RawPost.objects.update_or_create(
                profile=db_profile,
                platform="Instagram",
                post_id=post.shortcode, 
                defaults={
                    "content": caption[:500],
                    "timestamp": timestamp,
                    "likes": post.likes,
                    "comments": post.comments,
                    "sentiment_score": sentiment,
                },
            )
            posts_saved.append({
                "post_id": post.shortcode,
                "caption": caption[:100],
                "likes": post.likes,
                "comments": post.comments,
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

    

def unscrape_instagram_profile(username: str) -> bool:
    """Removes stored Instagram profile and associated social data."""
    try:
        profile = Profile.objects.get(username=username, platform="Instagram")
        SocialMediaAccount.objects.filter(profile=profile, platform="Instagram").delete()
        RawPost.objects.filter(profile=profile, platform="Instagram").delete()
        profile.delete()
        logger.info(f"Removed Instagram profile and posts for {username}")
        return True
    except Profile.DoesNotExist:
        return False
