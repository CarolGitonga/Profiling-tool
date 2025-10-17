import os, re, requests, logging
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone
from profiles.models import Profile, RawPost
from textblob import TextBlob

logger = logging.getLogger(__name__)

def scrape_instagram_posts_scrapingbee(username: str, max_posts: int = 10):
    """
    Fetch Instagram posts via ScrapingBee (as fallback for Instaloader).
    Saves captions, likes, comments, and sentiment into RawPost.
    """
    api_key = getattr(settings, "SCRAPINGBEE_API_KEY", None)
    if not api_key:
        logger.error("SCRAPINGBEE_API_KEY not set in settings.py")
        return []

    url = f"https://app.scrapingbee.com/api/v1/"
    target_url = f"https://www.instagram.com/{username}/"

    params = {
        "api_key": api_key,
        "url": target_url,
        "render_js": "true",
        "wait": "3000",
    }

    try:
        response = requests.get(url, params=params, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        # Extract JSON inside <script type="application/ld+json">
        json_scripts = soup.find_all("script", type="application/ld+json")
        captions = []
        db_profile = Profile.objects.filter(username=username, platform="Instagram").first()

        if not db_profile:
            logger.warning(f"No Profile found for {username}.")
            return []

        for js in json_scripts[:max_posts]:
            text = js.get_text(strip=True)
            if not text:
                continue

            # Try to extract caption, likes, comments
            caption_match = re.search(r'"caption":"(.*?)"', text)
            likes_match = re.search(r'"interactionCount":(\d+)', text)
            comments_match = re.search(r'"commentCount":(\d+)', text)

            caption = caption_match.group(1) if caption_match else ""
            likes = int(likes_match.group(1)) if likes_match else 0
            comments = int(comments_match.group(1)) if comments_match else 0

            sentiment = round(TextBlob(caption).sentiment.polarity, 2)

            RawPost.objects.update_or_create(
                profile=db_profile,
                content=caption[:500],
                platform="Instagram",
                defaults={
                    "likes": likes,
                    "comments": comments,
                    "sentiment_score": sentiment,
                    "timestamp": timezone.now(),
                },
            )

            captions.append((caption, sentiment))

        logger.info(f"✅ Saved {len(captions)} posts for {username} via ScrapingBee")
        return captions

    except Exception as e:
        logger.exception(f"ScrapingBee fetch failed for {username}: {e}")
        return []
