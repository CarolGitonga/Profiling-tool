import logging
from celery import shared_task
from django.db import transaction
from .utils.tiktok_scraper import scrape_tiktok_profile
from .utils.instagram_scraper import scrape_instagram_profile
from .models import BehavioralAnalysis, Profile, SocialMediaAccount
import random
import pandas as pd
import re
from textblob import TextBlob
from django.utils import timezone

logger = logging.getLogger(__name__)


def ensure_behavioral_record(profile):
    """Ensure a BehavioralAnalysis record exists for the given profile."""
    BehavioralAnalysis.objects.get_or_create(profile=profile)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="tiktok")
def scrape_tiktok_task(self, username: str) -> dict:
    """
    Celery task: Scrape TikTok profile via ScrapingBee and save to DB.
    Retries automatically on transient errors (network, rate limit).
    """
    try:
        result = scrape_tiktok_profile(username)

        # Handle success
        if result.get("success"):
            logger.info(f"TikTok scrape succeeded for {username}")

            #return {"success": True, "username": username, "platform": "TikTok"}
            # Get or create profile entry
            profile, _ = Profile.objects.get_or_create(
                username=username,
                platform="TikTok"
            )
            # Update profile basic info
            profile.full_name = result.get("full_name", "")
            profile.avatar_url = result.get("avatar_url")
            profile.save()

            # Update social account data
            SocialMediaAccount.objects.update_or_create(
                profile=profile,
                platform="TikTok",
                defaults={
                    "bio": result.get("bio", ""),
                    "followers": result.get("followers", 0),
                    "following": result.get("following", 0),
                    "posts_collected": result.get("posts", 0),
                    "is_private": result.get("is_private", False),
                    "external_url": result.get("external_url"),
                },
            )
            #Create behavioral record
            ensure_behavioral_record(profile)
            perform_behavioral_analysis.delay(profile.id)
            logger.info(f"✅ Behavioral record ensured for {username} (TikTok)")

            return {"success": True, "username": username, "platform": "TikTok"}


        # Handle explicit scrape failure (returned by scraper)
        reason = result.get("reason") or result.get("error") or "Unknown error"
        logger.warning(f"TikTok scrape failed for {username}: {reason}")
        raise Exception(reason)

    except Exception as e:
        logger.exception(f"TikTok scraping error for {username}")
        try:
            # Exponential backoff retries: 60s, 120s, 240s...
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for TikTok scrape: {username}")
            return {
                "success": False,
                "username": username,
                "platform": "TikTok",
                "reason": str(e)
            }

@shared_task(bind=True, max_retries=5, default_retry_delay=60, queue="instagram")
def scrape_instagram_task(self, username: str) -> dict:
    """
    Celery task: Scrape Instagram profile and save to DB.
    Retries only on temporary errors (rate limiting, network issues).
    Permanent errors (invalid/private/deleted accounts) are recorded once.
    """
    try:
        data = scrape_instagram_profile(username)

        # ✅ Handle permanent failures (invalid, deleted, private, no data)
        if not data or (isinstance(data, dict) and "error" in data):
            reason = data.get("error") if isinstance(data, dict) else "no data"
            logger.warning(f"Permanent failure scraping {username}: {reason}")

            # Store minimal record to avoid retrying forever
            with transaction.atomic():
                profile, _ = Profile.objects.get_or_create(
                    username=username,
                    platform="Instagram",
                )
                profile.full_name = ""
                profile.avatar_url = None
                profile.save()

                SocialMediaAccount.objects.update_or_create(
                    profile=profile,
                    platform="Instagram",
                    defaults={
                        "bio": "",
                        "followers": 0,
                        "following": 0,
                        "posts_collected": 0,
                        "is_private": True,  # assume private if no data
                        "external_url": None,
                    },
                )

            return {"success": False, "username": username, "platform": "Instagram", "reason": reason}

        # ✅ Valid scrape → save full profile
        with transaction.atomic():
            profile, _ = Profile.objects.get_or_create(username=username, platform="Instagram")
            profile.full_name = data.get("full_name", "")
            profile.avatar_url = data.get("profile_pic_url")
            profile.save()

            SocialMediaAccount.objects.update_or_create(
                profile=profile,
                platform="Instagram",
                defaults={
                    "bio": data.get("bio", ""),
                    "followers": data.get("followers", 0),
                    "following": data.get("following", 0),
                    "posts_collected": data.get("posts", 0),
                    "is_private": data.get("is_private", False),
                    "external_url": data.get("external_url"),
                },
            )
            # Create behavioral record
            ensure_behavioral_record(profile)
            perform_behavioral_analysis.delay(profile.id)
            logger.info(f"✅ Behavioral record ensured for {username} (Instagram)")

        return {"success": True, "username": username, "platform": "Instagram"}

    except Exception as e:
        err_msg = str(e)
        logger.exception(f"Instagram scraping failed for {username}: {err_msg}")

        try:
            # Retry only on temporary errors
            if "Please wait a few minutes" in err_msg or "401 Unauthorized" in err_msg:
               wait_time = 600  # 10 minutes
               logger.warning(f"Rate-limit block for {username}, retrying in {wait_time//60} minutes")
               raise self.retry(exc=e, countdown=wait_time)


            if "429" in err_msg or "temporarily unavailable" in err_msg:
                wait_time = random.randint(60, 180)  # 1-3 minutes
                logger.warning(f"Temporary error for {username}, retrying in {wait_time} seconds")
                raise self.retry(exc=e, countdown=wait_time)

            # ❌ For all other errors (invalid username, private, deleted), mark as permanent
            logger.error(f"Permanent error for {username}: {err_msg}")
            return {"success": False, "username": username, "platform": "Instagram", "reason": err_msg}

        except self.MaxRetriesExceededError:
            return {"error": err_msg, "username": username, "platform": "Instagram"}
    


@shared_task(bind=True, queue="default")
def perform_behavioral_analysis(self, profile_id):
    """
    Analyze a user's posting behavior, language, and interests.
    Updates the BehavioralAnalysis model for the given profile.
    """
    from .models import Profile, BehavioralAnalysis, SocialMediaAccount  # avoid circular imports

    try:
        profile = Profile.objects.get(id=profile_id)
        analysis, _ = BehavioralAnalysis.objects.get_or_create(profile=profile)

        # Simulate fetching user's text posts from SocialMediaAccount or other models
        # In your project, replace this with actual post text data.
        social_data = SocialMediaAccount.objects.filter(profile=profile).values_list("bio", flat=True)
        text_data = " ".join([t for t in social_data if t])

        # -----------------------------------
        # 🕒 1. Posting Patterns (Demo logic)
        # -----------------------------------
        # In a real case, use post timestamps from a RawPost model.
        # Here we simulate a simple placeholder:
        df = pd.DataFrame({
            "hour": [10, 14, 14, 21, 21, 21, 22],
            "weekday": ["Monday", "Tuesday", "Tuesday", "Friday", "Friday", "Friday", "Sunday"]
        })
        avg_post_time = f"{df['hour'].mode()[0]}:00"
        most_active_days = df['weekday'].value_counts().head(3).index.tolist()

        # -----------------------------------
        # 💬 2. Sentiment Analysis
        # -----------------------------------
        sentiment_score = 0.0
        if text_data:
            sentiment_score = round(TextBlob(text_data).sentiment.polarity, 2)

        # -----------------------------------
        # 🔖 3. Keyword & Hashtag Extraction
        # -----------------------------------
        hashtags = re.findall(r"#(\w+)", text_data)
        words = re.findall(r"\b[a-zA-Z]{4,}\b", text_data.lower())  # words >= 4 chars
        all_keywords = hashtags + words
        keyword_freq = pd.Series(all_keywords).value_counts().head(10).to_dict() if all_keywords else {}

        # -----------------------------------
        # 📍 4. Geolocation (placeholder)
        # -----------------------------------
        geo_locations = ["Nairobi", "Kenya"]  # Placeholder until you extract real locations

        # -----------------------------------
        # 👥 5. Network Size (followers + following)
        # -----------------------------------
        sm = SocialMediaAccount.objects.filter(profile=profile).first()
        network_size = (sm.followers + sm.following) if sm else 0

        # -----------------------------------
        # ✅ 6. Save Analysis
        # -----------------------------------
        analysis.avg_post_time = avg_post_time
        analysis.most_active_days = most_active_days
        analysis.sentiment_score = sentiment_score
        analysis.top_keywords = keyword_freq
        analysis.geo_locations = geo_locations
        analysis.network_size = network_size
        analysis.analyzed_at = timezone.now()
        analysis.save()

        logger.info(f"✅ Behavioral analysis completed for {profile.username}")
        return {"success": True, "profile": profile.username}

    except Exception as e:
        logger.exception(f"Behavioral analysis failed for profile {profile_id}: {e}")
        return {"success": False, "error": str(e)}


    
