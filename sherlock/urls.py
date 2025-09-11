from django.urls import path
from . import views

urlpatterns = [
    path('search/', views.sherlock_search, name='sherlock_search'),
]
