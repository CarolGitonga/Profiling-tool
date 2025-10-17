import logging
from celery import shared_task
from django.db import transaction
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

            #return {"success": True, "username": username, "platform": "TikTok"}
            # Get or create profile entry
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

        # ✅ Handle permanent failures (invalid, deleted, private, no data)
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

        # ✅ Valid scrape → save full profile
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

            # ❌ For all other errors (invalid username, private, deleted), mark as permanent
            logger.error(f"Permanent error for {username}: {err_msg}")
            return {"success": False, "username": username, "platform": "Instagram", "reason": err_msg}

        except self.MaxRetriesExceededError:
            return {"error": err_msg, "username": username, "platform": "Instagram"}
    


@shared_task(bind=True, queue="default")
def perform_behavioral_analysis(self, profile_id):
    """
    Analyze a user's posting behavior, language, and interests.
    Updates the BehavioralAnalysis model for the given profile.
    Includes GitHub-specific behavioral metrics.
    """

    try:
        profile = Profile.objects.get(id=profile_id)
        analysis, _ = BehavioralAnalysis.objects.get_or_create(profile=profile)

        # Fetch bio text (used for sentiment, keyword, interest analysis)
        social_data = SocialMediaAccount.objects.filter(profile=profile).values_list("bio", flat=True)
        posts = list(RawPost.objects.filter(profile=profile).values_list("content", flat=True))
        text_data = " ".join([t for t in social_data if t])

        # ====================================
        # 🧠 BRANCH 1: GITHUB BEHAVIOR ANALYSIS
        # ====================================
        if profile.platform == "GitHub":
            sm = SocialMediaAccount.objects.filter(profile=profile, platform="GitHub").first()

            # --- Developer Engagement Metrics ---
            followers = sm.followers if sm else 0
            following = sm.following if sm else 0
            repos = sm.public_repos if hasattr(sm, "public_repos") else 0

            follower_ratio = round(followers / (following or 1), 2)
            influence_score = round((followers * 0.6) + (repos * 0.4), 2)

            # --- Activity Pattern (based on repos + followers) ---
            if repos > 50:
                activity_pattern = "Extremely Active Developer"
            elif repos > 20:
                activity_pattern = "Active Developer"
            elif repos > 5:
                activity_pattern = "Occasional Contributor"
            else:
                activity_pattern = "Low GitHub Activity"

            # --- Interest Extraction ---
            keywords = []
            if sm.bio:
                keywords += re.findall(r"\b[a-zA-Z]{4,}\b", sm.bio.lower())
            if profile.company:
                keywords.append(profile.company.lower())
            if profile.blog:
                keywords.append("blog")

            keyword_freq = pd.Series(keywords).value_counts().head(10).to_dict() if keywords else {}

            # --- Sentiment of bio (optional heuristic) ---
            sentiment_score = round(TextBlob(sm.bio).sentiment.polarity, 2) if sm and sm.bio else 0.0

            # --- Save GitHub Analysis ---
            analysis.avg_post_time = "N/A"  # not applicable for GitHub
            analysis.most_active_days = ["Varies"]  # GitHub data doesn’t include weekdays here
            analysis.sentiment_score = sentiment_score
            analysis.top_keywords = keyword_freq
            analysis.geo_locations = [profile.location or "Unknown"]
            analysis.network_size = followers + following
            analysis.influence_score = influence_score  # optional new field if added to model
            analysis.activity_pattern = activity_pattern
            analysis.analyzed_at = timezone.now()
            analysis.save()

            logger.info(f"✅ GitHub Behavioral analysis completed for {profile.username}")
            return {"success": True, "profile": profile.username}

        # ====================================
        # 🧠 BRANCH 2: GENERIC (Instagram/TikTok)
        # ====================================
        posts_qs = RawPost.objects.filter(profile=profile)
        if posts_qs.exists():
            df = pd.DataFrame(list(posts_qs.values("timestamp")))
            df["hour"] = df["timestamp"].apply(lambda x: x.hour)
            df["weekday"] = df["timestamp"].apply(lambda x: x.strftime("%A"))
            avg_post_time = f"{int(df['hour'].mode()[0])}:00"
            most_active_days = df["weekday"].value_counts().head(3).index.tolist()
        else:
            avg_post_time = None
            most_active_days = []

            # --- Sentiment Analysis ---
            sentiment_score = round(TextBlob(text_data).sentiment.polarity, 2) if text_data else 0.0
            # 🧩 Fallback: Use ScrapingBee to get sentiment from captions if no posts
        sentiment_distribution = {"positive": 0, "neutral": 0, "negative": 0}
        used_scrapingbee = False

        if profile.platform == "Instagram" and not posts_qs.exists():
            used_scrapingbee = True
            captions = scrape_instagram_posts_scrapingbee(profile.username, max_posts=10)
            if captions:
                for caption, sentiment in captions:
                    if sentiment > 0.05:
                        sentiment_distribution["positive"] += 1
                    elif sentiment < -0.05:
                        sentiment_distribution["negative"] += 1
                    else:
                        sentiment_distribution["neutral"] += 1

                    RawPost.objects.update_or_create(
                        profile=profile,
                        content=caption[:500],
                        platform="Instagram",
                        defaults={
                            "sentiment_score": sentiment,
                            "timestamp": timezone.now(),
                        },
                    )

                sentiment_score = round(
                    (sentiment_distribution["positive"] - sentiment_distribution["negative"])
                    / max(1, sum(sentiment_distribution.values())),
                    2,
                )

            # --- Keyword Extraction ---
            hashtags = re.findall(r"#(\w+)", text_data)
            words = re.findall(r"\b[a-zA-Z]{4,}\b", text_data.lower())
            all_keywords = hashtags + words
            keyword_freq = pd.Series(all_keywords).value_counts().head(10).to_dict() if all_keywords else {}
            # --- Network Size ---
            sm = SocialMediaAccount.objects.filter(profile=profile).first()
            network_size = (sm.followers + sm.following) if sm else 0

            # --- Geolocation ---
            geo_locations = []
            if sm and sm.bio:
               if "nairobi" in sm.bio.lower(): geo_locations.append("Nairobi")
               if "kenya" in sm.bio.lower(): geo_locations.append("Kenya")

            

            # --- Save Generic Analysis ---
            analysis.avg_post_time = avg_post_time
            analysis.most_active_days = most_active_days
            analysis.sentiment_score = sentiment_score
            analysis.top_keywords = keyword_freq
            analysis.geo_locations = geo_locations
            analysis.network_size = network_size
            analysis.analyzed_at = timezone.now()
            analysis.save()

            logger.info(f"✅ Behavioral analysis completed for {profile.username}")
            return {"success": True, "profile": profile.username}

    except Exception as e:
        logger.exception(f"Behavioral analysis failed for profile {profile_id}: {e}")
        return {"success": False, "error": str(e)}
