from django.urls import path
from . import views



urlpatterns = [
    path('search/', views.search_profile, name='search_profile'),
    path('dashboard/<int:pk>/', views.profile_dashboard, name='profile_dashboard'),
    path('unscrape/<str:username>/', views.delete_twitter_data, name='unscrape_twitter'),
]