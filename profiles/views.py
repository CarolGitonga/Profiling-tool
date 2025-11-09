import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import Http404, JsonResponse
from django.db import transaction
from django.db.models import Count, Avg, F
from django.db.models.functions import TruncMonth
from collections import Counter
from django.conf import settings
import os
from urllib.parse import urljoin

from dateutil.parser import parse as parse_date
from celery.result import AsyncResult

from profiles.tasks import (
    ensure_behavioral_record,
    perform_behavioral_analysis,
    scrape_instagram_task,
    scrape_tiktok_task,
    scrape_twitter_task,
)
from profiles.utils.activity_heatmap import generate_activity_heatmap
from profiles.utils.engagement_timeline import generate_engagement_timeline
from profiles.utils.entity_graph import generate_entity_graph
from profiles.utils.github_scraper import scrape_github_profile, unscrape_github_profile
from profiles.utils.instagram_scraper import unscrape_instagram_profile
from profiles.utils.keywords_wordcloud import extract_keywords, generate_wordcloud_image
from profiles.utils.post_timeline import generate_post_timeline
from profiles.utils.sentiment_distribution import generate_sentiment_distribution
from profiles.utils.sentiment_timeline import generate_sentiment_timeline
from profiles.utils.tiktok_scraper import unscrape_tiktok_profile
from profiles.utils.twitter_scraper import unscrape_twitter_bio
from sherlock.utils import run_sherlock
from .models import Profile, RawPost, SocialMediaAccount
from .forms import UsernameSearchForm

logger = logging.getLogger(__name__)


# ==========================
# 🔍 SEARCH VIEW
# ==========================
def search_profile(request):
    if request.method == "POST":
        form = UsernameSearchForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"].strip()
            platform = form.cleaned_data["platform"]

            # --- TWITTER (async via ScrapingBee) ---
            if platform == "Twitter":
                profile, _ = Profile.objects.get_or_create(username=username, platform="Twitter")
                result = scrape_twitter_task.apply_async(args=[username], queue="twitter")

                messages.info(
                    request,
                    f"Twitter profile for {username} is being scraped in the background."
                )
                logger.info(f"🚀 Twitter scrape task queued for {username} (task ID: {result.id})")

                return redirect("profile_dashboard", pk=profile.pk)

            # --- GITHUB (sync) ---
            elif platform == "GitHub":
                github_data = scrape_github_profile(username)
                profile, _ = Profile.objects.get_or_create(username=username, platform="GitHub")
                profile.full_name = github_data.get("name", "")
                profile.avatar_url = f"https://github.com/{username}.png"

                if github_data.get("created_at"):
                    profile.github_created_at = parse_date(github_data["created_at"])

                profile.location = github_data.get("location")
                profile.company = github_data.get("company")
                profile.blog = github_data.get("blog")
                profile.save()

                SocialMediaAccount.objects.update_or_create(
                    profile=profile,
                    platform="GitHub",
                    defaults={
                        "bio": github_data.get("bio", ""),
                        "followers": github_data.get("followers", 0),
                        "following": github_data.get("following", 0),
                        "public_repos": github_data.get("public_repos", 0),
                        "posts_collected": 0,
                    },
                )
                ensure_behavioral_record(profile)
                perform_behavioral_analysis.delay(profile.id)
                logger.info(f"✅ Behavioral analysis queued for {username} (GitHub)")
                return redirect("profile_dashboard", pk=profile.pk)

            # --- INSTAGRAM (async) ---
            elif platform == "Instagram":
                profile, _ = Profile.objects.get_or_create(username=username, platform="Instagram")
                result = scrape_instagram_task.apply_async(args=[username], queue="instagram")

                messages.info(
                    request,
                    f"Instagram profile for {username} is being scraped in the background."
                )
                logger.info(f"🚀 Instagram scrape task queued for {username} (task ID: {result.id})")
                return redirect("profile_dashboard", pk=profile.pk)

            # --- TIKTOK (async) ---
            elif platform == "TikTok":
                profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
                result = scrape_tiktok_task.apply_async(args=[username], queue="tiktok")

                messages.info(
                    request,
                    f"TikTok profile for {username} is being scraped in the background."
                )
                logger.info(f"🚀 TikTok scrape task queued for {username} (task ID: {result.id})")
                return redirect("profile_dashboard", pk=profile.pk)

            # --- SHERLOCK (sync) ---
            elif platform == "Sherlock":
                profile, _ = Profile.objects.get_or_create(username=username, platform="Sherlock")
                sherlock_results = run_sherlock(username)

                SocialMediaAccount.objects.update_or_create(
                    profile=profile,
                    platform="Sherlock",
                    defaults={
                        "bio": f"Sherlock search ran for {username}",
                        "followers": 0,
                        "following": 0,
                        "posts_collected": 0,
                    },
                )
                request.session["sherlock_results"] = sherlock_results
                return redirect("profile_dashboard", pk=profile.pk)

    else:
        form = UsernameSearchForm()

    return render(request, "profiles/search.html", {"form": form})


# ==========================
# 🗑️ DELETE VIEWS
# ==========================
def delete_twitter_data(request, username):
    success = unscrape_twitter_bio(username)
    if success:
        messages.success(request, "Twitter data removed successfully.")
    else:
        messages.error(request, "Twitter profile not found or already removed.")
    return redirect("search_profile")


def delete_github_data(request, username):
    success = unscrape_github_profile(username)
    if success:
        messages.success(request, "GitHub data removed successfully.")
    else:
        messages.error(request, "GitHub profile not found or already removed.")
    return redirect("search_profile")


def delete_instagram_data(request, username):
    success = unscrape_instagram_profile(username)
    if success:
        messages.success(request, "Instagram data removed successfully.")
    else:
        messages.error(request, "Instagram profile not found or already removed.")
    return redirect("search_profile")


def delete_tiktok_data(request, username):
    success = unscrape_tiktok_profile(username)
    if success:
        messages.success(request, "TikTok data removed successfully.")
    else:
        messages.error(request, "TikTok profile not found or already removed.")
    return redirect("search_profile")


# ==========================
# 📊 TASK STATUS
# ==========================
def task_status(request, task_id):
    res = AsyncResult(task_id)
    return JsonResponse({"ready": res.ready(), "success": res.successful()})


# ==========================
# 📈 DASHBOARD
# ==========================
def profile_dashboard(request, pk):
    """Unified dashboard across all platforms."""
    profile = get_object_or_404(Profile, pk=pk)

    # 🔹 All profiles by this username (cross-platform view)
    profiles = Profile.objects.filter(username=profile.username)
    accounts = SocialMediaAccount.objects.filter(profile__in=profiles)
    sherlock_results = []
    wordcloud_image = None

    
    # --- Analytics ---
    platform_counts = (
        Profile.objects.values("platform")
        .annotate(count=Count("id"))
        .order_by("platform")
    )
    chart_labels = [p["platform"] for p in platform_counts]
    chart_data = [p["count"] for p in platform_counts]

    bar_labels = ["Twitter", "Instagram", "TikTok", "GitHub"]
    bar_data = [
        round(
            SocialMediaAccount.objects.filter(platform=p)
            .aggregate(avg=Avg("followers"))["avg"] or 0,
            2
        )
        for p in bar_labels
    ]

    growth = (
        Profile.objects.annotate(month=TruncMonth("date_profiled"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    )
    growth_labels = [g["month"].strftime("%b %Y") for g in growth]
    growth_data = [g["count"] for g in growth]

    context = {
        "profile": profile,          # single profile for header
        "profiles": profiles,        # list of all profiles for loop
        "accounts": accounts,        # all SocialMediaAccount objects
        "sherlock_results": sherlock_results,
        "wordcloud_image": wordcloud_image,
        "chart_labels": json.dumps(chart_labels),
        "chart_data": json.dumps(chart_data),
        "bar_labels": json.dumps(bar_labels),
        "bar_data": json.dumps(bar_data),
        "growth_labels": json.dumps(growth_labels),
        "growth_data": json.dumps(growth_data),
    }

    return render(request, "profiles/dashboard.html", context) 


#BEHAVIORAL DASHBOARD
def behavioral_dashboard(request, username, platform):
    """Unified behavioral dashboard using modular visualization utilities."""
    # 1️⃣ Profile + Related Data
    profile = get_object_or_404(Profile, username=username, platform=platform)
    social = SocialMediaAccount.objects.filter(profile=profile, platform=platform).first()
    analysis = getattr(profile, "behavior_analysis", None)
    posts = list(
        RawPost.objects.filter(profile=profile, platform=platform)
        .order_by("timestamp")
        .values("timestamp", "likes", "comments", "sentiment_score", "content")
    )
    # 2️⃣ Sentiment Timeline
    sentiment_labels, sentiment_values_json = generate_sentiment_timeline(posts)
    sentiment_values = json.loads(sentiment_values_json)

    # 3️⃣ Engagement Timeline
    engagement_labels, engagement_values = generate_engagement_timeline(posts)

    # 4️⃣ Post Timeline (Frequency per Day)
    post_timeline_html = generate_post_timeline(username, platform)

    # 5️⃣ Activity Heatmap
    activity_heatmap_image = generate_activity_heatmap(username, platform)

    # 🧠 Generate Entity Graph
    entity_graph_url = None
    cluster_colors = [
    "#007bff", "#28a745", "#17a2b8", "#ffc107",
    "#dc3545", "#6f42c1", "#20c997"
    ]
    cluster_summaries = []
    try:
        graph_path, cluster_summaries = generate_entity_graph(username, platform)
        if graph_path:
            if graph_path.startswith("/media/"):
                entity_graph_url = request.build_absolute_uri(graph_path)
            else:
                filename = os.path.basename(graph_path)
                media_url = settings.MEDIA_URL if settings.MEDIA_URL else "/media/"
                entity_graph_url = request.build_absolute_uri(
                    urljoin(media_url, filename)
                )
        else:
            print(f"⚠️ No entity graph generated for {username} on {platform}.")


    except Exception as e:
        print(f"⚠️ Entity graph generation failed for {username}: {e}")
        entity_graph_url = None
        
        


    # 6️⃣ Sentiment Distribution
    sentiment_pie = generate_sentiment_distribution(sentiment_values)

    # 7️⃣ Network Metrics
    followers = int(getattr(social, "followers", 0) or 0) if social else 0
    following = int(getattr(social, "following", 0) or 0) if social else 0
    network_size = followers + following
    sentiment_score = float(getattr(analysis, "sentiment_score", 0.0) or 0.0)
    influence_score = (
        round(network_size * (sentiment_score + 1.0), 2) if network_size else 0.0
    )

    # 8️⃣ Keywords + Wordcloud
    top_keywords = extract_keywords(posts, analysis)
    wordcloud_image = generate_wordcloud_image(posts, profile, top_keywords)

    # 🔟 Context for Template
    context = {
        "profile": profile,
        "platform": platform,
        "social": social,
        "analysis": analysis,
        "followers": followers,
        "following": following,
        "network_size": network_size,
        "influence_score": influence_score,
        "sentiment_pie": sentiment_pie,
        "sentiment_timeline_labels": sentiment_labels,
        "sentiment_timeline_values": sentiment_values_json,
        "engagement_labels": engagement_labels,
        "engagement_values": engagement_values,
        "activity_heatmap_image": activity_heatmap_image,
        "timeline_html": post_timeline_html,
        "entity_graph_url": entity_graph_url,
        "cluster_summaries": cluster_summaries,
        "cluster_colors": cluster_colors,
        "top_keywords": top_keywords,
        "wordcloud_image": wordcloud_image,
    }

    return render(request, "profiles/behavioral_dashboard.html", context)





   