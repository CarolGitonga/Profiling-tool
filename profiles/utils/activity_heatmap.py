import json
from collections import Counter

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
WEEKDAY_INDEX = {d: i for i, d in enumerate(WEEKDAYS)}

def generate_activity_heatmap(posts):
    """Generate heatmap data (weekday × hour)."""
    heat_counter = Counter()
    for p in posts:
        ts = p.get("timestamp")
        if ts:
            heat_counter[(ts.hour, ts.strftime("%A"))] += 1

    heatmap_data = [
        {"x": hour, "y": WEEKDAY_INDEX[wd], "v": heat_counter.get((hour, wd), 0)}
        for wd in WEEKDAYS for hour in range(24)
    ]
    return json.dumps(heatmap_data)
