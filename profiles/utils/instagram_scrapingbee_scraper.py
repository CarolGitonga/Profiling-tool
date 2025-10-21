import os, re, requests, logging
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone
from profiles.models import Profile, RawPost
from textblob import TextBlob
import json

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

    proxy_url = f"https://app.scrapingbee.com/api/v1/"
    target_url = f"https://www.instagram.com/{username}/"

    params = {
        "api_key": api_key,
        "url": target_url,
        "render_js": "true",
        "wait": "8000",
    }

    try:
        response = requests.get(proxy_url, params=params, timeout=60)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

       # ✅ Extract JSON inside <script id="__NEXT_DATA__">
        script_tag = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script_tag:
            logger.warning(f"No __NEXT_DATA__ found for {username}")
            return []
        
        raw_json = script_tag.string or script_tag.text
        data = json.loads(raw_json)

        # Navigate to the user's post data
        posts_data = (
            data.get("props", {})
                .get("pageProps", {})
                .get("graphql", {})
                .get("user", {})
                .get("edge_owner_to_timeline_media", {})
                .get("edges", [])
        )
        if not posts_data:
            logger.warning(f"No posts found in __NEXT_DATA__ for {username}")
            return []
        
        db_profile = Profile.objects.filter(username=username, platform="Instagram").first()
        if not db_profile:
            logger.warning(f"No Profile object found for {username}.")
            return []

        results = []
        for edge in posts_data[:max_posts]:
            node = edge.get("node", {})
            caption = (
                node.get("edge_media_to_caption", {})
                .get("edges", [{}])[0]
                .get("node", {})
                .get("text", "")
            )
            likes = node.get("edge_liked_by", {}).get("count", 0)
            comments = node.get("edge_media_to_comment", {}).get("count", 0)
            timestamp = timezone.now()
            sentiment = round(TextBlob(caption).sentiment.polarity, 2)

            RawPost.objects.update_or_create(
                profile=db_profile,
                content=caption[:500],
                platform="Instagram",
                defaults={
                    "likes": likes,
                    "comments": comments,
                    "sentiment_score": sentiment,
                    "timestamp": timestamp,
                },
            )
            results.append((caption, sentiment))

    
        logger.info(f"✅ Saved {len(results)} posts for {username} via ScrapingBee (__NEXT_DATA__).")
        return results

    except Exception as e:
        logger.exception(f"ScrapingBee Instagram scrape failed for {username}: {e}")
        return []
