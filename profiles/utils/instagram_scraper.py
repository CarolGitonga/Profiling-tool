# raw scraping logic (API calls, parsing, return dicts)
import logging
import instaloader
import os
from profiles.models import Profile, SocialMediaAccount
from django.conf import settings


def scrape_instagram_profile(username: str) -> dict | None:
    try:
        # Initialize Instaloader
        L = instaloader.Instaloader()
        # Load saved session (to avoid frequent logins and rate limits)
        L.load_session_from_file(settings.IG_LOGIN, filename=settings.SESSION_FILE)
        
        

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
    Fetch recent Instagram posts for a given user.
    Returns a list of dicts with basic post info.
    """
    try:
        L = instaloader.Instaloader()
        L.load_session_from_file(settings.IG_LOGIN, filename=settings.SESSION_FILE)

        profile = instaloader.Profile.from_username(L.context, username)
        posts = []

        for count, post in enumerate(profile.get_posts(), start=1):
            posts.append({
                "shortcode": post.shortcode,
                "caption": post.caption[:200] if post.caption else "",
                "likes": post.likes,
                "comments": post.comments,
                "date": post.date_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "image_url": post.url,
            })
            if count >= max_posts:
                break

        return posts

    except Exception as e:
        logging.exception(f"Error scraping posts for {username}: {e}")
        return []

    

def unscrape_instagram_profile(username: str) -> bool:
    """
    Removes stored Instagram profile and associated social media account data.
    """
    try:
        profile = Profile.objects.get(username=username, platform='Instagram')
        SocialMediaAccount.objects.filter(profile=profile, platform='Instagram').delete()
        profile.delete()
        return True
    
    except Profile.DoesNotExist:
        return False
