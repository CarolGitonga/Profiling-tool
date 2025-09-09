from django.contrib import admin
from .models import Profile, SocialMediaAccount


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        'username', 'platform', 'full_name', 'location',
        'date_profiled', 'profile_created_at', 'github_created_at'
    )
    list_filter = ('platform', 'date_profiled')
    search_fields = ('username', 'full_name', 'location', 'company')
    ordering = ('-date_profiled',)


@admin.register(SocialMediaAccount)
class SocialMediaAccountAdmin(admin.ModelAdmin):
    list_display = (
        'profile', 'platform', 'followers', 'following',
        'public_repos', 'posts_collected', 'is_private'
    )
    list_filter = ('platform', 'created_at', 'is_private')
    search_fields = ('profile__username', 'bio')
    ordering = ('-created_at',)

