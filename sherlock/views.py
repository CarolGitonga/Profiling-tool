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
            result = subprocess.run(
                [
                    sys.executable,  # path to Python interpreter
                    sherlock_script,
                    username,
                    '--print-found',
                    '--timeout', '10',
                    '--output', output_file
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            output = result.stdout + result.stderr
            return render(request, 'sherlock/result.html', {'output': output})

        except Exception as e:
            return HttpResponse(f"Error running Sherlock: {e}")

    return render(request, 'sherlock/search.html')
