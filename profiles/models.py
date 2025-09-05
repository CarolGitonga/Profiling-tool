from django.db import models
 
class Profile(models.Model):
    username = models.CharField(max_length=150)
    full_name = models.CharField(max_length=255, blank=True)
    platform = models.CharField(max_length=100)
    avatar_url = models.URLField(blank=True)
    date_profiled = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('username', 'platform')  # ensure uniqueness only per platform

    def __str__(self):
        return f"{self.username} ({self.platform})"
    
    
class SocialMediaAccount(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    platform = models.CharField(max_length=100)
    bio = models.TextField(blank=True)
    followers = models.IntegerField(default=0)
    posts_collected = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.platform} account for {self.profile.username}"