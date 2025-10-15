# profiles/activity_views.py
import json
from django.shortcuts import render, get_object_or_404
from django.db.models import Count
from django.db.models.functions import TruncMonth
from .models import RawPost, Profile

def activity_view(request, pk):
    profile = get_object_or_404(Profile, pk=pk)

    # Aggregate posts/activity by month across social accounts
    posts_data = (
    RawPost.objects.filter(profile=profile)
        .annotate(month=TruncMonth("created_at"))
        .values("platform", "month")
        .annotate(count=Count("id"))
        .order_by("month")
    )

    # Labels for x-axis (months)
    labels = sorted(set([str(item["month"].date()) for item in posts_data if item["month"]]))

    # Define platform colors
    colors = {
        "Twitter": "#1DA1F2",
        "Instagram": "#E1306C",
        "TikTok": "#69C9D0",
        "GitHub": "#333",
        "Sherlock": "#0d6efd",
    }

    # Prepare datasets: one line per platform
    datasets = []
    for platform, color in colors.items():
        counts = []
        for label in labels:
            count = next(
                (item["count"] for item in posts_data
                 if str(item["month"].date()) == label and item["platform"] == platform),
                0,
            )
            counts.append(count)

        datasets.append({
            "label": platform,
            "data": counts,
            "borderColor": color,
            "backgroundColor": color,
            "tension": 0.3,
        })

    return render(
        request,
        "profiles/activity.html",
        {
            "profile": profile,
            "labels": json.dumps(labels),
            "datasets": json.dumps(datasets),
        },
    )
