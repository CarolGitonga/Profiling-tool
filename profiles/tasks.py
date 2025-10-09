# profiles/tasks.py
import logging
from celery import shared_task
from django.db import transaction
from .utils.tiktok_scraper import scrape_tiktok_profile
from .utils.instagram_scraper import scrape_instagram_profile
from .models import Profile, SocialMediaAccount
import random


logger = logging.getLogger(__name__)


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

"""
@shared_task(bind=True, max_retries=5, default_retry_delay=60)
def scrape_instagram_task(self, username: str) -> dict:
    comment
    Celery task: Scrape Instagram profile and save to DB.
    Retries automatically if scraping fails (e.g., rate limiting).
    
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
            """
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
        

    
