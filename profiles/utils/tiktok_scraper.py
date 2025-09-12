import logging
import asyncio
from TikTokApi import TikTokApi
from profiles.models import Profile, SocialMediaAccount


async def _fetch_tiktok_info(username: str):
    """Internal async helper to fetch TikTok user info."""
    api = TikTokApi()

    # ✅ create a session (required for requests)
    await api.create_sessions(num_sessions=1, headless=True)

    user = api.user(username=username)
    info = await user.info()
    return info


def scrape_tiktok_profile(username: str):
    """
    Sync wrapper for scraping TikTok profile data.
    """
    try:
        info = asyncio.run(_fetch_tiktok_info(username))

        return {
            "username": info['user']['uniqueId'],
            "nickname": info['user']['nickname'],
            "bio": info['user']['signature'],
            "followers": info['stats']['followerCount'],
            "following": info['stats']['followingCount'],
            "likes": info['stats']['heartCount'],
            "video_count": info['stats']['videoCount'],
            "verified": info['user']['verified'],
            "avatar": info['user']['avatarLarger'],
        }

    except Exception as e:
        logging.exception("Error scraping TikTok profile")
        return {"error": str(e)}


def unscrape_tiktok_profile(username: str):
    """
    Deletes TikTok-related social media records for the given username.
    """
    try:
        profile = Profile.objects.get(username=username, platform='TikTok')
        SocialMediaAccount.objects.filter(profile=profile, platform='TikTok').delete()
        return True
    except Profile.DoesNotExist:
        return False
