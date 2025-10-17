import requests, re, logging
from bs4 import BeautifulSoup
from textblob import TextBlob
from django.utils import timezone
from profiles.models import Profile, RawPost
from django.conf import settings

logger = logging.getLogger(__name__)

def scrape_instagram_posts_scrapingbee(username: str, max_posts: int = 10):
    """
    Use ScrapingBee API to fetch and analyze Instagram posts.
    Returns sentiment distribution and saves RawPost entries.
    """
    api_key = settings.SCRAPINGBEE_API_KEY
    url = f"https://www.instagram.com/{username}/"
    api_url = f"https://app.scrapingbee.com/api/v1/?api_key={api_key}&url={url}&render_js=true"

    try:
        response = requests.get(api_url, timeout=30)
        if response.status_code != 200:
            logger.warning(f"ScrapingBee returned {response.status_code} for {username}")
            return {"success": False, "error": f"HTTP {response.status_code}"}

        soup = BeautifulSoup(response.text, "html.parser")
        captions = []

        # Instagram often stores captions inside <meta property="og:title"> or <script> tags
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = script.string
                if not data:
                    continue
                match = re.findall(r'"caption":\s*"([^"]+)"', data)
                captions.extend(match)
            except Exception:
                continue

        # Fall back: extract visible text patterns
        if not captions:
            all_text = soup.get_text(separator=" ")
            match = re.findall(r'"text":"([^"]+)"', all_text)
            captions.extend(match)

        captions = list(dict.fromkeys(captions))[:max_posts]
        if not captions:
            logger.warning(f"No captions found for {username}.")
            return {"success": False, "error": "No captions found"}

        profile = Profile.objects.filter(username=username, platform="Instagram").first()
        if not profile:
            logger.warning(f"No Profile found for {username}")
            return {"success": False, "error": "Profile not found"}

        # --- Sentiment Analysis ---
        sentiment_scores = {"positive": 0, "neutral": 0, "negative": 0}
        for caption in captions:
            sentiment = TextBlob(caption).sentiment.polarity
            if sentiment > 0.05:
                sentiment_scores["positive"] += 1
            elif sentiment < -0.05:
                sentiment_scores["negative"] += 1
            else:
                sentiment_scores["neutral"] += 1

            # Save RawPost to DB
            RawPost.objects.update_or_create(
                profile=profile,
                content=caption[:500],
                platform="Instagram",
                defaults={
                    "sentiment_score": sentiment,
                    "timestamp": timezone.now(),
                },
            )

        logger.info(f"✅ Saved {len(captions)} Instagram posts for {username} using ScrapingBee.")
        return {
            "success": True,
            "username": username,
            "platform": "Instagram",
            "posts_analyzed": len(captions),
            "sentiment_distribution": sentiment_scores,
        }

    except Exception as e:
        logger.exception(f"ScrapingBee Instagram error for {username}: {e}")
        return {"success": False, "error": str(e)}
