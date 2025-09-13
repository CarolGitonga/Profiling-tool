from celery import shared_task
from .utils.tiktok_scraper import scrape_tiktok_profile
from .utils.instagram_scraper import scrape_instagram_profile
from .models import Profile, SocialMediaAccount


@shared_task
def scrape_tiktok_task(username):
    data = scrape_tiktok_profile(username)
    if not data or "error" in data:
        return {"error": f"TikTok scrape failed for {username}"}

    profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
    profile.full_name = data['nickname']
    profile.avatar_url = data['avatar']
    profile.verified = data['verified']
    profile.save()

    SocialMediaAccount.objects.update_or_create(
        profile=profile,
        platform="TikTok",
        defaults={
            "bio": data['bio'],
            "followers": data['followers'],
            "following": data['following'],
            "hearts": data['likes'],
            "videos": data['video_count'],
            "verified": data['verified'],
            "posts_collected": 0,
        }
    )
    return {"success": True, "username": username, "platform": "TikTok"}


@shared_task
def scrape_instagram_task(username):
    data = scrape_instagram_profile(username)
    if not data or "error" in data:
        return {"error": f"Instagram scrape failed for {username}"}

    profile, _ = Profile.objects.get_or_create(username=username, platform="Instagram")
    profile.full_name = data['full_name']
    profile.avatar_url = data['profile_pic_url']
    profile.save()

    SocialMediaAccount.objects.update_or_create(
        profile=profile,
        platform="Instagram",
        defaults={
            "bio": data['bio'],
            "followers": data['followers'],
            "following": data['following'],
            "posts_collected": data['posts'],
        }
    )
    return {"success": True, "username": username, "platform": "Instagram"}
