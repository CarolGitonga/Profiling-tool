import instaloader
import os
from profiles.models import Profile, SocialMediaAccount
from django.conf import settings


def scrape_instagram_profile(username):
    try:
        # Step 3: Load the session into Instaloader
        L = instaloader.Instaloader()
        L.load_session_from_file(settings.IG_LOGIN, filename=settings.SESSION_FILE)
        
        

        # Fetch the target user profile
        profile = instaloader.Profile.from_username(L.context, username)

        

        return {
            'full_name': profile.full_name,
            'bio': profile.biography,
            'followers': profile.followers,
            'following': profile.followees,
            'posts': profile.mediacount,
            'is_verified': profile.is_verified,
            'external_url': profile.external_url,
            'profile_pic_url': profile.profile_pic_url
             }
    except instaloader.exceptions.ProfileNotExistsException:
        print(f"Instagram profile '{username}' not found.")
        return None
    
    except Exception as e:
        print(f"Error scraping Instagram: {e}")
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
