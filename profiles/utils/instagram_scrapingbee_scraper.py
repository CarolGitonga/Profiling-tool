import os, re, requests, logging, json, urllib.parse
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone
from textblob import TextBlob
from datetime import datetime
from profiles.models import Profile, RawPost

logger = logging.getLogger(__name__)

def scrape_instagram_posts_scrapingbee(username: str, max_posts: int = 10):
    """
    Scrape public Instagram posts using ScrapingBee.
    Automatically retries with premium proxy if stealth fails.
    Saves captions, likes, comments, timestamps, and sentiment into RawPost.
    """
    api_key = getattr(settings, "SCRAPINGBEE_API_KEY", None)
    if not api_key:
        logger.error("❌ SCRAPINGBEE_API_KEY not found in settings.")
        return []

    target_url = f"https://www.instagram.com/{username}/"
    proxy_url = "https://app.scrapingbee.com/api/v1/"

    # ✅ Initial parameters
    params = {
        "api_key": api_key,
        "url": target_url,
        "render_js": "true",
        "stealth_proxy": "true",          # Force stealth first
        "premium_proxy": "true", 
        "country_code": "ke",
        "block_resources": "true",
        "wait_browser": "networkidle",    # ✅ use only this one
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    captions = []
    response = None

    try:
        # --- Primary Request (stealth proxy)
        logger.info(f"🕵️ Fetching Instagram for {username} (stealth)...")
        response = requests.get(proxy_url, params=params, headers=headers, timeout=90)
        if response.status_code == 400:
            # Retry with premium proxy if ScrapingBee rejected params
            logger.warning(f"⚠️ Stealth proxy rejected for {username}, retrying with premium proxy...")
            params.pop("stealth_proxy", None)
            params["premium_proxy"] = "true"
            response = requests.get(proxy_url, params=params, headers=headers, timeout=120)
        response.raise_for_status()

        html = response.text
        if "login" in html.lower():
            logger.warning(f"⚠️ {username}: Login page detected, Instagram blocked stealth proxy.")
            return []

        soup = BeautifulSoup(html, "html.parser")
        db_profile = Profile.objects.filter(username=username, platform="Instagram").first()
        if not db_profile:
            logger.warning(f"⚠️ No Profile found for {username}. Skipping save.")
            return []

        # --- Parse __NEXT_DATA__ (Primary JSON)
        script_tag = soup.find("script", id="__NEXT_DATA__")
        if script_tag:
            try:
                data = json.loads(script_tag.string)
                posts_data = (
                    data.get("props", {})
                    .get("pageProps", {})
                    .get("graphql", {})
                    .get("user", {})
                    .get("edge_owner_to_timeline_media", {})
                    .get("edges", [])
                )

                for node in posts_data[:max_posts]:
                    node_data = node.get("node", {})
                    caption = (
                        node_data.get("edge_media_to_caption", {})
                        .get("edges", [{}])[0]
                        .get("node", {})
                        .get("text", "")
                    ) or ""

                    likes = node_data.get("edge_liked_by", {}).get("count", 0)
                    comments = node_data.get("edge_media_to_comment", {}).get("count", 0)

                    # ✅ Extract real timestamp
                    ts = node_data.get("taken_at_timestamp")
                    try:
                        timestamp = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else timezone.now()
                    except Exception:
                        timestamp = timezone.now()

                    # ✅ Clean caption & sentiment
                    clean_caption = re.sub(r"[^\x00-\x7F]+", " ", caption)
                    sentiment = round(TextBlob(clean_caption).sentiment.polarity, 2)

                    RawPost.objects.update_or_create(
                        profile=db_profile,
                        content=caption[:500],
                        platform="Instagram",
                        timestamp=timestamp,
                        defaults={
                            "likes": likes,
                            "comments": comments,
                            "sentiment_score": sentiment,
                        },
                    )
                    captions.append((caption, sentiment))

                logger.info(f"✅ Saved {len(captions)} posts for {username} via __NEXT_DATA__.")
                return captions

            except Exception as e:
                logger.warning(f"⚠️ Failed to parse __NEXT_DATA__ JSON for {username}: {e}")

        # --- Fallback to <script type="application/ld+json">
        json_scripts = soup.find_all("script", type="application/ld+json")
        for js in json_scripts[:max_posts]:
            text = js.get_text(strip=True)
            if not text:
                continue

            caption_match = re.search(r'"caption":"(.*?)"', text)
            likes_match = re.search(r'"interactionCount":(\d+)', text)
            comments_match = re.search(r'"commentCount":(\d+)', text)
            time_match = re.search(r'"uploadDate":"([^"]+)"', text)

            caption = caption_match.group(1) if caption_match else ""
            likes = int(likes_match.group(1)) if likes_match else 0
            comments = int(comments_match.group(1)) if comments_match else 0
            try:
                timestamp = (
                    datetime.fromisoformat(time_match.group(1).replace("Z", "+00:00"))
                    if time_match
                    else timezone.now()
                )
            except Exception:
                timestamp = timezone.now()

            sentiment = round(TextBlob(caption).sentiment.polarity, 2)

            RawPost.objects.update_or_create(
                profile=db_profile,
                content=caption[:500],
                platform="Instagram",
                timestamp=timestamp,
                defaults={
                    "likes": likes,
                    "comments": comments,
                    "sentiment_score": sentiment,
                },
            )
            captions.append((caption, sentiment))

        if captions:
            logger.info(f"✅ Saved {len(captions)} posts for {username} via fallback JSON.")
        else:
            logger.warning(f"⚠️ No post data found for {username}, even after fallback.")
        return captions

    except Exception as e:
        logger.exception(f"❌ ScrapingBee fetch failed for {username}: {e}")
        return []
