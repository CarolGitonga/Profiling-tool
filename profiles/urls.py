from django.urls import path
from . import views
from . import activity_views



urlpatterns = [
    path('search/', views.search_profile, name='search_profile'),
    path('dashboard/<int:pk>/', views.profile_dashboard, name='profile_dashboard'),
    path("activity/<int:pk>/", activity_views.activity_view, name="profile_activity"),
    #path("task-status/<str:task_id>/", views.task_status, name="task_status"),
    path("<str:username>/<str:platform>/dashboard/", views.behavioral_dashboard, name="behavioral_dashboard"),
    path("dashboard/<int:pk>/", views.profile_dashboard, name="profile_dashboard"),


    # Unscrape/delete routes
    path('unscrape/<str:username>/', views.delete_twitter_data, name='unscrape_twitter'),
    path('unscrape/github/<str:username>/', views.delete_github_data, name='unscrape_github'),
    path('unscrape/instagram/<str:username>/', views.delete_instagram_data, name='unscrape_instagram'),
    path('unscrape/tiktok/<str:username>/', views.delete_tiktok_data, name='unscrape_tiktok'), 
]