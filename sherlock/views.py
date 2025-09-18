import os
import sys
import subprocess
from django.conf import settings
from django.shortcuts import render
from django.http import HttpResponse

def sherlock_search(request):
    if request.method == 'POST':
        username = request.POST.get('username')

        sherlock_script = os.path.join(settings.SHERLOCK_PATH, 'sherlock_project', 'sherlock.py')
        output_file = os.path.join(settings.SHERLOCK_OUTPUT, f"{username}.txt")

        try:
            os.makedirs(settings.SHERLOCK_OUTPUT, exist_ok=True)
            result = subprocess.run(
                [
                    sys.executable,  # path to Python interpreter
                    '-m', 'sherlock_project',
                    username,
                    '--print-found',
                    '--timeout', '5',
                    '--output', output_file,
                    "--site", "github",
                    "--site", "twitter",
                    "--site", "linkedin",
                    "--site", "medium",
                    "--site", "instagram",
                    "--site", "trello",
                    "--site", "huggingface",
                    "--site", "instagram",
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
                cwd=settings.SHERLOCK_PATH
            )

            output = result.stdout + result.stderr
            return render(request, 'sherlock/result.html', {'output': output})

        except Exception as e:
            return HttpResponse(f"Error running Sherlock: {e}")

    return render(request, 'sherlock/search.html')
