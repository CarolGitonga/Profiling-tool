# profiles/tasks.py
from celery import shared_task
import logging
from django.db import transaction
from .utils.tiktok_scraper import scrape_tiktok_profile
from .utils.instagram_scraper import scrape_instagram_profile
from .models import Profile, SocialMediaAccount


@shared_task(bind=True, max_retries=3, default_retry_delay=30)  # retry up to 3 times, wait 30s
def scrape_tiktok_task(self, username: str) -> dict:
    """
    Celery task: Scrape TikTok profile and save to DB.
    Retries automatically if scraping fails (e.g., network issues).
    """
    try:
        data = scrape_tiktok_profile(username)

        if not data or "error" in data:
            raise Exception(data.get("error", f"TikTok scrape failed for {username}"))

        with transaction.atomic():
            profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
            profile.full_name = data.get("nickname") or ""
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
        logging.exception(f"TikTok scraping failed for {username}")
        try:
            # retry with exponential backoff
            raise self.retry(exc=e, countdown=2 ** self.request.retries)
        except self.MaxRetriesExceededError:
            return {"error": str(e), "username": username, "platform": "TikTok"}


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def scrape_instagram_task(self, username: str) -> dict:
    """
    Celery task: Scrape Instagram profile and save to DB.print(res.get())
    Retries automatically if scraping fails.
    """
    try:
        data = scrape_instagram_profile(username)

        if not data or "error" in data:
            raise Exception(data.get("error", f"Instagram scrape failed for {username}"))

        with transaction.atomic():
            profile, _ = Profile.objects.get_or_create(username=username, platform="Instagram")
            profile.full_name = data.get("full_name") or ""
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
                    "is_private": False,  # TODO: scrape this if needed
                    "external_url": data.get("external_url"),
                },
            )

        return {"success": True, "username": username, "platform": "Instagram"}

    except Exception as e:
        logging.exception(f"Instagram scraping failed for {username}")
        try:
            raise self.retry(exc=e, countdown=2 ** self.request.retries)
        except self.MaxRetriesExceededError:
            return {"error": str(e), "username": username, "platform": "Instagram"}
