# profiles/tasks.py
import logging
from celery import shared_task
from django.db import transaction
from .utils.tiktok_scraper import scrape_tiktok_profile
from .utils.instagram_scraper import scrape_instagram_profile
from .models import Profile, SocialMediaAccount


logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def scrape_tiktok_task(self, username: str) -> dict:
    """
    Celery task: Scrape TikTok profile and save to DB.
    Retries automatically if scraping fails (e.g., network issues).
    """
    try:
        data = scrape_tiktok_profile(username)

        if not data:
            raise Exception(f"TikTok scrape returned no data for {username}")
        if isinstance(data, dict) and "error" in data:
            raise Exception(data["error"])

        with transaction.atomic():
            profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
            profile.full_name = data.get("nickname", "")
            profile.avatar_url = data.get("avatar")
            profile.verified = data.get("verified", False)
            profile.save()

            SocialMediaAccount.objects.update_or_create(
                profile=profile,
                platform="TikTok",
                defaults={
                    "bio": data.get("bio", ""),
                    "followers": data.get("followers", 0),
                    "following": data.get("following", 0),
                    "hearts": data.get("likes", 0),
                    "videos": data.get("video_count", 0),
                    "verified": data.get("verified", False),
                    "posts_collected": 0,
                },
            )

        return {"success": True, "username": username, "platform": "TikTok"}

    except Exception as e:
        logger.exception(f"TikTok scraping failed for {username}")
        try:
            raise self.retry(exc=e, countdown=2 ** self.request.retries)
        except self.MaxRetriesExceededError:
            return {"error": str(e), "username": username, "platform": "TikTok"}


@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def scrape_instagram_task(self, username: str) -> dict:
    """
    Celery task: Scrape Instagram profile and save to DB.
    Retries automatically if scraping fails (e.g., rate limiting).
    """
    try:
        data = scrape_instagram_profile(username)

        if not data:
            raise Exception(f"Instagram scrape returned no data for {username}")
        if isinstance(data, dict) and "error" in data:
            raise Exception(data["error"])

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

        return {"success": True, "username": username, "platform": "Instagram"}

    #except Exception as e:
       # logger.exception(f"Instagram scraping failed for {username}")
       # try:
       #     raise self.retry(exc=e, countdown=60 ** self.request.retries + 1)
       # except self.MaxRetriesExceededError:
         #   return {"error": str(e), "username": username, "platform": "Instagram"}

    except Exception as e:
        err_msg = str(e)
        logger.exception(f"Instagram scraping failed for {username}: {err_msg}")

        try:
            # Special handling for Instagram's "Please wait" rate-limit
            if "Please wait a few minutes" in err_msg:
                wait_time = 600  # 10 minutes
                logger.warning(f"Rate limit hit for {username}, retrying in {wait_time//60} minutes")
                raise self.retry(exc=e, countdown=wait_time)

            # Exponential backoff for other errors: 2s, 4s, 8s, 16s...
            backoff = min(2 ** self.request.retries, 900)  # cap at 15 minutes
            raise self.retry(exc=e, countdown=backoff)

        except self.MaxRetriesExceededError:
            return {"error": err_msg, "username": username, "platform": "Instagram"}
        

    
