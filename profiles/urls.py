from django.urls import path
from . import views



urlpatterns = [
    path('search/', views.search_profile, name='search_profile'),
    path('dashboard/<int:pk>/', views.profile_dashboard, name='profile_dashboard'),

    # Unscrape/delete routes
    path('unscrape/<str:username>/', views.delete_twitter_data, name='unscrape_twitter'),
    path('unscrape/github/<str:username>/', views.delete_github_data, name='unscrape_github'),
    path('unscrape/instagram/<str:username>/', views.delete_instagram_data, name='unscrape_instagram'),
    path('unscrape/tiktok/<str:username>/', views.delete_tiktok_data, name='unscrape_tiktok'), 
]