from django.db import models
 
class Profile(models.Model):
    username = models.CharField(max_length=150)
    full_name = models.CharField(max_length=255, blank=True, null=True)
    platform = models.CharField(max_length=100)
    avatar_url = models.URLField(blank=True, null=True)
    date_profiled = models.DateTimeField(auto_now_add=True)
    # New fields for GitHub
    github_created_at = models.DateTimeField(blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    company = models.CharField(max_length=255, blank=True, null=True)
    blog = models.URLField(blank=True, null=True)

    class Meta:
        unique_together = ('username', 'platform')  # ensure uniqueness only per platform

    def __str__(self):
        return f"{self.username} ({self.platform})"
    
    
class SocialMediaAccount(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    platform = models.CharField(max_length=100)
    bio = models.TextField(blank=True, null=True)
    followers = models.IntegerField(default=0)
    following = models.IntegerField(default=0)
    posts_collected = models.IntegerField(default=0)
    public_repos = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.platform} account for {self.profile.username}"