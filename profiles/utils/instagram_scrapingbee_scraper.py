import os, re, requests, logging, json
from bs4 import BeautifulSoup
from django.conf import settings
from django.utils import timezone
from textblob import TextBlob
from profiles.models import Profile, RawPost

logger = logging.getLogger(__name__)

def scrape_instagram_posts_scrapingbee(username: str, max_posts: int = 10):
    """
    Fetch Instagram posts using ScrapingBee with auto fallback chain:
    → Normal → Premium Proxy → Stealth Proxy.
    Saves captions, likes, comments, and sentiment into RawPost.
    """
    api_key = getattr(settings, "SCRAPINGBEE_API_KEY", None)
    if not api_key:
        logger.error(" SCRAPINGBEE_API_KEY not set in settings.py")
        return []

    proxy_url = "https://app.scrapingbee.com/api/v1/"
    target_url = f"https://www.instagram.com/{username}/"

    # --- Base parameters ---
    params = {
        "api_key": api_key,
        "url": target_url,
        "render_js": "true",
        "block_resources": "false",
        "wait": "5000",
    }

    response = None
    captions = []

    try:
        # NORMAL REQUEST
        try:
            logger.info(f"Fetching {username} (Stage 1: normal)...")
            response = requests.get(proxy_url, params=params, timeout=60)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if "Redirected to login" in str(e) or getattr(response, "status_code", 0) == 500:
                # PREMIUM PROXY RETRY
                logger.warning(f"Retrying {username} with premium proxy (Stage 2)...")
                params["premium_proxy"] = "true"
                params["wait"] = "8000"
                response = requests.get(proxy_url, params=params, timeout=90)
                response.raise_for_status()
            else:
                raise

        # If still login blocked or 500 error → escalate to stealth proxy
        if "login" in response.text.lower() or response.status_code == 500:
            # STEALTH PROXY RETRY
            logger.warning(f"🕵️ Retrying {username} with stealth proxy (Stage 3)...")
            params.pop("premium_proxy", None)
            params["stealth_proxy"] = "true"
            params["wait"] = "10000"
            response = requests.get(proxy_url, params=params, timeout=120)
            response.raise_for_status()

        # --- Parse HTML response ---
        soup = BeautifulSoup(response.text, "html.parser")
        db_profile = Profile.objects.filter(username=username, platform="Instagram").first()
        if not db_profile:
            logger.warning(f"No Profile found for {username}. Skipping save.")
            return []

        # 1: __NEXT_DATA__ JSON
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
                    )
                    likes = node_data.get("edge_liked_by", {}).get("count", 0)
                    comments = node_data.get("edge_media_to_comment", {}).get("count", 0)
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

                logger.info(f"✅ Saved {len(captions)} posts for {username} via __NEXT_DATA__.")
                return captions

            except Exception as e:
                logger.warning(f"⚠️ Failed to parse __NEXT_DATA__ JSON for {username}: {e}")

        # 2: Fallback to <script type="application/ld+json">
        json_scripts = soup.find_all("script", type="application/ld+json")
        for js in json_scripts[:max_posts]:
            text = js.get_text(strip=True)
            if not text:
                continue

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

        if captions:
            logger.info(f"Saved {len(captions)} posts for {username} via fallback JSON.")
        else:
            logger.warning(f"No post data found for {username}, even after stealth retry.")

        return captions

    except Exception as e:
        logger.exception(f"ScrapingBee fetch failed for {username}: {e}")
        return []
