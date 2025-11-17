import json
from profiles.models import RawPost

def generate_sentiment_distribution(username=None, platform=None, sentiment_values=None):
    """
    Multi-platform sentiment distribution calculator.
    
    Options:
    - Pass sentiment_values directly (list of floats)  ➜ used immediately
    - Pass username + platform                        ➜ fetch from DB
    - Use platform='all'                              ➜ merge all platforms
    
    Returns: JSON array → [positive, neutral, negative]
    """

    # ------------------------------------------
    # 1. Use provided sentiment values directly
    # ------------------------------------------
    if sentiment_values is not None:
        values = [float(s) for s in sentiment_values if s is not None]
    else:
        # --------------------------------------------------------
        # 2. Fetch from DB if username/platform are provided
        # --------------------------------------------------------
        if not username:
            return json.dumps([0, 0, 0])

        platform = (platform or "").capitalize()

        if platform.lower() == "all":
            qs = RawPost.objects.filter(profile__username=username)
        else:
            qs = RawPost.objects.filter(
                profile__username=username,
                profile__platform=platform
            )

        values = []
        for p in qs:
            if p.sentiment_score is not None:
                try:
                    values.append(float(p.sentiment_score))
                except:
                    pass  # ignore corrupt values

    # ------------------------------------------
    # 3. Compute sentiment distributions
    # ------------------------------------------
    if not values:
        return json.dumps([0, 0, 0])

    pos = sum(1 for s in values if s > 0.05)
    neg = sum(1 for s in values if s < -0.05)
    neu = len(values) - pos - neg

    return json.dumps([pos, neu, neg])
