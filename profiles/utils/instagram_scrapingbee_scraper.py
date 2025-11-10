# profiles/utils/instagram_scrapingbee_scraper.py

import os, sys, shutil, subprocess, logging, random, re
from bs4 import BeautifulSoup
from django.conf import settings
from scrapingbee import ScrapingBeeClient

logger = logging.getLogger(__name__)

# ============================================================
# ✅ Ensure Playwright is installed & consistent
# ============================================================
PLAYWRIGHT_PATH = "/opt/render/project/src/.playwright"
os.environ["PLAYWRIGHT_BROWSERS_PATH"] = PLAYWRIGHT_PATH

# Detect correct python binary
PY_EXEC = shutil.which("python") or shutil.which("python3") or sys.executable

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


SCRAPINGBEE_API_KEY = os.getenv("SCRAPINGBEE_API_KEY", getattr(settings, "SCRAPINGBEE_API_KEY", None))

def _get_client():
    if not SCRAPINGBEE_API_KEY:
        logger.error("❌ SCRAPINGBEE_API_KEY missing in environment.")
        return None
    return ScrapingBeeClient(api_key=SCRAPINGBEE_API_KEY)

# --- optional Playwright fallback (same idea as your TikTok scraper) ---
try:
    from playwright.sync_api import sync_playwright
except Exception:
    sync_playwright = None

def _fetch_with_playwright(username: str) -> str | None:
    if not sync_playwright:
        logger.warning("Playwright not available in this process.")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/126.0.0.0 Safari/537.36"),
                viewport={"width": 1280, "height": 800}
            )
            page = context.new_page()
            page.goto(f"https://www.instagram.com/{username}/", wait_until="networkidle", timeout=45000)
            html = page.content()
            browser.close()
            logger.info(f"✅ Playwright fetched Instagram page for {username}")
            return html
    except Exception as e:
        logger.exception(f"❌ Playwright failed for Instagram @{username}: {e}")
        return None

def _fetch_instagram_html(username: str) -> tuple[str | None, str]:
    """
    Try ScrapingBee first (JS render), then fall back to Playwright.
    Returns (html, source_label)
    """
    client = _get_client()
    if client:
        for region in random.sample(["us","gb","fr","de","ca"], 5):
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
                        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                                       "Chrome/126.0.0.0 Safari/537.36"),
                        "Accept-Language": "en-US,en;q=0.9",
                        "Referer": "https://www.instagram.com/",
                    },
                )
                if resp.status_code == 200 and ("og:title" in resp.text or "og:description" in resp.text):
                    logger.info(f"✅ ScrapingBee (region={region}) worked for Instagram @{username}")
                    return resp.text, f"ScrapingBee ({region})"
                else:
                    logger.warning(f"⚠️ Instagram returned {resp.status_code} region={region} for @{username}")
            except Exception as e:
                logger.warning(f"⚠️ ScrapingBee region {region} failed for Instagram @{username}: {e}")

    # fallback to Playwright
    html = _fetch_with_playwright(username)
    return (html, "Playwright (fallback)") if html else (None, "Failed")

def _to_int_safe(s: str) -> int:
    s = s.strip().upper().replace(",", "")
    try:
        if s.endswith("K"):
            return int(float(s[:-1]) * 1_000)
        if s.endswith("M"):
            return int(float(s[:-1]) * 1_000_000)
        if s.endswith("B"):
            return int(float(s[:-1]) * 1_000_000_000)
        return int(re.sub(r"[^\d]", "", s))
    except Exception:
        return 0

def parse_instagram_html(html: str) -> dict:
    """
    Parse Instagram profile HTML robustly using JSON-LD or OpenGraph tags.
    """
    import json, re

    soup = BeautifulSoup(html, "html.parser")

    # --- Try JSON-LD structured data ---
    json_data = None
    ld_script = soup.find("script", {"type": "application/ld+json"})
    if ld_script and ld_script.string:
        try:
            json_data = json.loads(ld_script.string)
        except Exception:
            pass

    full_name = ""
    username = ""
    bio = ""
    avatar = ""
    followers = following = posts = 0

    if json_data:
        full_name = json_data.get("name", "")
        bio = json_data.get("description", "")
        avatar = json_data.get("image", "")

    # --- Fallback to OpenGraph metadata ---
    if not full_name:
        og_title = soup.find("meta", {"property": "og:title"})
        if og_title and og_title.get("content"):
            title = og_title["content"]
            # Example: "Neo Minganga (@neominganga) • Instagram photos and videos"
            full_name = title.split("(@")[0].strip()
            m = re.search(r"\(@([^)]+)\)", title)
            if m:
                username = m.group(1).strip()

    if not avatar:
        og_img = soup.find("meta", {"property": "og:image"})
        if og_img:
            avatar = og_img.get("content", "")

    if not bio:
        og_desc = soup.find("meta", {"property": "og:description"})
        if og_desc:
            desc = og_desc.get("content", "")
            bio = desc.split("–")[-1].strip() if "–" in desc else desc
            # Extract numbers if available
            m = re.search(r"([\d,\.KMB]+)\s+Followers?,\s+([\d,\.KMB]+)\s+Following?,\s+([\d,\.KMB]+)\s+Posts?", desc)
            if m:
                followers = _to_int_safe(m.group(1))
                following = _to_int_safe(m.group(2))
                posts = _to_int_safe(m.group(3))

    return {
        "username": username,
        "full_name": full_name,
        "followers": followers,
        "following": following,
        "posts": posts,
        "bio": bio,
        "avatar": avatar,
    }


# --- public API used by views/tasks ---
def scrape_instagram_profile(username: str) -> dict:
    """
    Fetch and parse profile info only (no posts here),
    return structured dict. You can persist in tasks.py.
    """
    html, source = _fetch_instagram_html(username)
    if not html:
        return {"success": False, "error": f"Failed to fetch HTML: {source}"}

    parsed = parse_instagram_html(html)
    return {"success": True, "source": source, **parsed}
