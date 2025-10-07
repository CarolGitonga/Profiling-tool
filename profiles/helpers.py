import os
from celery import Celery
from django.conf import settings

def send_tiktok_task(username: str):
    """
    Sends a TikTok scraping task to the appropriate Redis queue.
    - Local dev → uses local Docker Redis.
    - Production → uses Render Redis.
    """
    is_local = "render" not in os.getenv("RENDER", "").lower() and "DESKTOP" in os.getenv("COMPUTERNAME", "").upper()
    broker_url = "redis://localhost:6379/0" if is_local else settings.CELERY_BROKER_URL
    backend_url = "redis://localhost:6379/0" if is_local else settings.CELERY_RESULT_BACKEND

    # Optional visual feedback in your terminal
    env = "LOCAL Docker Redis" if is_local else "Render Redis"
    print(f"🚀 Sending TikTok task via {env}: {broker_url}")

    # Build Celery instance and send task
    app = Celery("people_profiling", broker=broker_url)
    app.conf.update(result_backend=backend_url)

    app.send_task(
        "profiles.tasks.scrape_tiktok_task",
        args=[username],
        queue="tiktok"
    )
