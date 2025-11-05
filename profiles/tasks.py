import logging
import random
import re
import pandas as pd
from textblob import TextBlob
from celery import shared_task
from django.db import transaction
from django.utils import timezone

from profiles.models import BehavioralAnalysis, Profile, RawPost, SocialMediaAccount
from profiles.utils.twitter_scrapingbee_scraper import scrape_twitter_profile
from profiles.utils.tiktok_scraper import scrape_tiktok_profile
from profiles.utils.instagram_scraper import scrape_instagram_profile
from profiles.utils.instagram_scrapingbee_scraper import scrape_instagram_posts_scrapingbee
from profiles.utils.wordcloud import generate_wordcloud  # optional for debug
from .tasks import perform_behavioral_analysis  # ensures visibility if split later

logger = logging.getLogger(__name__)


# ==========================================================
# 🧠 Helper
# ==========================================================
def ensure_behavioral_record(profile):
    """Ensure a BehavioralAnalysis record exists for the given profile."""
    BehavioralAnalysis.objects.get_or_create(profile=profile)


# ==========================================================
# 🐦 TWITTER TASK
# ==========================================================
@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="twitter")
def scrape_twitter_task(self, username: str) -> dict:
    """Scrape Twitter profile via ScrapingBee and save to DB."""
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
        profile, _ = Profile.objects.get_or_create(username=username, platform="Twitter")
        profile.full_name = profile_data.get("name", username)
        profile.avatar_url = profile_data.get("profile_image")
        profile.save()

        # --- Save SocialMediaAccount ---
        SocialMediaAccount.objects.update_or_create(
            profile=profile,
            platform="Twitter",
            defaults={
                "bio": profile_data.get("description", ""),
                "followers": profile_data.get("followers", 0),
                "following": profile_data.get("following", 0),
                "posts_collected": len(posts),
                "is_private": False,
                "external_url": profile_data.get("url"),
            },
        )

        # --- Save Tweets ---
        saved_count = 0
        for tweet in posts:
            caption = tweet.get("text", "")
            timestamp = tweet.get("timestamp", timezone.now())
            sentiment = round(TextBlob(caption).sentiment.polarity, 2)

            RawPost.objects.update_or_create(
                profile=profile,
                content=caption[:500],
                platform="Twitter",
                timestamp=timestamp,
                defaults={
                    "likes": tweet.get("likes", 0),
                    "comments": tweet.get("replies", 0),
                    "sentiment_score": sentiment,
                },
            )
            saved_count += 1

        logger.info(f"✅ Saved {saved_count} tweets for {username}")

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
            return {"success": False, "username": username, "platform": "Twitter", "reason": str(e)}


# ==========================================================
# 🎵 TIKTOK TASK
# ==========================================================
@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="tiktok")
def scrape_tiktok_task(self, username: str) -> dict:
    """Scrape TikTok profile via ScrapingBee and save to DB."""
    try:
        result = scrape_tiktok_profile(username)
        if not result.get("success"):
            raise Exception(result.get("reason") or "Unknown TikTok scrape error")

        profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
        profile.full_name = result.get("full_name", "")
        profile.avatar_url = result.get("avatar_url")
        profile.save()

        SocialMediaAccount.objects.update_or_create(
            profile=profile,
            platform="TikTok",
            defaults={
                "bio": result.get("bio", ""),
                "followers": result.get("followers", 0),
                "following": result.get("following", 0),
                "posts_collected": len(result.get("posts", [])),
                "is_private": result.get("is_private", False),
                "external_url": result.get("external_url"),
            },
        )

        posts = result.get("posts", [])
        for post in posts:
            caption = post.get("caption", "")
            likes = int(post.get("likes", 0))
            comments = int(post.get("comments", 0))
            timestamp = post.get("timestamp") or timezone.now()
            sentiment = round(TextBlob(caption).sentiment.polarity, 2)

            RawPost.objects.update_or_create(
                profile=profile,
                content=caption[:500],
                platform="TikTok",
                timestamp=timestamp,
                defaults={
                    "likes": likes,
                    "comments": comments,
                    "sentiment_score": sentiment,
                },
            )

        ensure_behavioral_record(profile)
        perform_behavioral_analysis.delay(profile.id)
        logger.info(f"✅ TikTok behavioral analysis queued for {username}")
        return {"success": True, "username": username, "platform": "TikTok"}

    except Exception as e:
        logger.exception(f"TikTok scraping error for {username}")
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for TikTok scrape: {username}")
            return {"success": False, "username": username, "platform": "TikTok", "reason": str(e)}


# ==========================================================
# 📸 INSTAGRAM TASK
# ==========================================================
@shared_task(bind=True, max_retries=5, default_retry_delay=60, queue="instagram")
def scrape_instagram_task(self, username: str) -> dict:
    """Scrape Instagram profile via scraping utility and save to DB."""
    try:
        data = scrape_instagram_profile(username)
        if not data or (isinstance(data, dict) and "error" in data):
            reason = data.get("error") if isinstance(data, dict) else "No data"
            logger.warning(f"Permanent failure scraping {username}: {reason}")
            with transaction.atomic():
                profile, _ = Profile.objects.get_or_create(username=username, platform="Instagram")
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
                        "is_private": True,
                        "external_url": None,
                    },
                )
            return {"success": False, "username": username, "platform": "Instagram", "reason": reason}

        # Valid scrape
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
                    "posts_collected": len(data.get("posts", [])),
                    "is_private": data.get("is_private", False),
                    "external_url": data.get("external_url"),
                },
            )

        ensure_behavioral_record(profile)
        perform_behavioral_analysis.delay(profile.id)
        logger.info(f"✅ Behavioral record ensured for {username} (Instagram)")
        return {"success": True, "username": username, "platform": "Instagram"}

    except Exception as e:
        err_msg = str(e)
        logger.exception(f"Instagram scraping failed for {username}: {err_msg}")
        if any(x in err_msg for x in ["Please wait", "401", "429", "temporarily unavailable"]):
            wait_time = 120
            raise self.retry(exc=e, countdown=wait_time)
        return {"success": False, "username": username, "platform": "Instagram", "reason": err_msg}


# ==========================================================
# 🧩 BEHAVIORAL ANALYSIS TASK
# ==========================================================
@shared_task(bind=True, queue="default")
def perform_behavioral_analysis(self, profile_id):
    """Analyze user behavior, sentiment, and interests (multi-platform)."""
    try:
        profile = Profile.objects.get(id=profile_id)
        analysis, _ = BehavioralAnalysis.objects.get_or_create(profile=profile)
        sm = SocialMediaAccount.objects.filter(profile=profile, platform=profile.platform).first()
        posts_qs = RawPost.objects.filter(profile=profile)

        # Helper functions
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

        # --- Generic fallback (covers Twitter/others) ---
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
        analysis.network_size = network_size
        analysis.sentiment_distribution = sentiment_distribution
        analysis.influence_score = round(network_size * (sentiment_score + 1), 2)
        analysis.analyzed_at = timezone.now()
        analysis.save()

        logger.info(f"✅ Behavioral analysis done for {profile.username}")
        return {"success": True, "profile": profile.username}

    except Exception as e:
        logger.exception(f"Behavioral analysis failed for profile {profile_id}: {e}")
        return {"success": False, "error": str(e)}
