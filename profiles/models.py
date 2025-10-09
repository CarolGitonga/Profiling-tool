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

# ✅ New Post model
class Post(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="posts")
    platform = models.CharField(max_length=100)  # Twitter, Instagram, etc.
    content = models.TextField(blank=True, null=True)  # optional: store text, captions, commit msg, etc.
    url = models.URLField(blank=True, null=True)       # optional: link to post
    created_at = models.DateTimeField()  # actual time the post was made

    likes = models.IntegerField(default=0)     # optional metrics
    comments = models.IntegerField(default=0)
    shares = models.IntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.platform} post by {self.profile.username} on {self.created_at:%Y-%m-%d}"