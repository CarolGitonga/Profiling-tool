import json, logging, re
from datetime import datetime
from textblob import TextBlob
from django.conf import settings
from django.utils import timezone
from scrapingbee import ScrapingBeeClient
from profiles.models import Profile, RawPost

logger = logging.getLogger(__name__)

def scrape_instagram_posts_scrapingbee(username: str, max_posts: int = 10):
    """
    🐝 Scrape Instagram posts using the public GraphQL API via ScrapingBee.
    Requires a valid INSTAGRAM_SESSION_ID cookie to bypass the login wall.
    """
    api_key = getattr(settings, "SCRAPINGBEE_API_KEY", None)
    session_id = getattr(settings, "INSTAGRAM_SESSION_ID", None)
    if not api_key or not session_id:
        logger.error("Missing ScrapingBee or Instagram session credentials.")
        return []

    client = ScrapingBeeClient(api_key=api_key)

    try:
        # Step 1: get user ID
        info_url = f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}"
        info_resp = client.get(
            info_url,
            headers={
                "cookie": f"sessionid={session_id};",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            },
            params={"render_js": "false"},
        )

        data = json.loads(info_resp.content.decode("utf-8"))
        user_id = data["data"]["user"]["id"]
        logger.info(f"Found IG user_id={user_id} for {username}")

        # Step 2: fetch posts via GraphQL
        query_hash = "58b6785bea111c67129decbe6a448951"
        variables = json.dumps({"id": user_id, "first": max_posts})
        gql_url = f"https://www.instagram.com/graphql/query/?query_hash={query_hash}&variables={variables}"

        gql_resp = client.get(
            gql_url,
            headers={
                "cookie": f"sessionid={session_id};",
                "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            },
            params={"render_js": "false"},
        )

        if not gql_resp.ok:
            logger.warning(f"GraphQL request failed ({gql_resp.status_code}) for {username}")
            return []

        posts_data = json.loads(gql_resp.content.decode("utf-8"))["data"]["user"]["edge_owner_to_timeline_media"]["edges"]

        db_profile = Profile.objects.filter(username=username, platform="Instagram").first()
        if not db_profile:
            logger.warning(f"No Profile found for {username}. Skipping DB save.")
            return []

        results = []
        for edge in posts_data:
            node = edge["node"]
            caption = (node.get("edge_media_to_caption", {}).get("edges", [{}])[0].get("node", {}).get("text", "")) or ""
            likes = node.get("edge_liked_by", {}).get("count", 0)
            comments = node.get("edge_media_to_comment", {}).get("count", 0)
            ts = node.get("taken_at_timestamp")
            timestamp = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else timezone.now()
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
            results.append((caption, sentiment))

        logger.info(f"✅ Saved {len(results)} posts for {username} via GraphQL ScrapingBee.")
        return results

    except Exception as e:
        logger.exception(f"❌ GraphQL ScrapingBee failed for {username}: {e}")
        return []
