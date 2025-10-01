web: gunicorn people_profiling.wsgi:application --workers=4
worker: celery -A people_profiling worker -l info
