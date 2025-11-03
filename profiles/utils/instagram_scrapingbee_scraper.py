import logging, json, re
from bs4 import BeautifulSoup
from datetime import datetime
from textblob import TextBlob
from django.conf import settings
from django.utils import timezone
from scrapingbee import ScrapingBeeClient
from profiles.models import Profile, RawPost

logger = logging.getLogger(__name__)

def scrape_instagram_posts_scrapingbee(username: str, max_posts: int = 10):
    """
    🐝 Instagram scraping with ScrapingBee official client.
    - Automatically handles URL encoding and rendering
    - Uses premium proxy & fallback regions
    - Extracts captions, likes, comments, timestamps, and sentiment
    """

    api_key = getattr(settings, "SCRAPINGBEE_API_KEY", None)
    if not api_key:
        logger.error("❌ SCRAPINGBEE_API_KEY missing from Django settings.")
        return []

    client = ScrapingBeeClient(api_key=api_key)
    target_url = f"https://www.instagram.com/{username}/"
    country_codes = ["us", "fr", "de", "ke"]
    captions = []

    db_profile = Profile.objects.filter(username=username, platform="Instagram").first()
    if not db_profile:
        logger.warning(f"⚠️ No Profile found for {username}. Skipping save.")
        return []

    for country in country_codes:
        try:
            logger.info(f"🌍 [{country.upper()}] Fetching Instagram for {username}...")

            response = client.get(
                target_url,
                params={
                    "render_js": "true",
                    "premium_proxy": "true",
                    "country_code": country,
                    "block_resources": "true",
                    "wait": "3000" 

                },
                timeout=180,
            )

            if response.status_code == 429:
                logger.warning(f"⚠️ Rate limit reached for {country.upper()}. Retrying next region...")
                continue
            if not response.ok:
                logger.warning(f"❌ ScrapingBee failed ({response.status_code}) for {country.upper()}")
                continue

            html = response.content.decode("utf-8", errors="ignore")
            if "login" in html.lower() or "challenge" in html.lower():
                logger.warning(f"⚠️ Login wall detected for {username} ({country.upper()})")
                continue

            soup = BeautifulSoup(html, "html.parser")

            # --- Parse __NEXT_DATA__ JSON ---
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
                        ts = node_data.get("taken_at_timestamp")

                        try:
                            timestamp = datetime.fromtimestamp(int(ts), tz=timezone.utc) if ts else timezone.now()
                        except Exception:
                            timestamp = timezone.now()

                        sentiment = round(TextBlob(re.sub(r"[^\x00-\x7F]+", " ", caption)).sentiment.polarity, 2)

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

                    logger.info(f"✅ Saved {len(captions)} posts for {username} via ScrapingBeeClient.")
                    return captions

                except Exception as e:
                    logger.warning(f"⚠️ Failed to parse JSON for {username}: {e}")

        except Exception as e:
            logger.warning(f"⚠️ {country.upper()} proxy failed for {username}: {e}")
            continue

    logger.error(f"❌ All ScrapingBee regions failed for {username}.")
    return captions
