from django.db import models
 
class Profile(models.Model):
    PLATFORM_CHOICES = [
        ('Twitter', 'Twitter'),
        ('GitHub', 'GitHub'),
        ('Instagram', 'Instagram'),
        ('TikTok', 'TikTok'),
        # Add more platforms as needed
    ]
    username = models.CharField(max_length=255)
    full_name = models.CharField(max_length=1000, blank=True, null=True)
    platform = models.CharField(max_length=100, choices=PLATFORM_CHOICES)
    avatar_url = models.URLField(max_length=2000, blank=True, null=True)
    date_profiled = models.DateTimeField(auto_now_add=True)
    posts_count = models.PositiveIntegerField(default=0) 

    # Optional fields (platform-specific)
    profile_created_at = models.DateTimeField(blank=True, null=True)  # For Twitter, Instagram
    github_created_at = models.DateTimeField(blank=True, null=True)   # For GitHub
    location = models.CharField(max_length=255, blank=True, null=True)  # Common field
    company = models.CharField(max_length=255, blank=True, null=True)   # GitHub
    blog = models.URLField(blank=True, null=True)  # GitHub or personal site

     # ✅ TikTok-specific
    verified = models.BooleanField(default=False)
    tiktok_created_at = models.DateTimeField(blank=True, null=True)
    tiktok_user_id = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        unique_together = ('username', 'platform')  # ensure uniqueness only per platform

    def __str__(self):
        return f"{self.username} ({self.platform})"
    
    
class SocialMediaAccount(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    platform = models.CharField(max_length=100)

    # Common fields
    bio = models.TextField(blank=True, null=True)
    followers = models.IntegerField(default=0)
    following = models.IntegerField(default=0)
    posts_collected = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    # GitHub-specific
    public_repos = models.IntegerField(default=0)
    
    # Instagram-specific (optional)
    is_private = models.BooleanField(default=False)
    external_url = models.URLField(blank=True, null=True)

     # ✅ TikTok-specific
    hearts = models.IntegerField(default=0)
    videos = models.IntegerField(default=0)
    private_account = models.BooleanField(default=False)
    tiktok_bio_link = models.URLField(blank=True, null=True)
    tiktok_region = models.CharField(max_length=100, blank=True, null=True)
    verified = models.BooleanField(default=False)   # ✅ add this
    

    def __str__(self):
        return f"{self.platform} account for {self.profile.username}"

class RawPost(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    platform = models.CharField(max_length=50)
    post_id = models.CharField(max_length=255, blank=True, null=True)
    content = models.TextField()
    timestamp = models.DateTimeField(blank=True, null=True)
    likes = models.IntegerField(default=0)
    comments = models.IntegerField(default=0)
    sentiment_score = models.FloatField(blank=True, null=True)

    def __str__(self):
        return f"{self.platform} post by {self.profile.username}"

    
class BehavioralAnalysis(models.Model):
    profile = models.OneToOneField("Profile", on_delete=models.CASCADE, related_name="behavior_analysis")
    # Posting patterns
    avg_post_time = models.CharField(max_length=50, null=True, blank=True)
    most_active_days = models.JSONField(null=True, blank=True)
    # Language & sentiment
    sentiment_score = models.FloatField(null=True, blank=True)
    top_keywords = models.JSONField(null=True, blank=True)
    # Geolocation
    geo_locations = models.JSONField(null=True, blank=True)
    # Connections
    network_size = models.IntegerField(null=True, blank=True)
    network_density = models.FloatField(null=True, blank=True)
    # Interests
    interests = models.JSONField(null=True, blank=True)
    # Last analysis date
    analyzed_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Behavioral Analysis for {self.profile.username}"
    class Meta:
        verbose_name_plural = "Behavioral Analyses"
    def behavior(self):
        return getattr(self, "behavior_analysis", None)