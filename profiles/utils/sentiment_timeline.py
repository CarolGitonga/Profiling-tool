import json

def generate_sentiment_timeline(posts):
    """Build sentiment over time line chart."""
    sentiment_labels, sentiment_values = [], []
    for p in posts:
        ts = p.get("timestamp")
        if ts and p.get("sentiment_score") is not None:
            sentiment_labels.append(ts.strftime("%b %d"))
            sentiment_values.append(round(float(p["sentiment_score"]), 3))
    return json.dumps(sentiment_labels), json.dumps(sentiment_values)
