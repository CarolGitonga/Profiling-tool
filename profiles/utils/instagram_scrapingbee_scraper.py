import os, sys, shutil, subprocess, logging, random, re, json
from bs4 import BeautifulSoup
from django.conf import settings
from scrapingbee import ScrapingBeeClient

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
    IG_USER = os.getenv("IG_LOGIN")
    IG_PASS = os.getenv("INSTAGRAM_PASSWORD")
    if not IG_USER or not IG_PASS:
        logger.error("❌ Missing IG_LOGIN or INSTAGRAM_PASSWORD in environment.")
        return None, "Missing credentials"
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
            page = context.new_page()
            page.goto("https://www.instagram.com/accounts/login/", timeout=60000)
            page.wait_for_timeout(5000)
            page.fill('input[name="username"]', IG_USER)
            page.fill('input[name="password"]', IG_PASS)
            page.click('button[type="submit"]')

            try:
                page.wait_for_selector('svg[aria-label="Home"]', timeout=20000)
                logger.info("✅ Instagram login successful.")
            except Exception:
                logger.warning("⚠️ Login confirmation not found — continuing anyway.")
            # --- Navigate to profile ---
            profile_url = f"https://www.instagram.com/{username}/"
            page.goto(profile_url, timeout=60000)
            page.wait_for_timeout(5000)
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

# ============================================================
# 🧩 HTML Parser
# ============================================================
def parse_instagram_html(html: str) -> dict:
    """
    Parse Instagram profile HTML robustly using JSON-LD, OG tags,
    or embedded JSON (window._sharedData / __additionalDataLoaded).
    """
    import json, re
    from bs4 import BeautifulSoup

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
    followers = following = posts = 0

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
            posts = _to_int_safe(m.group(3))

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
                posts = user_data.get("edge_owner_to_timeline_media", {}).get(
                    "count", posts
                )
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
                posts = user_data.get("edge_owner_to_timeline_media", {}).get(
                    "count", posts
                )
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
        "posts": posts,
        "bio": bio,
        "avatar": avatar,
    }


# ============================================================
# 🚀 Public Function
# ============================================================
def scrape_instagram_profile(username: str) -> dict:
    html, source = _fetch_instagram_html(username)
    if not html:
        return {"success": False, "error": f"Failed to fetch HTML: {source}"}
    parsed = parse_instagram_html(html)
    return {"success": True, "source": source, **parsed}
