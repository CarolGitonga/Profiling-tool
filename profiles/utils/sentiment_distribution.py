import json
from profiles.models import RawPost

def generate_sentiment_distribution(username=None, platform=None, sentiment_values=None):
    """
    Returns a Python list [positive, neutral, negative]
    properly filtered across platforms.
    """

    # 1. If caller passed raw sentiment values
    if sentiment_values is not None:
        values = [float(s) for s in sentiment_values if s is not None]

    else:
        if not username:
            return [0, 0, 0]

        # Normalize platform
        platform = (platform or "").lower()

        # 2. Database fetch
        if platform == "all":
            qs = RawPost.objects.filter(profile__username=username)
        else:
            qs = RawPost.objects.filter(
                profile__username=username,
                platform=platform    # CORRECT FIELD
            )

        # Gather sentiment scores
        values = []
        for p in qs:
            if p.sentiment_score is not None:
                try:
                    values.append(float(p.sentiment_score))
                except:
                    pass

    if not values:
        return [0, 0, 0]

    # 3. Compute sentiment groups
    pos = sum(1 for s in values if s > 0.05)
    neg = sum(1 for s in values if s < -0.05)
    neu = len(values) - pos - neg

    return [pos, neu, neg]     # RETURN A PYTHON LIST, NOT JSON
