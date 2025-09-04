from django.db import models

# Create your models here.
class Profile(models.Model):
    username = models.CharField(max_length=150, unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    platform = models.CharField(max_length=100)
    avatar_url = models.URLField(blank=True)
    date_profiled = models.DateTimeField(auto_now_add=True)

class SocialMediaAccount(models.Model):
    profile = models.ForeignKey(Profile, on_delete=models.CASCADE)
    platform = models.CharField(max_length=100)
    bio = models.TextField(blank=True)
    followers = models.IntegerField(default=0)
    posts_collected = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


