# tiktok_scraper.py

from TikTokApi import TikTokApi
import logging

from profiles.models import Profile, SocialMediaAccount

def scrape_tiktok_profile(username):
    """
    Scrapes public TikTok profile data using TikTokApi and Playwright.
    
    Args:
        username (str): The TikTok username to scrape (without @).
    
    Returns:
        dict: Dictionary with TikTok user data or error details.
    """
    try:
        with TikTokApi() as api:
            user = api.user(username=username)
            info = user.info()

            return {
                "username": info['user']['uniqueId'],
                "nickname": info['user']['nickname'],
                "bio": info['user']['signature'],
                "followers": info['stats']['followerCount'],
                "following": info['stats']['followingCount'],
                "likes": info['stats']['heartCount'],
                "video_count": info['stats']['videoCount'],
                "verified": info['user']['verified'],
                "avatar": info['user']['avatarLarger']
            }

    except Exception as e:
        logging.exception("Error scraping TikTok profile")
        return {"error": str(e)}
    
def unscrape_tiktok_profile(username):
    """
    Deletes TikTok-related social media records for the given username.
    """
    try:
        profile = Profile.objects.get(username=username, platform='TikTok')
        SocialMediaAccount.objects.filter(profile=profile, platform='TikTok').delete()
        return True
    except Profile.DoesNotExist:
        return False

