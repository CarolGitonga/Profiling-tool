import json
from collections import Counter

def generate_post_timeline(posts):
    """Frequency of posts per day."""
    post_counter = Counter()
    for p in posts:
        ts = p.get("timestamp")
        if ts:
            post_counter[ts.date()] += 1

    post_timeline_labels = [d.strftime("%b %d") for d in sorted(post_counter.keys())]
    post_timeline_values = [post_counter[d] for d in sorted(post_counter.keys())]
    return json.dumps(post_timeline_labels), json.dumps(post_timeline_values)
