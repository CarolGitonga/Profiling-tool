import os
import sys

# Ensure Django settings are loaded
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "people_profiling.settings")

import django
django.setup()

from profiles.utils.instagram_scraper import scrape_instagram_profile

if __name__ == "__main__":
    username = "iamcarolgitonga"  # ✅ test with your own account first
    print(f"🔎 Testing Instagram scrape for: {username}")

    data = scrape_instagram_profile(username)

    if data:
        print("✅ Scrape successful:")
        for k, v in data.items():
            print(f"{k}: {v}")
    else:
        print("❌ Scrape failed (no data returned)")
