import logging
from celery import shared_task
from django.db import transaction

from profiles.utils.twitter_scrapingbee_scraper import scrape_twitter_profile
from .utils.tiktok_scraper import scrape_tiktok_profile
from .utils.instagram_scraper import scrape_instagram_profile
from .models import BehavioralAnalysis, Profile, RawPost, SocialMediaAccount
import random
import pandas as pd
import re
from textblob import TextBlob
from django.utils import timezone
from profiles.utils.instagram_scrapingbee_scraper import scrape_instagram_posts_scrapingbee

logger = logging.getLogger(__name__)


def ensure_behavioral_record(profile):
    """Ensure a BehavioralAnalysis record exists for the given profile."""
    BehavioralAnalysis.objects.get_or_create(profile=profile)


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="twitter")
def scrape_twitter_task(self, username: str) -> dict:
    """
    Celery task: Scrape Twitter profile via ScrapingBee and save to DB.
    Retries automatically on transient errors (network, rate limit).
    """
    try:
        result = scrape_twitter_profile(username)

        profile_data = result.get("profile", {})
        posts = result.get("recent_posts", [])

        # Handle scrape errors
        if "error" in profile_data:
            reason = profile_data["error"]
            logger.warning(f"Twitter scrape failed for {username}: {reason}")
            raise Exception(reason)

        # --- Save Profile ---
        profile, _ = Profile.objects.get_or_create(
            username=username,
            platform="Twitter",
        )
        profile.full_name = profile_data.get("username", username)
        profile.avatar_url = profile_data.get("profile_image")
        profile.save()

        # --- Save SocialMediaAccount ---
        SocialMediaAccount.objects.update_or_create(
            profile=profile,
            platform="Twitter",
            defaults={
                "bio": profile_data.get("description", ""),
                "followers": 0,  # Twitter follower count not easily parsed from og:meta
                "following": 0,
                "posts_collected": len(posts),
                "is_private": False,
                "external_url": profile_data.get("url"),
            },
        )

        # --- Save Raw Tweets ---
        saved_count = 0
        for tweet in posts:
            caption = tweet.get("text", "")
            timestamp = tweet.get("timestamp", timezone.now())
            sentiment = round(TextBlob(caption).sentiment.polarity, 2)

            RawPost.objects.update_or_create(
                profile=profile,
                content=caption[:500],
                platform="Twitter",
                defaults={
                    "likes": 0,  # optional: ScrapingBee doesn’t easily expose this
                    "comments": 0,
                    "sentiment_score": sentiment,
                    "timestamp": timestamp,
                },
            )
            saved_count += 1

        logger.info(f"✅ Saved {saved_count} tweets for {username}")

        # --- Behavioral Analysis ---
        ensure_behavioral_record(profile)
        perform_behavioral_analysis.delay(profile.id)
        logger.info(f"✅ Behavioral record ensured for {username} (Twitter)")

        return {"success": True, "username": username, "platform": "Twitter"}

    except Exception as e:
        logger.exception(f"Twitter scraping error for {username}")
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for Twitter scrape: {username}")
            return {
                "success": False,
                "username": username,
                "platform": "Twitter",
                "reason": str(e),
            }


@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="tiktok")
def scrape_tiktok_task(self, username: str) -> dict:
    """
    Celery task: Scrape TikTok profile via ScrapingBee and save to DB.
    Retries automatically on transient errors (network, rate limit).
    """
    try:
        result = scrape_tiktok_profile(username)

        # Handle success
        if result.get("success"):
            logger.info(f"TikTok scrape succeeded for {username}")
            profile, _ = Profile.objects.get_or_create(
                username=username,
                platform="TikTok"
            )
            # Update profile basic info
            profile.full_name = result.get("full_name", "")
            profile.avatar_url = result.get("avatar_url")
            profile.save()

            # Update social account data
            SocialMediaAccount.objects.update_or_create(
                profile=profile,
                platform="TikTok",
                defaults={
                    "bio": result.get("bio", ""),
                    "followers": result.get("followers", 0),
                    "following": result.get("following", 0),
                    "posts_collected": result.get("posts", 0),
                    "is_private": result.get("is_private", False),
                    "external_url": result.get("external_url"),
                },
            )
            # --- Save Raw Posts (for Behavioral Dashboard) ---
            posts = result.get("posts", [])
            saved_count = 0
            for post in posts:
                caption = post.get("caption") or ""
                likes = int(post.get("likes", 0))
                comments = int(post.get("comments", 0))
                timestamp = post.get("timestamp") or timezone.now()
                # Compute sentiment for caption
                sentiment = round(TextBlob(caption).sentiment.polarity, 2)

                RawPost.objects.update_or_create(
                    profile=profile,
                    content=caption[:500],
                    platform="TikTok",
                    defaults={
                        "likes": likes,
                        "comments": comments,
                        "sentiment_score": sentiment,
                        "timestamp": timestamp,
                    },
                )
                saved_count += 1
            logger.info(f"✅ Saved {saved_count} TikTok posts for {username}")

            #Create behavioral record
            ensure_behavioral_record(profile)
            perform_behavioral_analysis.delay(profile.id)
            logger.info(f"✅ Behavioral record ensured for {username} (TikTok)")
            return {"success": True, "username": username, "platform": "TikTok"}

        # Handle explicit scrape failure (returned by scraper)
        reason = result.get("reason") or result.get("error") or "Unknown error"
        logger.warning(f"TikTok scrape failed for {username}: {reason}")
        raise Exception(reason)

    except Exception as e:
        logger.exception(f"TikTok scraping error for {username}")
        try:
            # Exponential backoff retries: 60s, 120s, 240s...
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for TikTok scrape: {username}")
            return {
                "success": False,
                "username": username,
                "platform": "TikTok",
                "reason": str(e)
            }

@shared_task(bind=True, max_retries=5, default_retry_delay=60, queue="instagram")
def scrape_instagram_task(self, username: str) -> dict:
    """
    Celery task: Scrape Instagram profile and save to DB.
    Retries only on temporary errors (rate limiting, network issues).
    Permanent errors (invalid/private/deleted accounts) are recorded once.
    """
    try:
        data = scrape_instagram_profile(username)

        # Handle permanent failures (invalid, deleted, private, no data)
        if not data or (isinstance(data, dict) and "error" in data):
            reason = data.get("error") if isinstance(data, dict) else "no data"
            logger.warning(f"Permanent failure scraping {username}: {reason}")

            # Store minimal record to avoid retrying forever
            with transaction.atomic():
                profile, _ = Profile.objects.get_or_create(
                    username=username,
                    platform="Instagram",
                )
                profile.full_name = ""
                profile.avatar_url = None
                profile.save()

                SocialMediaAccount.objects.update_or_create(
                    profile=profile,
                    platform="Instagram",
                    defaults={
                        "bio": "",
                        "followers": 0,
                        "following": 0,
                        "posts_collected": 0,
                        "is_private": True,  # assume private if no data
                        "external_url": None,
                    },
                )

            return {"success": False, "username": username, "platform": "Instagram", "reason": reason}

        # Valid scrape → save full profile
        with transaction.atomic():
            profile, _ = Profile.objects.get_or_create(username=username, platform="Instagram")
            profile.full_name = data.get("full_name", "")
            profile.avatar_url = data.get("profile_pic_url")
            profile.save()

            SocialMediaAccount.objects.update_or_create(
                profile=profile,
                platform="Instagram",
                defaults={
                    "bio": data.get("bio", ""),
                    "followers": data.get("followers", 0),
                    "following": data.get("following", 0),
                    "posts_collected": data.get("posts", 0),
                    "is_private": data.get("is_private", False),
                    "external_url": data.get("external_url"),
                },
            )
            # Create behavioral record
            ensure_behavioral_record(profile)
            perform_behavioral_analysis.delay(profile.id)
            logger.info(f"✅ Behavioral record ensured for {username} (Instagram)")

        return {"success": True, "username": username, "platform": "Instagram"}

    except Exception as e:
        err_msg = str(e)
        logger.exception(f"Instagram scraping failed for {username}: {err_msg}")

        try:
            # Retry only on temporary errors
            if "Please wait a few minutes" in err_msg or "401 Unauthorized" in err_msg:
               wait_time = 600  # 10 minutes
               logger.warning(f"Rate-limit block for {username}, retrying in {wait_time//60} minutes")
               raise self.retry(exc=e, countdown=wait_time)


            if "429" in err_msg or "temporarily unavailable" in err_msg:
                wait_time = random.randint(60, 180)  # 1-3 minutes
                logger.warning(f"Temporary error for {username}, retrying in {wait_time} seconds")
                raise self.retry(exc=e, countdown=wait_time)

            # For all other errors (invalid username, private, deleted), mark as permanent
            logger.error(f"Permanent error for {username}: {err_msg}")
            return {"success": False, "username": username, "platform": "Instagram", "reason": err_msg}

        except self.MaxRetriesExceededError:
            return {"error": err_msg, "username": username, "platform": "Instagram"}
    
@shared_task(bind=True, queue="default")
def perform_behavioral_analysis(self, profile_id):
    """Analyze user behavior, sentiment, and interests (multi-platform)."""

    try:
        profile = Profile.objects.get(id=profile_id)
        analysis, _ = BehavioralAnalysis.objects.get_or_create(profile=profile)
        sm = SocialMediaAccount.objects.filter(profile=profile, platform=profile.platform).first()
        posts_qs = RawPost.objects.filter(profile=profile)

        # Shared helpers
        def compute_posting_patterns(posts_df):
            if posts_df.empty:
                return None, []
            posts_df["hour"] = posts_df["timestamp"].apply(lambda x: x.hour)
            posts_df["weekday"] = posts_df["timestamp"].apply(lambda x: x.strftime("%A"))
            avg_post_time = f"{int(posts_df['hour'].mode()[0])}:00"
            most_active_days = posts_df["weekday"].value_counts().head(3).index.tolist()
            return avg_post_time, most_active_days

        def extract_keywords(text):
            hashtags = re.findall(r"#(\w+)", text)
            words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
            all_keywords = hashtags + words
            return pd.Series(all_keywords).value_counts().head(10).to_dict() if all_keywords else {}

        def compute_sentiment_distribution(captions):
            sentiment_distribution = {"positive": 0, "neutral": 0, "negative": 0}
            sentiments = []
            for caption in captions:
                sentiment = round(TextBlob(str(caption)).sentiment.polarity, 2)
                sentiments.append(sentiment)
                if sentiment > 0.05:
                    sentiment_distribution["positive"] += 1
                elif sentiment < -0.05:
                    sentiment_distribution["negative"] += 1
                else:
                    sentiment_distribution["neutral"] += 1
            overall_score = round(
                (sentiment_distribution["positive"] - sentiment_distribution["negative"])
                / max(1, sum(sentiment_distribution.values())),
                2,
            )
            return sentiments, sentiment_distribution, overall_score

        # =============================
        # 🧩 PLATFORM: GITHUB
        # =============================
        if profile.platform == "GitHub":
            followers = sm.followers if sm else 0
            following = sm.following if sm else 0
            repos = getattr(sm, "public_repos", 0)

            follower_ratio = round(followers / (following or 1), 2)
            influence_score = round((followers * 0.6) + (repos * 0.4), 2)

            if repos > 50:
                activity_pattern = "Extremely Active Developer"
            elif repos > 20:
                activity_pattern = "Active Developer"
            elif repos > 5:
                activity_pattern = "Occasional Contributor"
            else:
                activity_pattern = "Low GitHub Activity"

            keywords = []
            if sm and sm.bio:
                keywords += re.findall(r"\b[a-zA-Z]{4,}\b", sm.bio.lower())
            if profile.company:
                keywords.append(profile.company.lower())
            if profile.blog:
                keywords.append("blog")
            keyword_freq = pd.Series(keywords).value_counts().head(10).to_dict() if keywords else {}

            sentiment_score = round(TextBlob(sm.bio).sentiment.polarity, 2) if sm and sm.bio else 0.0

            analysis.avg_post_time = "N/A"
            analysis.most_active_days = ["Varies"]
            analysis.sentiment_score = sentiment_score
            analysis.top_keywords = keyword_freq
            analysis.geo_locations = [profile.location or "Unknown"]
            analysis.network_size = followers + following
            analysis.influence_score = influence_score
            analysis.activity_pattern = activity_pattern
            analysis.analyzed_at = timezone.now()
            analysis.save()

            logger.info(f"✅ GitHub behavioral analysis done for {profile.username}")
            return {"success": True, "profile": profile.username}

        # =============================
        # 🧩 PLATFORM: INSTAGRAM
        # =============================
        if profile.platform == "Instagram":
            captions = list(posts_qs.values_list("content", flat=True))
            used_scrapingbee = False

            if not captions:
                # fallback to scrapingbee if no RawPosts
                captions = scrape_instagram_posts_scrapingbee(profile.username, max_posts=10)
                used_scrapingbee = True

            sentiments, sentiment_distribution, sentiment_score = compute_sentiment_distribution(captions)
            text_data = " ".join(captions + ([sm.bio] if sm and sm.bio else []))
            keyword_freq = extract_keywords(text_data)
            avg_post_time, most_active_days = compute_posting_patterns(
                pd.DataFrame(list(posts_qs.values("timestamp"))) if posts_qs.exists() else pd.DataFrame()
            )

            network_size = (sm.followers + sm.following) if sm else 0
            geo_locations = []
            if sm and sm.bio:
                if "nairobi" in sm.bio.lower():
                    geo_locations.append("Nairobi")
                if "kenya" in sm.bio.lower():
                    geo_locations.append("Kenya")

            analysis.avg_post_time = avg_post_time
            analysis.most_active_days = most_active_days
            analysis.sentiment_score = sentiment_score
            analysis.top_keywords = keyword_freq
            analysis.geo_locations = geo_locations
            analysis.network_size = network_size
            analysis.sentiment_distribution = sentiment_distribution
            analysis.used_scrapingbee = used_scrapingbee
            analysis.influence_score = round(network_size * (sentiment_score + 1), 2)
            analysis.analyzed_at = timezone.now()
            analysis.save()

            logger.info(f"✅ Instagram behavioral analysis done for {profile.username}")
            return {"success": True, "profile": profile.username}

        # =============================
        # 🧩 PLATFORM: TIKTOK
        # =============================
        if profile.platform == "TikTok":
            captions = list(posts_qs.values_list("content", flat=True))
            sentiments, sentiment_distribution, sentiment_score = compute_sentiment_distribution(captions)

            # Aggregate keyword extraction from captions + bio
            text_data = " ".join(captions + ([sm.bio] if sm and sm.bio else []))
            keyword_freq = extract_keywords(text_data)

            # Activity patterns
            avg_post_time, most_active_days = compute_posting_patterns(
                pd.DataFrame(list(posts_qs.values("timestamp"))) if posts_qs.exists() else pd.DataFrame()
            )

            # Influence = weighted by engagement
            likes = sum(list(posts_qs.values_list("likes", flat=True))) if posts_qs.exists() else 0
            comments = sum(list(posts_qs.values_list("comments", flat=True))) if posts_qs.exists() else 0
            total_engagement = likes + comments
            followers = sm.followers if sm else 0
            following = sm.following if sm else 0
            influence_score = round((followers * 0.7) + (total_engagement * 0.3 / max(1, len(captions))), 2)

            geo_locations = []
            if sm and sm.bio:
                if "nairobi" in sm.bio.lower():
                    geo_locations.append("Nairobi")
                if "kenya" in sm.bio.lower():
                    geo_locations.append("Kenya")

            analysis.avg_post_time = avg_post_time
            analysis.most_active_days = most_active_days
            analysis.sentiment_score = sentiment_score
            analysis.top_keywords = keyword_freq
            analysis.geo_locations = geo_locations
            analysis.network_size = followers + following
            analysis.sentiment_distribution = sentiment_distribution
            analysis.influence_score = influence_score
            analysis.used_scrapingbee = False
            analysis.analyzed_at = timezone.now()
            analysis.save()

            logger.info(f"✅ TikTok behavioral analysis done for {profile.username}")
            return {"success": True, "profile": profile.username}

        # =============================
        # 🧩 GENERIC FALLBACK (Twitter, etc.)
        # =============================
        captions = list(posts_qs.values_list("content", flat=True))
        sentiments, sentiment_distribution, sentiment_score = compute_sentiment_distribution(captions)
        keyword_freq = extract_keywords(" ".join(captions))
        avg_post_time, most_active_days = compute_posting_patterns(
            pd.DataFrame(list(posts_qs.values("timestamp"))) if posts_qs.exists() else pd.DataFrame()
        )
        network_size = (sm.followers + sm.following) if sm else 0

        analysis.avg_post_time = avg_post_time
        analysis.most_active_days = most_active_days
        analysis.sentiment_score = sentiment_score
        analysis.top_keywords = keyword_freq
        analysis.geo_locations = []
        analysis.network_size = network_size
        analysis.sentiment_distribution = sentiment_distribution
        analysis.influence_score = round(network_size * (sentiment_score + 1), 2)
        analysis.analyzed_at = timezone.now()
        analysis.save()

        logger.info(f"✅ Generic behavioral analysis done for {profile.username}")
        return {"success": True, "profile": profile.username}

    except Exception as e:
        logger.exception(f"Behavioral analysis failed for profile {profile_id}: {e}")
        return {"success": False, "error": str(e)}


