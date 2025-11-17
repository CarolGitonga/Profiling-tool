import json
from profiles.models import RawPost

def generate_sentiment_timeline(posts=None, username=None, platform=None):
    """
    Generate a sentiment-over-time line chart for any platform.
    
    Options:
      ✔ Pass list of posts directly (existing behavior)
      ✔ Pass username + platform to auto-fetch
      ✔ Use platform='all' to combine all platforms
    """

    # ------------------------------------------------------
    # 1. If posts list is NOT provided, fetch from DB
    # ------------------------------------------------------
    if posts is None:
        if not username:
            return "[]", "[]"

        if platform is None or platform.lower() == "all":
            qs = RawPost.objects.filter(profile__username=username)
        else:
            qs = RawPost.objects.filter(
                profile__username=username,
                profile__platform=platform
            )

        posts = list(
            qs.exclude(timestamp=None)
              .order_by("timestamp")
              .values("timestamp", "sentiment_score")
        )

    # ------------------------------------------------------
    # 2. Clean + convert data
    # ------------------------------------------------------
    sentiment_labels = []
    sentiment_values = []

    for p in posts:
        ts = p.get("timestamp")
        score = p.get("sentiment_score")

        if ts and score is not None:
            sentiment_labels.append(ts.strftime("%b %d"))
            try:
                sentiment_values.append(round(float(score), 3))
            except:
                sentiment_values.append(0)

    return json.dumps(sentiment_labels), json.dumps(sentiment_values)
