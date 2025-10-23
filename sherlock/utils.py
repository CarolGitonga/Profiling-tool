# sherlock/utils.py
import os, sys, subprocess
from django.conf import settings

def run_sherlock(username: str):
    """
    Run Sherlock for a given username and return parsed results as a list of dicts.
    """

    # Safer output directory (works locally + Render)
    sherlock_output_dir = getattr(settings, "SHERLOCK_OUTPUT", os.path.join("/tmp", "sherlock"))
    os.makedirs(sherlock_output_dir, exist_ok=True)
    output_file = os.path.join(sherlock_output_dir, f"{username}.txt")

    result = subprocess.run(
        [
            'sherlock',
            username,
            '--print-found',
            '--timeout', '15',
            '--output', output_file,
            "--site", "github",
            "--site", "twitter",
            "--site", "linkedin",
            "--site", "medium",
            "--site", "instagram",
            "--site", "trello",
            "--site", "huggingface",
            "--site", "hackerrank",
            "--site", "youtube",
            "--site", "codecademy",
            "--site", "dribble",
            "--site", "chess",
            "--site", "discord",
            "--site", "reddit",
            "--site", "strava",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        #cwd=settings.SHERLOCK_PATH
    )

    # Debugging logs
    if result.stderr:
        print("Sherlock Error:", result.stderr)

    raw_output = result.stdout + result.stderr
    sherlock_results = []

    for line in raw_output.splitlines():
        if line.startswith("[+]"):
            parts = line.replace("[+] ", "").split(": ", 1)
            if len(parts) == 2:
                platform, url = parts
                sherlock_results.append({
                    "platform": platform.strip(),
                    "url": url.strip()
                })

    return sherlock_results
