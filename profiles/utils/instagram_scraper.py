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
        logging.exception(f"Error scraping Instagram for {username}")
        return None
    

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
