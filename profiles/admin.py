from django.contrib import admin
from .models import BehavioralAnalysis, Profile, RawPost, SocialMediaAccount


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = (
        'username', 'platform', 'full_name', 'location',
        'date_profiled', 'profile_created_at', 'github_created_at',
        'tiktok_user_id', 'verified',
    )
    list_filter = ('platform', 'date_profiled', 'verified')
    search_fields = ('username', 'full_name', 'location', 'company', 'tiktok_user_id')
    ordering = ('-date_profiled',)


@admin.register(SocialMediaAccount)
class SocialMediaAccountAdmin(admin.ModelAdmin):
    list_display = (
        'profile', 'platform', 'followers', 'following',
        'hearts', 'videos',        # TikTok stats
        'public_repos',            # GitHub
        'posts_collected', 'is_private',
        'show_verified',
    )
    list_filter = ('platform', 'created_at', 'is_private')
    search_fields = ('profile__username', 'bio', 'tiktok_region')
    ordering = ('-created_at',)

    # Show Profile.verified inside SocialMediaAccount
    def show_verified(self, obj):
        return obj.profile.verified
    show_verified.short_description = "Verified"
    show_verified.boolean = True  # adds ✅/❌ in admin list


@admin.register(RawPost)
class RawPostAdmin(admin.ModelAdmin):
    list_display = ("profile", "platform", "short_content", "timestamp", "likes", "comments", "sentiment_score")
    search_fields = ("profile__username", "content", "platform")
    list_filter = ("platform", "timestamp")

    def short_content(self, obj):
        """Show first 50 chars of post content."""
        return (obj.content[:50] + "...") if len(obj.content) > 50 else obj.content
    short_content.short_description = "Post Content"


@admin.register(BehavioralAnalysis)
class BehavioralAnalysisAdmin(admin.ModelAdmin):
    list_display = ("profile", "sentiment_score", "avg_post_time", "analyzed_at")
    search_fields = ("profile__username",)
