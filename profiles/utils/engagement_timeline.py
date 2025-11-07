import json

def generate_engagement_timeline(posts):
    """Generate engagement (likes + comments) timeline."""
    engagement_labels, engagement_values = [], []
    for p in posts:
        ts = p.get("timestamp")
        if ts:
            engagement_labels.append(ts.strftime("%b %d"))
            likes = int(p.get("likes") or 0)
            comments = int(p.get("comments") or 0)
            engagement_values.append(likes + comments)
    return json.dumps(engagement_labels), json.dumps(engagement_values)
