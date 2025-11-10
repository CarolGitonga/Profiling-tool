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
# from profiles.utils.instagram_scraper import scrape_instagram_profile
from profiles.utils.instagram_scrapingbee_scraper import scrape_instagram_posts_scrapingbee


logger = logging.getLogger(__name__)


# ==========================================================
# 🧠 Helper
# ==========================================================
def ensure_behavioral_record(profile):
    """Ensure a BehavioralAnalysis record exists for the given profile."""
    BehavioralAnalysis.objects.get_or_create(profile=profile)


# ==========================================================
# 🐦 TWITTER TASK

@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="twitter")
def scrape_twitter_task(self, username: str) -> dict:
    """
    Celery task to scrape a Twitter profile via ScrapingBee/Nitter,
    update database models, and trigger behavioral analysis.
    """
    try:
        # --- Run scraper ---
        logger.info(f"🚀 Starting Twitter scrape task for @{username}")
        result = scrape_twitter_profile(username)

        # --- Handle scrape failure ---
        if not result.get("success"):
            reason = result.get("error", "Unknown scrape failure")
            logger.warning(f"⚠️ Twitter scrape failed for {username}: {reason}")
            raise Exception(reason)

        # --- Upsert Profile ---
        profile, _ = Profile.objects.get_or_create(
            username=username,
            platform="Twitter",
            defaults={
                "full_name": result.get("full_name", username),
                "avatar_url": result.get("avatar_url", ""),
            },
        )
        profile.full_name = result.get("full_name", username)
        profile.avatar_url = result.get("avatar_url", "")
        profile.posts_count = result.get("total_tweets_scraped", 0)
        profile.save()

        # --- Upsert SocialMediaAccount ---
        SocialMediaAccount.objects.update_or_create(
            profile=profile,
            platform="Twitter",
            defaults={
                "bio": result.get("bio", ""),
                "followers": result.get("followers", 0),
                "following": result.get("following", 0),
                "posts_collected": result.get("tweets_saved", 0),
                "is_private": False,
                "external_url": None,
            },
        )

        # --- Tweets are already saved inside scraper ---
        # But double-check at least one exists
        saved_posts = RawPost.objects.filter(profile=profile, platform="Twitter").count()
        if saved_posts == 0:
            logger.warning(f"⚠️ No tweets saved for {username}.")
        else:
            logger.info(f"💾 Verified {saved_posts} tweets saved for {username}")

        # --- Trigger Behavioral Analysis ---
        try:
            ensure_behavioral_record(profile)
            perform_behavioral_analysis.delay(profile.id)
            logger.info(f"🧠 Behavioral analysis queued for {username} (Twitter)")
        except Exception as e:
            logger.warning(f"⚠️ Behavioral analysis not started: {e}")

        logger.info(f"✅ Completed Twitter scrape for @{username}")
        return {
            "success": True,
            "username": username,
            "platform": "Twitter",
            "followers": result.get("followers", 0),
            "following": result.get("following", 0),
            "tweets": result.get("total_tweets_scraped", 0),
            "source": result.get("source", "unknown"),
        }

    except Exception as e:
        logger.exception(f"❌ Error scraping Twitter for {username}")
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"🚫 Max retries exceeded for Twitter scrape: {username}")
            return {
                "success": False,
                "username": username,
                "platform": "Twitter",
                "reason": str(e),
            }


# ==========================================================
# 🎵 TIKTOK TASK (Refactored for Playwright fallback)
# ==========================================================
@shared_task(bind=True, max_retries=3, default_retry_delay=60, queue="tiktok")
def scrape_tiktok_task(self, username: str) -> dict:
    """
    Scrape TikTok profile using ScrapingBee + Playwright fallback,
    save to DB, and trigger behavioral analysis.
    """
    from profiles.utils.tiktok_scraper import scrape_tiktok_profile

    try:
        logger.info(f"🎵 Starting TikTok scrape task for {username}")
        result = scrape_tiktok_profile(username)

        # --- Handle failure gracefully
        if not result.get("success"):
            reason = result.get("reason") or result.get("error") or "Unknown error"
            raise Exception(f"TikTok scrape failed for {username}: {reason}")

        # --- Extract returned info safely
        full_name = result.get("full_name", "")
        bio = result.get("bio", "")
        followers = result.get("followers", 0)
        following = result.get("following", 0)
        likes = result.get("likes", 0)
        avatar = result.get("avatar") or result.get("avatar_url", "")
        source = result.get("source", "unknown")

        # --- Update or create Profile + SocialMediaAccount
        profile, _ = Profile.objects.update_or_create(
            username=username,
            platform="TikTok",
            defaults={
                "full_name": full_name,
                "avatar_url": avatar,
                "posts_count": 0,
            },
        )

        SocialMediaAccount.objects.update_or_create(
            profile=profile,
            platform="TikTok",
            defaults={
                "bio": bio,
                "followers": followers,
                "following": following,
                "posts_collected": 0,
                "is_private": False,
                "external_url": "",
            },
        )

        # --- Behavioral record (no posts yet, but triggers analysis later)
        ensure_behavioral_record(profile)
        perform_behavioral_analysis.delay(profile.id)

        logger.info(
            f"✅ TikTok scrape complete for {username} | Followers={followers}, Following={following}, Likes={likes}, Source={source}"
        )

        return {
            "success": True,
            "username": username,
            "platform": "TikTok",
            "followers": followers,
            "following": following,
            "likes": likes,
            "source": source,
        }

    except Exception as e:
        logger.exception(f"❌ TikTok scraping error for {username}: {e}")
        try:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        except self.MaxRetriesExceededError:
            logger.error(f"Max retries exceeded for TikTok scrape: {username}")
            return {
                "success": False,
                "username": username,
                "platform": "TikTok",
                "reason": str(e),
            }



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
# 🧩 BEHAVIORAL ANALYSIS TASK (refactored)
# ==========================================================

@shared_task(bind=True, queue="default")
def perform_behavioral_analysis(self, profile_id):
    """Analyze user behavior, sentiment, and interests (multi-platform safe)."""
    try:
        profile = Profile.objects.get(id=profile_id)
        analysis, _ = BehavioralAnalysis.objects.get_or_create(profile=profile)
        sm = SocialMediaAccount.objects.filter(profile=profile, platform=profile.platform).first()
        posts_qs = RawPost.objects.filter(profile=profile).only("timestamp", "content")

        # ----------------- Helpers -----------------
        def _to_df(qs):
            if not qs.exists():
                return pd.DataFrame()
            df = pd.DataFrame.from_records(list(qs.values("timestamp", "content")))
            # Drop null timestamps and coerce to datetime
            if "timestamp" in df.columns:
                df = df[df["timestamp"].notna()].copy()
                # ensure timezone-aware; if naive, treat as now (fallback)
                df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
                df = df[df["timestamp"].notna()]
            return df

        def compute_posting_patterns(posts_df: pd.DataFrame):
            if posts_df.empty or "timestamp" not in posts_df.columns:
                return None, []
            posts_df["hour"] = posts_df["timestamp"].dt.hour
            posts_df["weekday"] = posts_df["timestamp"].dt.day_name()
            # Mode can be empty; guard
            try:
                avg_post_time = f"{int(posts_df['hour'].mode().iat[0])}:00"
            except Exception:
                avg_post_time = None
            most_active_days = []
            if "weekday" in posts_df.columns:
                most_active_days = posts_df["weekday"].value_counts().head(3).index.tolist()
            return avg_post_time, most_active_days

        def extract_keywords(text: str):
            if not text.strip():
                return {}
            hashtags = re.findall(r"#(\w+)", text)
            words = re.findall(r"\b[a-zA-Z]{4,}\b", text.lower())
            all_keywords = hashtags + words
            return pd.Series(all_keywords).value_counts().head(20).to_dict() if all_keywords else {}

        def compute_sentiment_distribution(captions):
            sentiment_distribution = {"positive": 0, "neutral": 0, "negative": 0}
            sentiments = []
            for caption in captions:
                s = round(TextBlob(str(caption)).sentiment.polarity, 3)
                sentiments.append(s)
                if s > 0.05:
                    sentiment_distribution["positive"] += 1
                elif s < -0.05:
                    sentiment_distribution["negative"] += 1
                else:
                    sentiment_distribution["neutral"] += 1
            overall_score = round(
                (sentiment_distribution["positive"] - sentiment_distribution["negative"])
                / max(1, sum(sentiment_distribution.values())),
                3,
            )
            return sentiments, sentiment_distribution, overall_score

        # ----------------- Compute -----------------
        captions = list(posts_qs.values_list("content", flat=True))
        sentiments, sentiment_distribution, sentiment_score = compute_sentiment_distribution(captions)

        posts_df = _to_df(posts_qs)
        avg_post_time, most_active_days = compute_posting_patterns(posts_df)
        keyword_freq = extract_keywords(" ".join(captions))

        followers = int(getattr(sm, "followers", 0) or 0) if sm else 0
        following = int(getattr(sm, "following", 0) or 0) if sm else 0
        network_size = followers + following

        # ----------------- Persist -----------------
        analysis.avg_post_time = avg_post_time
        analysis.most_active_days = most_active_days or []
        analysis.sentiment_score = sentiment_score
        analysis.top_keywords = keyword_freq or {}
        analysis.network_size = network_size
        # Optional fields left untouched: network_density, geo_locations, interests
        analysis.analyzed_at = timezone.now()
        analysis.save()

        logger.info(f"✅ Behavioral analysis done for {profile.username} ({profile.platform})")
        # Return includes derived fields we didn't store (for convenience)
        return {
            "success": True,
            "profile": profile.username,
            "platform": profile.platform,
            "sentiment_distribution": sentiment_distribution,
            "computed_samples": len(captions),
        }

    except Exception as e:
        logger.exception(f"Behavioral analysis failed for profile {profile_id}: {e}")
        return {"success": False, "error": str(e)}
