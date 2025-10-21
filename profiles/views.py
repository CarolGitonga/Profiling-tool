
# user-facing logic (form handling, enqueue Celery tasks, render templates)
import json
import logging
from django.shortcuts import render, redirect, get_object_or_404
from profiles.tasks import ensure_behavioral_record, perform_behavioral_analysis, scrape_instagram_task, scrape_tiktok_task
from profiles.utils.github_scraper import scrape_github_profile, unscrape_github_profile
from profiles.utils.instagram_scraper import unscrape_instagram_profile
from profiles.utils.tiktok_scraper import unscrape_tiktok_profile
from profiles.utils.twitter_scraper import get_twitter_profile, unscrape_twitter_bio
from profiles.utils.wordcloud import generate_wordcloud
from .models import Profile, RawPost, SocialMediaAccount
from .forms import UsernameSearchForm
from django.contrib import messages
from dateutil.parser import parse as parse_date
from sherlock.utils import run_sherlock
from django.db.models import Count
from django.db.models import Avg
from django.db.models.functions import TruncMonth
from celery.result import AsyncResult
from django.http import Http404, JsonResponse
from collections import Counter, defaultdict
from django.db.models import F
from profiles.utils.wordcloud import generate_wordcloud  # or adjust path if it's in another utils file


logger = logging.getLogger(__name__)


def search_profile(request):
    if request.method == "POST":
        form = UsernameSearchForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data["username"].strip()
            platform = form.cleaned_data["platform"]
            


            # --- TWITTER (sync) ---
            if platform == "Twitter":
                twitter_data = get_twitter_profile(username)
                if not twitter_data:
                    messages.error(request, f"Could not retrieve Twitter profile for {username}.")
                    return redirect("search_profile")

                profile, _ = Profile.objects.get_or_create(username=username, platform="Twitter")
                profile.full_name = twitter_data["name"]
                profile.avatar_url = twitter_data["avatar_url"]
                profile.profile_created_at = twitter_data["created_at"]
                profile.save()

                SocialMediaAccount.objects.update_or_create(
                    profile=profile,
                    platform="Twitter",
                    defaults={
                        "bio": twitter_data["bio"],
                        "followers": twitter_data["followers_count"],
                        "posts_collected": 0,
                        "is_private": not twitter_data.get("verified", False),
                    },
                )
                # Trigger Behavioral Analysis
                ensure_behavioral_record(profile)
                perform_behavioral_analysis.delay(profile.id)
                logger.info(f"✅ Behavioral analysis queued for {username} (Twitter)")
                return redirect("profile_dashboard", pk=profile.pk)

            # --- GITHUB (sync) ---
            elif platform == "GitHub":
                github_data = scrape_github_profile(username)
                profile, _ = Profile.objects.get_or_create(username=username, platform="GitHub")
                profile.full_name = github_data["name"]
                profile.avatar_url = f"https://github.com/{username}.png"

                if github_data["created_at"]:
                    profile.github_created_at = parse_date(github_data["created_at"])

                profile.location = github_data.get("location")
                profile.company = github_data.get("company")
                profile.blog = github_data.get("blog")
                profile.save()

                SocialMediaAccount.objects.update_or_create(
                    profile=profile,
                    platform="GitHub",
                    defaults={
                        "bio": github_data["bio"],
                        "followers": github_data["followers"] or 0,
                        "following": github_data["following"] or 0,
                        "public_repos": github_data["public_repos"] or 0,
                        "posts_collected": 0,
                    },
                )
                 # Ensure behavioral record exists
                ensure_behavioral_record(profile)
                # Queue asynchronous behavioral analysis
                perform_behavioral_analysis.delay(profile.id)

                logger.info(f"✅ Behavioral analysis queued for {username} (GitHub)")
                return redirect("profile_dashboard", pk=profile.pk)

            # --- INSTAGRAM (async) ---
            elif platform == "Instagram":
                profile, _ = Profile.objects.get_or_create(username=username, platform="Instagram")
                # Send to the correct Celery queue
                result = scrape_instagram_task.apply_async(args=[username], queue="instagram")
                print(f"📤 Sent Instagram scrape task for {username}, task ID: {result.id}")

                messages.info(request, f"Instagram profile for {username} is being scraped in the background.")
                return redirect("profile_dashboard", pk=profile.pk)

            # --- TIKTOK (async) ---
            elif platform == "TikTok":
                profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
                # Send the correct Celery queue
                result = scrape_tiktok_task.apply_async(args=[username], queue="tiktok")
                messages.info(request, f"TikTok profile for {username} is being scraped in the background.")
                return redirect("profile_dashboard", pk=profile.pk)
                
            elif platform == "Sherlock":
                profile, _ = Profile.objects.get_or_create(username=username, platform="Sherlock")
                # call your Sherlock runner (could be sync or async)
                sherlock_results = run_sherlock(username)
                

                # save minimal info into SocialMediaAccount or a related model
                SocialMediaAccount.objects.update_or_create(
                    profile=profile,
                    platform="Sherlock",
                    defaults={"bio": f"Sherlock search ran for {username}",
                              "followers": 0, "following": 0, "posts_collected": 0},
                )         
                 # attach results into context later for dashboard
                request.session["sherlock_results"] = sherlock_results  
                return redirect("profile_dashboard", pk=profile.pk)    
            

    else:
        form = UsernameSearchForm()
    return render(request, "profiles/search.html", {"form": form})


# --- DELETE VIEWS ---
def delete_twitter_data(request, username):
    success = unscrape_twitter_bio(username)
    if success:
        messages.success(request, "Twitter data removed successfully.")
    else:
        messages.error(request, "Profile not found or already removed.")
    return redirect("search_profile")



def task_status(request, task_id):
    res = AsyncResult(task_id)
    return JsonResponse({"ready": res.ready(), "success": res.successful()})


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


# --- DASHBOARD ---
def profile_dashboard(request, pk):
    profile = get_object_or_404(Profile, pk=pk)
    profiles = [profile]  # wrap single profile in a list
    accounts = SocialMediaAccount.objects.filter(profile=profile)
    sherlock_results = []
    wordcloud_image = None
     # Sherlock profile → use sherlock_results text
    if profile.platform == "Sherlock":
        sherlock_results = request.session.get("sherlock_results", [])
        text_data = " ".join([res["platform"] for res in sherlock_results])
        if text_data:
            wordcloud_image = generate_wordcloud(text_data)
    # Other platforms → build text from bios + names
    else:
        text_data = " ".join(
            [acc.bio or "" for acc in accounts] +
            [profile.full_name or "", profile.username]
        )
        if text_data.strip():
            wordcloud_image = generate_wordcloud(text_data)
   # --- Platform distribution across ALL profiles ---
    platform_counts = (
        Profile.objects.values("platform")
        .annotate(count=Count("id"))
        .order_by("platform")
    )
    chart_labels = [p["platform"] for p in platform_counts]
    chart_data = [p["count"] for p in platform_counts]

     # --- Bar Chart Data (followers per platform) ---
    bar_labels = ["Twitter", "Instagram", "TikTok", "GitHub"]
    bar_data = []
    for platform in bar_labels:
        avg_followers = (
            SocialMediaAccount.objects.filter(platform=platform)
            .aggregate(avg=Avg("followers"))["avg"] or 0
        )
        bar_data.append(round(avg_followers, 2))  # 2 decimal precision
    # --- Line Chart Data (profiles added per month) ---
    growth = (
        Profile.objects.annotate(month=TruncMonth("date_profiled"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    )
    growth_labels = [g["month"].strftime("%b %Y") for g in growth]
    growth_data = [g["count"] for g in growth]

    

    context = {
        "profile": profile,
        "profiles": profiles,
        "accounts": accounts,
        "sherlock_results": sherlock_results,
        "wordcloud_image": wordcloud_image,
        "chart_labels": json.dumps(chart_labels),  # pass as JSON-safe
        "chart_data": json.dumps(chart_data),
        "bar_labels": json.dumps(bar_labels),
        "bar_data": json.dumps(bar_data),
        "growth_labels": json.dumps(growth_labels),
        "growth_data": json.dumps(growth_data),

    }

    return render( request, "profiles/dashboard.html", context)

WEEKDAYS = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
WEEKDAY_INDEX = {d: i for i, d in enumerate(WEEKDAYS)}

def behavioral_dashboard(request, username, platform):
    """Platform-specific behavioral dashboard."""
    profile = (
        Profile.objects
        .filter(username=username, platform=platform)
        .order_by("-date_profiled")
        .first()
    )
    if not profile:
        raise Http404(f"No profile found for {username} on {platform}")

    social = SocialMediaAccount.objects.filter(profile=profile, platform=platform).first()
    analysis = getattr(profile, "behavior_analysis", None)

    # ----- Raw posts for this profile (platform-specific) -----
    posts_qs = RawPost.objects.filter(profile=profile, platform=platform).order_by("timestamp")
    posts = list(posts_qs.values("timestamp", "likes", "comments", "sentiment_score", "content"))

    # ----- Sentiment over time (x: date label, y: score) -----
    sentiment_labels = []
    sentiment_values = []
    for p in posts:
        if p["timestamp"] and p["sentiment_score"] is not None:
            sentiment_labels.append(p["timestamp"].strftime("%b %d"))
            sentiment_values.append(round(p["sentiment_score"], 3))

    # ----- Engagement trend (likes + comments over time) -----
    engagement_labels, engagement_values = [], []
    for p in posts:
        if p["timestamp"]:
            engagement_labels.append(p["timestamp"].strftime("%b %d"))
            likes = int(p.get("likes") or 0)
            comments = int(p.get("comments") or 0)
            engagement_values.append(likes + comments)
             

    # ----- Heatmap data: counts by weekday/hour -----
    # Chart.js matrix expects [{x: hour, y: weekdayIndex, v: count}, ...]
    heat_counter = Counter()
    for p in posts:
        ts = p["timestamp"]
        if ts:
            heat_counter[(ts.hour, ts.strftime("%A"))] += 1

    heatmap_data = [
        {"x": hour, "y": WEEKDAY_INDEX[wd], "v": heat_counter.get((hour, wd), 0)}
        for wd in WEEKDAYS for hour in range(24)
    ]

    # ----- Sentiment distribution buckets -----
    pos = sum(1 for s in sentiment_values if s >  0.1)
    neg = sum(1 for s in sentiment_values if s < -0.1)
    neu = max(0, len(sentiment_values) - pos - neg)

    # ----- Network metrics -----
    followers = int(getattr(social, "followers", 0) or 0) if social else 0
    following = int(getattr(social, "following", 0) or 0) if social else 0
    network_size = followers + following
    influence_score = getattr(analysis, "influence_score", None)

    # ----- Keywords / word cloud -----
    # Prefer BehavioralAnalysis.top_keywords; fallback to quick extract from posts
    top_keywords = analysis.top_keywords if analysis and analysis.top_keywords else {}
    if not top_keywords and posts:
        import re
        words = []
        for p in posts:
            content = (p["content"] or "").lower()
            words += re.findall(r"#(\w+)", content)  # hashtags
            words += re.findall(r"\b[a-zA-Z]{4,}\b", content)
        freq = Counter(words).most_common(20)
        top_keywords = {k: v for k, v in freq}
    # ---- 9. Word cloud generation ----
    captions = [p.get("content", "") for p in posts if p.get("content")]
    bios = [
        s.bio for s in SocialMediaAccount.objects.filter(profile=profile)
        if s.bio
    ]
    weighted_keywords = []
    if top_keywords:
        for k, v in top_keywords.items():
            weighted_keywords.append((k + " ") * max(int(v), 1))

    combined_text = " ".join(captions + bios + weighted_keywords)
    wordcloud_image = generate_wordcloud(combined_text) if combined_text.strip() else None

   

    context = {
        "profile": profile,
        "platform": platform,
        "social": social,
        "analysis": analysis,
        # summary cards
        "network_size": network_size,
        "followers": followers,
        "following": following,
        "influence_score": influence_score,
        # charts data (JSON)
        "sentiment_pie": json.dumps([pos, neu, neg]),
        "sentiment_timeline_labels": json.dumps(sentiment_labels),
        "sentiment_timeline_values": json.dumps(sentiment_values),
        "engagement_labels": json.dumps(engagement_labels),
        "engagement_values": json.dumps(engagement_values),
        "heatmap_data": json.dumps(heatmap_data),
        # keywords
        "top_keywords": top_keywords,
        "wordcloud_image": wordcloud_image,
    }
    return render(request, "profiles/behavioral_dashboard.html", context)
