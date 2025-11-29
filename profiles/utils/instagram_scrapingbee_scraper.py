import os, sys, shutil, subprocess, logging, random, re, json, base64
from bs4 import BeautifulSoup
from django.conf import settings
from scrapingbee import ScrapingBeeClient
from datetime import datetime, timezone as dt_timezone
from profiles.models import Profile, SocialMediaAccount, RawPost
from django.utils import timezone as dj_timezone
from textblob import TextBlob
logger = logging.getLogger(__name__)

# ============================================================
# ✅ Ensure Playwright is installed & consistent
# ============================================================
PLAYWRIGHT_PATH = "/opt/render/project/src/.playwright"
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_PATH

PY_EXEC = shutil.which("python3") or shutil.which("python") or sys.executable

# Auto-install Playwright (only if missing)
if not os.path.exists(os.path.join(PLAYWRIGHT_PATH, "chromium_headless_shell-1187")):
    print("⚙️ Installing Playwright Chromium runtime (first-run fix)...")
    try:
        os.makedirs(PLAYWRIGHT_PATH, exist_ok=True)
        subprocess.run(
            [
                PY_EXEC,
                "-m",
                "playwright",
                "install",
                "chromium",
                "chromium-headless-shell",
            ],
            check=True,
            env={**os.environ, "PLAYWRIGHT_BROWSERS_PATH": PLAYWRIGHT_PATH},
        )
        print(f"✅ Playwright browsers installed at {PLAYWRIGHT_PATH}")
    except Exception as e:
        print("❌ Auto-install failed:", e)
else:
    print(f"✅ Playwright already installed at {PLAYWRIGHT_PATH}")

# ============================================================
# 🔑 ScrapingBee Setup
# ============================================================
SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))

def _get_client():
    if not SCRAPINGBEE_API_KEY:
        logger.error("❌ SCRAPINGBEE_API_KEY missing in environment.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)

# Try importing Playwright safely
try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None
    logger.warning("⚠️ Playwright not available — only ScrapingBee will be used.")

# ============================================================
# 🌍 Fetch Instagram HTML
# ============================================================
def _fetch_instagram_html(username: str) -> tuple[str | None, str]:
    """Try ScrapingBee first, then fall back to Playwright."""
    client = _get_client()
    if client:
        for region in random.sample(["us", "gb", "fr", "de", "ca"], 5):
            try:
                resp = client.get(
                    f"https://www.instagram.com/{username}/",
                    params={
                        "render_js": "true",
                        "wait_browser": "networkidle",
                        "stealth_proxy": "true",
                        "premium_proxy": "true",
                        "country_code": region,
                        "block_resources": "true",
                        "device": "desktop",
                    },
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/126.0.0.0 Safari/537.36"
                        ),
                        "Accept-Language": "en-US,en;q=0.9",
                        "Referer": "https://www.instagram.com/",
                    },
                )
                if resp.status_code == 200 and ("og:title" in resp.text or "og:description" in resp.text):
                    logger.info(f"✅ ScrapingBee (region={region}) worked for @{username}")
                    return resp.text, f"ScrapingBee ({region})"
                else:
                    logger.warning(f"⚠️ Instagram returned {resp.status_code} region={region} for @{username}")
            except Exception as e:
                logger.warning(f"⚠️ ScrapingBee region {region} failed for @{username}: {e}")

    # ======================================================
    # 🧠 Playwright Fallback — dynamic rendering
    # ======================================================
    if not sync_playwright:
        return None, "Playwright not available"
    try:
        with sync_playwright() as p:
            logger.info(f"🌐 Using Playwright fallback for Instagram @{username}")
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/126.0.0.0 Safari/537.36"
                )
            )
            # Load Instagram cookies into Playwright
            cookies_b64 = os.getenv("IG_COOKIES_B64")
            if cookies_b64:
                try:
                    cookies_raw = base64.b64decode(cookies_b64).decode()
                    cookies = json.loads(cookies_raw)
                    context.add_cookies(cookies)
                    logger.info("🍪 Loaded Instagram cookies for Playwright")
                except Exception as e:
                    logger.error(f"❌ Failed to load cookies: {e}")
            page = context.new_page()
            # --- Navigate to profile ---
            profile_url = f"https://www.instagram.com/{username}/"
            page.goto(profile_url, timeout=60000)

            page.wait_for_timeout(6000)
            try:
                page.wait_for_selector('meta[property="og:title"]', timeout=15000)
            except Exception:
                logger.warning("⏳ OG meta not found — trying fallback selectors...")
                try:
                    page.wait_for_selector('img[alt*="profile picture"]', timeout=10000)
                except Exception:
                    pass     

            html = page.content()
            browser.close()

            if "og:title" in html or "og:description" in html:
                logger.info(f"✅ Playwright successfully fetched Instagram page for @{username}")
                return html, "Playwright (fallback)"
            else:
                logger.warning(f"⚠️ Playwright fetched but missing metadata for @{username}")
                return html, "Playwright (empty)"
    except Exception as e:
        logger.error(f"❌ Playwright failed for @{username}: {e}")
        return None, "Failed"

# ============================================================
# 🔢 Helper: Convert Instagram follower counts
# ============================================================
def _to_int_safe(value: str) -> int:
    if not value:
        return 0
    try:
        s = str(value).replace(",", "").strip().upper()
        if "K" in s:
            return int(float(s.replace("K", "")) * 1_000)
        elif "M" in s:
            return int(float(s.replace("M", "")) * 1_000_000)
        elif "B" in s:
            return int(float(s.replace("B", "")) * 1_000_000_000)
        else:
            return int(float(s))
    except Exception:
        return 0

import requests

def fetch_recent_posts_api(username: str):
    """
    Fetch recent Instagram posts using the public web_profile_info API.
    Works without login.
    """
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"

    headers = {
        "User-Agent": "Mozilla/5.0",
        "X-IG-App-ID": "936619743392459"
    }

    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code != 200:
            logger.warning(f"⚠️ Instagram API returned {resp.status_code} for {username}")
            return []

        data = resp.json()
        user = data.get("data", {}).get("user", {})
        media = user.get("edge_owner_to_timeline_media", {})
        edges = media.get("edges", [])

        posts = []
        for edge in edges:
            node = edge.get("node", {})

            caption = ""
            cap_edges = node.get("edge_media_to_caption", {}).get("edges")
            if cap_edges:
                caption = cap_edges[0].get("node", {}).get("text", "")

            posts.append({
                "caption": caption,
                "timestamp": node.get("taken_at_timestamp"),
                "likes": node.get("edge_liked_by", {}).get("count", 0),
                "comments": node.get("edge_media_to_comment", {}).get("count", 0),
            })

        return posts

    except Exception as e:
        logger.error(f"❌ Instagram API failed for @{username}: {e}")
        return []


# Extract posts from user_data JSON
def extract_posts_from_user_data(user_data) -> list[dict]:
    """
    Extract recent posts (caption, timestamp, likes, comments) from
    Instagram's user_data JSON, suitable for RawPost.
    """
    posts = []
    media = user_data.get("edge_owner_to_timeline_media") or {}
    edges = media.get("edges") or []
    for edge in edges:
        node = edge.get("node") or {}
        caption_edges = node.get("edge_media_to_caption", {}).get("edges") or []
        if caption_edges:
            caption = caption_edges[0].get("node", {}).get("text", "") or ""
        else:
            caption = ""
        taken_at = node.get("taken_at_timestamp")
        if taken_at:
            try:
                ts = datetime.fromtimestamp(int(taken_at), tz=dt_timezone.utc)
            except Exception:
                ts = None
        else:
            ts = None
        likes = (node.get("edge_liked_by") or {}).get("count", 0)
        comments = (node.get("edge_media_to_comment") or {}).get("count", 0)
        posts.append(
            {
                "caption": caption,
                "timestamp": ts,
                "likes": likes,
                "comments": comments,
            }
        )
    return posts


# ============================================================
# 🧩 HTML Parser
# ============================================================
def parse_instagram_html(html: str) -> dict:
    """
    Parse Instagram profile HTML robustly using JSON-LD, OG tags,
    or embedded JSON (window._sharedData / __additionalDataLoaded).
    """

    soup = BeautifulSoup(html, "html.parser")

    # -------------------------------
    # 1️⃣ Try JSON-LD structured data
    # -------------------------------
    json_data = None
    ld_script = soup.find("script", {"type": "application/ld+json"})
    if ld_script and ld_script.string:
        try:
            json_data = json.loads(ld_script.string)
        except Exception:
            pass

    full_name = username = bio = avatar = ""
    followers = following = posts_count = 0
    recent_posts: list[dict] = []

    if json_data:
        full_name = json_data.get("name", "")
        bio = json_data.get("description", "")
        avatar = json_data.get("image", "")

    # -------------------------------
    # 2️⃣ Try OpenGraph meta tags
    # -------------------------------
    og_title = soup.find("meta", {"property": "og:title"})
    if og_title and og_title.get("content"):
        title = og_title["content"]
        full_name = full_name or title.split("(@")[0].strip()
        m = re.search(r"\(@([^)]+)\)", title)
        if m:
            username = m.group(1).strip()

    og_img = soup.find("meta", {"property": "og:image"})
    if og_img:
        avatar = avatar or og_img.get("content", "")

    og_desc = soup.find("meta", {"property": "og:description"})
    if og_desc:
        desc = og_desc.get("content", "")
        bio = bio or (desc.split("–")[-1].strip() if "–" in desc else desc)
        m = re.search(
            r"([\d,\.KMB]+)\s+Followers?,\s+([\d,\.KMB]+)\s+Following?,\s+([\d,\.KMB]+)\s+Posts?",
            desc,
        )
        if m:
            followers = _to_int_safe(m.group(1))
            following = _to_int_safe(m.group(2))
            posts_count = _to_int_safe(m.group(3))

    # -------------------------------
    # 3️⃣ Try window._sharedData JSON
    # -------------------------------
    shared_script = soup.find("script", string=re.compile("window._sharedData"))
    if shared_script:
        try:
            json_text = re.search(
                r"window\._sharedData\s*=\s*(\{.*\});", shared_script.string
            ).group(1)
            shared_data = json.loads(json_text)
            user_data = (
                shared_data.get("entry_data", {})
                .get("ProfilePage", [{}])[0]
                .get("graphql", {})
                .get("user", {})
            )
            if user_data:
                username = user_data.get("username", username)
                full_name = user_data.get("full_name", full_name)
                bio = user_data.get("biography", bio)
                avatar = user_data.get("profile_pic_url_hd", avatar)
                followers = user_data.get("edge_followed_by", {}).get("count", followers)
                following = user_data.get("edge_follow", {}).get("count", following)
                posts_count = user_data.get("edge_owner_to_timeline_media", {}).get(
                    "count", posts_count
                )
                if not recent_posts:
                    recent_posts = extract_posts_from_user_data(user_data)
        except Exception as e:
            logger.warning(f"⚠️ Failed to parse window._sharedData for @{username}: {e}")

    # -------------------------------
    # 4️⃣ Try window.__additionalDataLoaded (newer structure)
    # -------------------------------
    additional_script = soup.find("script", string=re.compile("__additionalDataLoaded"))
    if additional_script:
        try:
            json_text = re.search(
                r"__additionalDataLoaded\([^,]+,\s*(\{.*\})\);", additional_script.string
            ).group(1)
            data = json.loads(json_text)
            user_data = (
                data.get("graphql", {}).get("user", {})
                or data.get("data", {}).get("user", {})
            )
            if user_data:
                username = user_data.get("username", username)
                full_name = user_data.get("full_name", full_name)
                bio = user_data.get("biography", bio)
                avatar = user_data.get("profile_pic_url_hd", avatar)
                followers = user_data.get("edge_followed_by", {}).get("count", followers)
                following = user_data.get("edge_follow", {}).get("count", following)
                posts_count = user_data.get("edge_owner_to_timeline_media", {}).get(
                    "count", posts_count
                )
                if not recent_posts:
                    recent_posts = extract_posts_from_user_data(user_data)
        except Exception as e:
            logger.warning(
                f"⚠️ Failed to parse __additionalDataLoaded JSON for @{username}: {e}"
            )

    # -------------------------------
    # ✅ Final structured return
    # -------------------------------
    return {
        "username": username,
        "full_name": full_name,
        "followers": followers,
        "following": following,
        "posts": posts_count,
        "bio": bio,
        "avatar": avatar,
        "recent_posts": recent_posts,
    }


# ============================================================
# 🚀 Public Function
# ============================================================
def scrape_instagram_profile(username: str) -> dict:
    """
    Fetch an Instagram profile + recent posts, persist them to the DB,
    and return a summary suitable for the behavioral dashboard.
    """ 
    html, source = _fetch_instagram_html(username)
    if not html:
        return {"success": False, "error": f"Failed to fetch HTML: {source}"}
    parsed = parse_instagram_html(html)

    ig_username = parsed.get("username") or username
    full_name = parsed.get("full_name") or ig_username
    avatar = parsed.get("avatar") or ""
    bio = parsed.get("bio") or ""
    followers = parsed.get("followers") or 0
    following = parsed.get("following") or 0
    recent_posts = fetch_recent_posts_api(ig_username)

    # 1️⃣ Upsert Profile
    profile, _ = Profile.objects.get_or_create(
        username=ig_username,
        platform="Instagram",
        defaults={"full_name": full_name, "avatar_url": avatar},
    )
    # keep profile fresh
    profile.full_name = full_name or profile.full_name
    profile.avatar_url = avatar or profile.avatar_url
    profile.save(update_fields=["full_name", "avatar_url"])
    # 2️⃣ Upsert SocialMediaAccount
    sm_account, _ = SocialMediaAccount.objects.get_or_create(
        profile=profile,
        platform="Instagram",
    )
    sm_account.bio = bio
    sm_account.followers = followers
    sm_account.following = following
    sm_account.save()
    # 3️⃣ Save posts into RawPost with sentiment + timestamp
    saved_count = 0
    for p in recent_posts[:50]:   # limit to 50 for safety
        caption = (p.get("caption") or "").strip()
        if not caption:
            continue
        raw_ts = p.get("timestamp")
        ts = None
        if raw_ts:
            try:
                ts = datetime.fromtimestamp(int(raw_ts), tz=dj_timezone.utc)
            except Exception:
                ts = dj_timezone.now()
        else:
            ts = dj_timezone.now()
        likes = p.get("likes") or 0
        comments = p.get("comments") or 0
        # crude duplicate check by prefix of caption
        if RawPost.objects.filter(
            profile=profile,
            platform="Instagram",
            content__icontains=caption[:60],
        ).exists():
            continue
        polarity = round(TextBlob(caption).sentiment.polarity, 3)
        RawPost.objects.create(
            profile=profile,
            platform="Instagram",
            content=caption,
            timestamp=ts,
            likes=likes,
            comments=comments,
            sentiment_score=polarity,
        )
        saved_count += 1
    total_posts = RawPost.objects.filter(profile=profile, platform="Instagram").count()
    profile.posts_count = total_posts
    profile.save(update_fields=["posts_count"])

    sm_account.posts_collected = total_posts
    sm_account.save(update_fields=["posts_collected"])
    logger.info(
        f"💾 Instagram @{ig_username}: saved {saved_count}/{len(recent_posts)} posts; "
        f"followers={followers}, following={following}, source={source}"
    )
    return {
        "success": True,
        "source": source,
        "username": ig_username,
        "full_name": full_name,
        "bio": bio,
        "avatar_url": avatar,
        "followers": followers,
        "following": following,
        "posts_saved": saved_count,
        "total_posts": total_posts,
    }
