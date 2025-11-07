import re
from collections import Counter
from profiles.utils.wordcloud import generate_wordcloud

def extract_keywords(posts, analysis=None):
    """Extract or fallback to computed keywords."""
    top_keywords = getattr(analysis, "top_keywords", None) if analysis else None
    if top_keywords:
        return top_keywords

    words = []
    for p in posts:
        content = (p.get("content") or "").lower()
        words += re.findall(r"#(\w+)", content)
        words += re.findall(r"\b[a-zA-Z]{4,}\b", content)
    freq = Counter(words).most_common(20)
    return {k: v for k, v in freq}


def generate_wordcloud_image(posts, profile, top_keywords):
    """Generate base64 wordcloud image."""
    bios = [s.bio for s in profile.socialmediaaccount_set.all() if s.bio]
    captions = [p.get("content", "") for p in posts if p.get("content")]
    weighted_keywords = [(k + " ") * max(int(v), 1) for k, v in top_keywords.items()]
    combined_text = " ".join(captions + bios + weighted_keywords)
    return generate_wordcloud(combined_text) if combined_text.strip() else None
