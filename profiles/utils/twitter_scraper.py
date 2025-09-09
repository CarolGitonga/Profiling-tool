from django.conf import settings
import tweepy
from django.core.cache import cache

api_key = settings.TWITTER_API_KEY

def get_twitter_profile(username: str) -> dict:
    if not username:
        return None
    cache_key = f"twitter_profile_{username.lower()}"
    cached_profile = cache.get(cache_key)
    if cached_profile:
        print("Using cached Twitter data for", username)
        return cached_profile
    
    client = tweepy.Client(bearer_token=settings.TWITTER_BEARER_TOKEN)
    try:
        # Get user info
        user_response = client.get_user(
            username=username,
            user_fields=[
                "description", "created_at", "location", 
                "public_metrics", "verified", "profile_image_url", "name"
                ]
        )
        user = user_response.data
        if not user:
            print(f"No Twitter data found for {username}")
            return None
        
        profile_data = {
            'name': user.name,
            'bio': user.description,
            'created_at': user.created_at,
            'location': user.location,
            'followers_count': user.public_metrics["followers_count"],
            'following_count': user.public_metrics["following_count"],
            'verified': user.verified,
            'avatar_url': user.profile_image_url,
        }
        # Cache it for 1 hour (3600 seconds)
        cache.set(cache_key, profile_data, timeout=3600)
        return profile_data
    
    except tweepy.TweepyException as e:
        print("Error fetching Twitter profile:", e)
        return None

def unscrape_twitter_bio(username: str) -> bool:
    """
    Simulates "unscraping" by removing cached/stored Twitter bio data.
    Deletes SocialMediaAccount entries tied to Twitter for the given profile.
    """
    from profiles.models import Profile, SocialMediaAccount
    try:
        profile = Profile.objects.get(username=username, platform='Twitter')
        SocialMediaAccount.objects.filter(profile=profile, platform='Twitter').delete()
        return True
    except Profile.DoesNotExist:
        return False