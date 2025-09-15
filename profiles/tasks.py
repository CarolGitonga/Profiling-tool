# Celery tasks (wrap scrapers, save Profile/SocialMediaAccount)
from celery import shared_task
import logging
from .utils.tiktok_scraper import scrape_tiktok_profile
from .utils.instagram_scraper import scrape_instagram_profile
from .models import Profile, SocialMediaAccount


@shared_task
def scrape_tiktok_task(username: str) -> dict:
    """
    Celery task: Scrape TikTok profile and save to DB.
    """
    try:
        data = scrape_tiktok_profile(username)
        if not data or "error" in data:
            raise Exception(data.get("error", f"TikTok scrape failed for {username}"))

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
        return {"error": str(e), "username": username, "platform": "TikTok"}


@shared_task
def scrape_instagram_task(username: str) -> dict:
    """
    Celery task: Scrape Instagram profile and save to DB.
    """
    try:
        data = scrape_instagram_profile(username)
        if not data or "error" in data:
            raise Exception(data.get("error", f"Instagram scrape failed for {username}"))

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
                "is_private": False,  # you could add a real check if needed
                "external_url": data.get("external_url"),
            },
        )
        return {"success": True, "username": username, "platform": "Instagram"}

    except Exception as e:
        logging.exception(f"Instagram scraping failed for {username}")
        return {"error": str(e), "username": username, "platform": "Instagram"}
