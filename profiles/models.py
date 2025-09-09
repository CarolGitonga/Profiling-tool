from django.db import models
 
class Profile(models.Model):
    PLATFORM_CHOICES = [
        ('Twitter', 'Twitter'),
        ('GitHub', 'GitHub'),
        ('Instagram', 'Instagram'),
        # Add more platforms as needed
    ]
    username = models.CharField(max_length=150)
    full_name = models.CharField(max_length=255, blank=True, null=True)
    platform = models.CharField(max_length=100, choices=PLATFORM_CHOICES)
    avatar_url = models.URLField(blank=True, null=True)
    date_profiled = models.DateTimeField(auto_now_add=True)

    # Optional fields (platform-specific)
    profile_created_at = models.DateTimeField(blank=True, null=True)  # For Twitter, Instagram
    github_created_at = models.DateTimeField(blank=True, null=True)   # For GitHub
    location = models.CharField(max_length=255, blank=True, null=True)  # Common field
    company = models.CharField(max_length=255, blank=True, null=True)   # GitHub
    blog = models.URLField(blank=True, null=True)  # GitHub or personal site

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
    

    def __str__(self):
        return f"{self.platform} account for {self.profile.username}"