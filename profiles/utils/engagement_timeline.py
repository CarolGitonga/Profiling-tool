import json
import pandas as pd

def generate_engagement_timeline(posts):
    """
    Multi-platform safe engagement timeline.
    Accepts posts for ANY platform:
      - Twitter: likes + retweets + replies
      - Instagram: likes + comments
      - TikTok: likes + comments + shares
      - GitHub: stars + forks (if available)
    Posts list must contain: timestamp, likes, comments (missing values allowed).
    """

    if not posts:
        return "[]", "[]"

    # --- Build DataFrame ---
    df = pd.DataFrame(posts)

    # Ensure timestamp column exists
    if "timestamp" not in df.columns:
        return "[]", "[]"

    # Convert timestamps to datetime safely
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df[df["timestamp"].notna()]

    if df.empty:
        return "[]", "[]"

    # --- Normalize engagement fields ---
    df["likes"] = pd.to_numeric(df.get("likes", 0), errors="coerce").fillna(0)
    df["comments"] = pd.to_numeric(df.get("comments", 0), errors="coerce").fillna(0)

    # TikTok extra fields (optional)
    df["shares"] = pd.to_numeric(df.get("shares", 0), errors="coerce").fillna(0)

    # GitHub fields (optional)
    df["stars"] = pd.to_numeric(df.get("stars", 0), errors="coerce").fillna(0)
    df["forks"] = pd.to_numeric(df.get("forks", 0), errors="coerce").fillna(0)

    # Engagement formula (covering all platforms)
    df["engagement"] = (
        df["likes"] +
        df["comments"] +
        df["shares"] +
        df["stars"] +
        df["forks"]
    )

    # Extract date label
    df["date"] = df["timestamp"].dt.strftime("%b %d")

    # Group by date (sum engagements for same day)
    grouped = df.groupby("date")["engagement"].sum().reset_index()

    # Convert to JSON for charts
    labels_json = json.dumps(list(grouped["date"]))
    values_json = json.dumps(list(grouped["engagement"]))

    return labels_json, values_json
