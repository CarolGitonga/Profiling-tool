import json

def generate_sentiment_distribution(sentiment_values):
    """Compute sentiment pie chart data."""
    pos = sum(1 for s in sentiment_values if s > 0.05)
    neg = sum(1 for s in sentiment_values if s < -0.05)
    neu = max(0, len(sentiment_values) - pos - neg)
    return json.dumps([pos, neu, neg])
