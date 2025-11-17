import io
import base64
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from profiles.models import RawPost

def generate_activity_heatmap(username, platform="Twitter"):
    """
    Generate an activity heatmap (weekday × hour) showing posting frequency.
    Returns a base64-encoded PNG string for embedding in templates.
    """
    #Normalize platform name for DB consistency
    platform = platform.capitalize()
    # Platform-aware query
    if platform.lower() == "all":
        posts = RawPost.objects.filter(profile__username=username)
    else:
        posts = RawPost.objects.filter(profile__username=username, profile__platform=platform)
    timestamps = [p.timestamp for p in posts if p.timestamp]

    if not timestamps:
        return None

    # Build DataFrame from timestamps
    df = pd.DataFrame({"timestamp": timestamps})

    # Fix timezone & coercion
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df[df["timestamp"].notna()]

    df["day"] = df["timestamp"].dt.day_name()
    df["hour"] = df["timestamp"].dt.hour

    # Define weekday order
    day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    df["day"] = pd.Categorical(df["day"], categories=day_order, ordered=True)

    # Create pivot table: rows = days, columns = hours, values = post counts
    pivot = df.pivot_table(index="day", columns="hour", aggfunc="size", fill_value=0)

    # --- Plot setup ---
    plt.figure(figsize=(10, 5))
    sns.heatmap(
        pivot,
        cmap="YlGnBu",
        linewidths=0.4,
        cbar_kws={"label": "Posts"},
    )
    plt.title(f"Posting Activity Heatmap for @{username}", fontsize=13, pad=10)
    plt.xlabel("Hour of Day", fontsize=11)
    plt.ylabel("Day of Week", fontsize=11)

    # Convert Matplotlib figure to Base64 PNG
    buffer = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buffer, format="png")
    plt.close()
    buffer.seek(0)
    image_base64 = base64.b64encode(buffer.read()).decode("utf-8")
    buffer.close()

    return image_base64

