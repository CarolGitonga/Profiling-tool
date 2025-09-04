import requests
from bs4 import BeautifulSoup

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

