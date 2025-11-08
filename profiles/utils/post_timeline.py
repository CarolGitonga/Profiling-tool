import pandas as pd
import plotly.express as px
from django.utils import timezone
from profiles.models import RawPost

def generate_post_timeline(username: str, platform: str = "Twitter"):
    """
    Generate a Plotly timeline showing posting frequency and average sentiment over time.
    Returns an HTML <div> string that can be embedded directly into Django templates.
    """
    # --- 1️⃣ Fetch data ---
    posts = RawPost.objects.filter(
        profile__username=username, 
        profile__platform=platform
    ).exclude(timestamp=None).order_by("timestamp")

    if not posts.exists():
        return None  # nothing to visualize

    # --- 2️⃣ Convert to DataFrame ---
    data = [
        {
            "timestamp": p.timestamp,
            "sentiment": p.sentiment_score if p.sentiment_score is not None else 0.0,
            "content": (p.content or "")[:100]
        }
        for p in posts
    ]
    df = pd.DataFrame(data)
    df["date"] = df["timestamp"].dt.date

    # --- 3️⃣ Aggregate per day ---
    grouped = df.groupby("date").agg(
        posts=("content", "count"),
        avg_sentiment=("sentiment", "mean")
    ).reset_index()

    # --- 4️⃣ Create Plotly figure ---
    fig = px.bar(
        grouped,
        x="date",
        y="posts",
        color="avg_sentiment",
        title=f"Posting Timeline for @{username} ({platform})",
        labels={"date": "Date", "posts": "Number of Posts"},
        color_continuous_scale="RdYlGn",  # Red (negative) → Yellow → Green (positive)
    )

    fig.update_layout(
        template="plotly_white",
        xaxis_title="Date",
        yaxis_title="Posts per Day",
        title_x=0.5,
        margin=dict(l=40, r=40, t=60, b=40),
        hovermode="x unified",
        coloraxis_colorbar=dict(title="Avg Sentiment"),
    )

    # --- 5️⃣ Return as embeddable HTML fragment ---
    return fig.to_html(full_html=False, include_plotlyjs="cdn")
