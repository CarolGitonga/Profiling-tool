import os
import re
import json
import logging
import random
import subprocess
import shutil
import sys
from bs4 import BeautifulSoup
from datetime import datetime
from textblob import TextBlob
from scrapingbee import ScrapingBeeClient
from playwright.sync_api import sync_playwright
from django.conf import settings
from django.utils import timezone
from profiles.models import Profile, SocialMediaAccount, RawPost



logger = logging.getLogger(__name__)


# ============================================================
# Playwright Environment
# ============================================================
PLAYWRIGHT_PATH = "/opt/render/project/src/.playwright"
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_PATH

PY_EXEC = shutil.which("python3") or shutil.which("python") or sys.executable

if not os.path.exists(os.path.join(PLAYWRIGHT_PATH, "chromium_headless_shell-1187")):
    try:
        subprocess.run(
            [PY_EXEC, "-m", "playwright", "install", "chromium", "chromium-headless-shell"],
            check=True,
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": PLAYWRIGHT_PATH}
        )
    except Exception as e:
        print("❌ Failed Playwright install:", e)
else:
    print(f"✅ Playwright installed at {PLAYWRIGHT_PATH}")


SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))


def _get_client():
    if not SCRAPINGBEE_API_KEY:
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)


# ============================================================
# Fetch TikTok HTML
# ============================================================
def _fetch_tiktok_html(username: str):
    client = _get_client()

    if client:
        for region in ["us", "gb", "fr", "de", "ca", "ke"]:
            try:
                resp = client.get(
                    f"https://www.tiktok.com/@{username}",
                    params={
                        "render_js": "true",
                        "wait_browser": "networkidle",
                        "premium_proxy": "true",
                        "stealth_proxy": "true",
                        "device": "desktop",
                        "country_code": region,
                    },
                )
                if resp.status_code == 200 and "SIGI_STATE" in resp.text:
                    logger.info(f"✅ ScrapingBee worked for {username} ({region})")
                    return resp.text, f"ScrapingBee ({region})"
            except:
                pass

    # Fallback to Playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(f"https://www.tiktok.com/@{username}", timeout=60000)

            page.wait_for_timeout(5000)
            html = page.content()
            browser.close()
            return html, "Playwright (fallback)"
    except Exception as e:
        logger.error(f"❌ Playwright failed: {e}")
        return None, "Failed"


# ============================================================
# Parse TikTok Profile
# ============================================================
def _parse_tiktok_profile(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")

    def t(tag):  # convenience wrapper
        el = soup.select_one(f'[data-e2e="{tag}"]')
        return el.get_text(strip=True) if el else ""

    def to_int(s):
        s = s.upper().replace(",", "")
        try:
            if "K" in s:
                return int(float(s.replace("K", "")) * 1_000)
            if "M" in s:
                return int(float(s.replace("M", "")) * 1_000_000)
            if "B" in s:
                return int(float(s.replace("B", "")) * 1_000_000_000)
            return int(s)
        except:
            return 0

    return {
        "username": t("user-uniqueId"),     # FIXED
        "full_name": t("user-title"),
        "bio": t("user-bio"),
        "followers": to_int(t("followers-count")),
        "following": to_int(t("following-count")),
        "likes": to_int(t("likes-count")),
        "avatar": (
            soup.select_one('[data-e2e="user-avatar"] img[src]')["src"]
            if soup.select_one('[data-e2e="user-avatar"] img[src]')
            else ""
        )
    }


# ============================================================
# Parse Posts from HTML
# ============================================================
def extract_tiktok_posts_from_html(html, max_posts=20):
    soup = BeautifulSoup(html, "html.parser")
    posts = []

    containers = soup.select("div[data-e2e='user-post-item'], a[data-e2e='user-post-item']")

    for c in containers[:max_posts]:
        caption = c.get_text(strip=True)
        likes_el = c.select_one("strong[data-e2e='likes-count']")
        comments_el = c.select_one("strong[data-e2e='comment-count']")

        def to_int(s):
            s = s.upper().replace(",", "")
            try:
                if "K" in s: return int(float(s.replace("K", "")) * 1000)
                if "M" in s: return int(float(s.replace("M", "")) * 1000000)
                return int(s)
            except:
                return 0

        likes = to_int(likes_el.text) if likes_el else 0
        comments = to_int(comments_el.text) if comments_el else 0

        posts.append({
            "content": caption,
            "likes": likes,
            "comments": comments,
            "timestamp": timezone.now(),
            "sentiment": TextBlob(caption).sentiment.polarity if caption else 0.0,
        })

    return posts


# ============================================================
# Main Scraper + Save to DB
# ============================================================
def scrape_tiktok_profile(username: str):
    html, source = _fetch_tiktok_html(username)
    if not html:
        return {"success": False, "reason": f"Failed to fetch TikTok HTML: {source}"}

    profile_data = _parse_tiktok_profile(html)
    if not profile_data["username"]:
        return {"success": False, "reason": "Failed to parse TikTok profile"}

    posts = extract_tiktok_posts_from_html(html, max_posts=20)

    # Save Profile
    profile, _ = Profile.objects.update_or_create(
        username=username,
        platform="TikTok",
        defaults={
            "full_name": profile_data.get("full_name", ""),
            "avatar_url": profile_data.get("avatar"),
        }
    )

    # Save SocialMediaAccount
    SocialMediaAccount.objects.update_or_create(
        profile=profile,
        platform="TikTok",
        defaults={
            "bio": profile_data.get("bio", ""),
            "followers": profile_data.get("followers", 0),
            "following": profile_data.get("following", 0),
            "posts_collected": len(posts),
        }
    )

    # Save posts into RawPost (FIXED)
    saved = 0
    for post in posts:
        RawPost.objects.update_or_create(
            profile=profile,
            platform="TikTok",
            post_id=f"{username}-{hash(post['content'])}",
            defaults={
                "content": post["content"],
                "likes": post["likes"],
                "comments": post["comments"],
                "timestamp": post["timestamp"],
                "sentiment_score": post["sentiment"],
            }
        )
        saved += 1

    logger.info(f"💾 TikTok saved {saved}/{len(posts)} posts for {username}")
    return {
        "success": True,
        "source": source,
        "saved_posts": saved,
        **profile_data,
    }

    
