import requests
from datetime import datetime
from .models import Profile, SocialMediaAccount
from bs4 import BeautifulSoup
from django.conf import settings

api_key = settings.TWITTER_API_KEY

def scrape_twitter_bio(username):
    url = f"https://x.com/{username}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            bio = soup.find('meta', {'name': 'description'})
            return bio['content'] if bio else 'N/A'
    except Exception as e:
        print(f"Error scraping: {e}")
    return 'Bio not found'

def unscrape_twitter_bio(username: str) -> bool:
    """
    Simulates "unscraping" by removing cached/stored Twitter bio data.
    Deletes SocialMediaAccount entries tied to Twitter for the given profile.
    """
    from .models import Profile, SocialMediaAccount
    try:
        profile = Profile.objects.get(username=username, platform='Twitter')
        SocialMediaAccount.objects.filter(profile=profile, platform='Twitter').delete()
        return True
    except Profile.DoesNotExist:
        return False
    
def scrape_github_profile(username):
    url = f"https://api.github.com/users/{username}"
    try: 
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            return {
                'name': data.get('name') or username,
                'bio': data.get('bio') or "No bio provided.",
                'url': data.get('html_url'),
                'created_at': data.get('created_at'),
                'public_repos': data.get('public_repos'),
                'followers': data.get('followers'),
                'following': data.get('following'),
                'location': data.get('location'),
                'company': data.get('company'),
                'blog': data.get('blog')
            }
        
    except Exception as e:
        print(f"Error scraping GitHub via API: {e}")
    return {
        'name': username,
        'bio': "GitHub user not found.",
        'url': f"https://github.com/{username}",
        'created_at': None,
        'public_repos': 0,
        'followers': 0,
        'following': 0,
        'location': None,
        'company': None,
        'blog': None
    }

def unscrape_github_profile(username):
    try:
        profile = Profile.objects.get(username=username, platform='GitHub')
        SocialMediaAccount.objects.filter(profile=profile, platform='GitHub').delete()
        return True
    except Profile.DoesNotExist:
        return False

