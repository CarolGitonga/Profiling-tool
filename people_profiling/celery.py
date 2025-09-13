import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'people_profiling.settings')

app = Celery('Profiling')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()
