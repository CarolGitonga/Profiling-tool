import re
import json
import logging
import requests, urllib.parse
from bs4 import BeautifulSoup
from datetime import datetime
from textblob import TextBlob
from django.conf import settings
from django.utils import timezone
from profiles.models import Profile, RawPost

logger = logging.getLogger(__name__)

def scrape_instagram_posts_scrapingbee(username: str, max_posts: int = 10):
    """
    🐝 Scrape public Instagram posts using ScrapingBee.
    - Uses stealth + premium proxies automatically
    - Retries gracefully across proxies and timeouts
    - Saves captions, likes, comments, timestamps, and sentiment into RawPost
    """

    api_key = getattr(settings, "SCRAPINGBEE_API_KEY", None)
    if not api_key:
        logger.error("❌ SCRAPINGBEE_API_KEY missing from Django settings.")
        return []

    proxy_url = "https://app.scrapingbee.com/api/v1/"
    target_url = f"https://www.instagram.com/{username}/"

    # Rotate countries if one is blocked or 500s
    country_codes = ["us", "fr", "de"]
    captions = []
    db_profile = Profile.objects.filter(username=username, platform="Instagram").first()

    if not db_profile:
        logger.warning(f"⚠️ No Profile found for {username}. Skipping save.")
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    # --------------------------------------------
    #  STEP 1: Try ScrapingBee with fallback logic
    # --------------------------------------------
    for country in country_codes:
        params = {
            "api_key": api_key,
            "url": urllib.parse.unquote(target_url),
            "render_js": "true",
            "stealth_proxy": "true",
            "premium_proxy": "true",
            "country_code": country,
            "block_resources": "true",
            "wait_browser": "networkidle",
        }

        try:
            logger.info(f"🌍 [{country.upper()}] Fetching Instagram for {username}...")
            response = requests.get(proxy_url, params=params, headers=headers, timeout=180)

            if response.status_code == 429:
                logger.warning(f"⚠️ Rate limit hit in {country.upper()}. Retrying next proxy...")
                continue

            if response.status_code in (403, 500):
                logger.warning(f"⚠️ Proxy {country.upper()} blocked or failed ({response.status_code}). Trying next...")
                continue

            if response.status_code == 400:
                logger.error(f"❌ Bad Request: Likely double-encoded URL. Check params.")
                logger.debug(f"Request URL: {response.url}")
                continue

            response.raise_for_status()

            html = response.text
            if "login" in html.lower() or "challenge" in html.lower():
                logger.warning(f"⚠️ {username}: Login challenge or cookie wall detected in {country.upper()}.")
                continue

            soup = BeautifulSoup(html, "html.parser")

            # -------------------------------
            #  STEP 2: Try __NEXT_DATA__ JSON
            # -------------------------------
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

                    if captions:
                        logger.info(f"✅ Saved {len(captions)} posts for {username} via __NEXT_DATA__ JSON.")
                        return captions

                except Exception as e:
                    logger.warning(f"⚠️ Failed to parse __NEXT_DATA__ JSON for {username}: {e}")

            # -----------------------------------------------
            #  STEP 3: Fallback to <script type='ld+json'>
            # -----------------------------------------------
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
                logger.info(f"✅ Saved {len(captions)} posts for {username} via fallback JSON ({country.upper()}).")
                return captions

        except requests.exceptions.RequestException as e:
            logger.warning(f"⚠️ {country.upper()} proxy failed for {username}: {e}")
            continue

        except Exception as e:
            logger.exception(f"❌ Unexpected error scraping {username} via {country.upper()}: {e}")
            continue

    # If all proxies failed
    logger.error(f"❌ All ScrapingBee proxies failed for {username}.")
    return captions
