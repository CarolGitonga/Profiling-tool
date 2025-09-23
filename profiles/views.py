
# user-facing logic (form handling, enqueue Celery tasks, render templates)
import json
from django.shortcuts import render, redirect, get_object_or_404
from profiles.tasks import scrape_instagram_task, scrape_tiktok_task
from profiles.utils.github_scraper import scrape_github_profile, unscrape_github_profile
from profiles.utils.instagram_scraper import unscrape_instagram_profile
from profiles.utils.tiktok_scraper import unscrape_tiktok_profile
from profiles.utils.twitter_scraper import get_twitter_profile, unscrape_twitter_bio
from profiles.utils.wordcloud import generate_wordcloud
from .models import Profile, SocialMediaAccount
from .forms import UsernameSearchForm
from django.contrib import messages
from dateutil.parser import parse as parse_date
from sherlock.utils import run_sherlock
from django.db.models import Count




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
                    },
                )
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
                return redirect("profile_dashboard", pk=profile.pk)

            # --- INSTAGRAM (async) ---
            elif platform == "Instagram":
                profile, _ = Profile.objects.get_or_create(username=username, platform="Instagram")
                scrape_instagram_task.delay(username)  # enqueue async
                messages.info(request, f"Instagram profile for {username} is being scraped in the background.")
                return redirect("profile_dashboard", pk=profile.pk)

            # --- TIKTOK (async) ---
            elif platform == "TikTok":
                profile, _ = Profile.objects.get_or_create(username=username, platform="TikTok")
                scrape_tiktok_task.delay(username)  # enqueue async
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
    # --- NEW: platform distribution (count how many profiles per platform) ---
    distribution = (
        Profile.objects.values("platform")
        .annotate(count=Count("platform"))
        .order_by("platform")
    )
    
     # Convert for Chart.js (labels + data)
    chart_labels = [item["platform"] for item in distribution]
    chart_data = [item["count"] for item in distribution]

    context = {
        "profiles": profiles,
        "accounts": accounts,
        "sherlock_results": sherlock_results,
        "wordcloud_image": wordcloud_image,
        "chart_labels": json.dumps(chart_labels),  # pass as JSON-safe
        "chart_data": json.dumps(chart_data),

    }

    return render( request, "profiles/dashboard.html", context)
