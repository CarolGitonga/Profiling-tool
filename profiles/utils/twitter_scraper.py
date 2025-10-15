from profile import Profile
from django.conf import settings
import tweepy
from django.core.cache import cache
from django.utils import timezone
from profiles.models import RawPost

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

def fetch_and_store_tweets(username: str, client=None, limit: int = 10):
    """
    Fetch recent tweets from a user's timeline and save them to RawPost.
    """
    if not client:
        client = tweepy.Client(bearer_token=settings.TWITTER_BEARER_TOKEN)
        try:
            user = client.get_user(username=username)
            if not user.data:
                print(f" No Twitter user found for {username}")
                return []
            user_id = user.data.id

            tweets = client.get_users_tweets(
                id=user_id,
                max_results=limit,
                tweet_fields=["created_at", "public_metrics", "text"]
            )
            if not tweets.data:
                print(f"No recent tweets found for {username}")
                return []
            
            profile = Profile.objects.filter(username=username, platform="Twitter").first()
            if not profile:
                print(f" No Profile object found for {username} (Twitter). Skipping tweet save.")
                return []
            
            saved_tweets = []
            for tweet in tweets.data:
                content = tweet.text.strip()
                metrics = tweet.public_metrics or {}

                post, created = RawPost.objects.update_or_create(
                    profile=profile,
                    content=content,
                    platform="Twitter",
                    defaults={
                        "timestamp": tweet.created_at or timezone.now(),
                        "likes": metrics.get("like_count", 0),
                        "comments": metrics.get("reply_count", 0),
                    },
                )
                saved_tweets.append(post)
            print(f"Saved {len(saved_tweets)} tweets for {username}")
            return saved_tweets
        except tweepy.TweepyException as e:
            print(f"❌ Error fetching tweets for {username}: {e}")
            return []
        except Exception as e:
            print(f"⚠️ Unexpected error saving tweets for {username}: {e}")
            return []


def unscrape_twitter_bio(username: str) -> bool:
    """
    Deletes stored Twitter bio and posts from DB.
    """
    from profiles.models import SocialMediaAccount

    try:
        profile = Profile.objects.get(username=username, platform="Twitter")

        # Delete associated social data and posts
        SocialMediaAccount.objects.filter(profile=profile, platform="Twitter").delete()
        RawPost.objects.filter(profile=profile, platform="Twitter").delete()

        print(f"🗑️ Cleared Twitter bio and posts for {username}")
        return True

    except Profile.DoesNotExist:
        print(f"⚠️ Profile for {username} not found.")
        return False