from django.test import TestCase, Client
from django.urls import reverse
from .models import Profile, SocialMediaAccount
from .utils import scrape_twitter_bio
from profiles.utils import unscrape_twitter_bio

# Create your tests here.
class ProfileAppTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.username = "testuser123"
        self.profile = Profile.objects.create(username=self.username, platform="Twitter")

    def test_profile_model_creation(self):
        self.assertEqual(self.profile.username, self.username)
        self.assertEqual(self.profile.platform, "Twitter")

    def test_scrape_twitter_bio_function(self):
        bio = scrape_twitter_bio("jack") # Use a known public Twitter handle
        self.assertIsInstance(bio, str)
        
    def test_unscrape_twitter_bio_function(self):
        SocialMediaAccount.objects.create(profile=self.profile, platform="Twitter", bio="Test Bio")
        result = unscrape_twitter_bio(self.username)
        self.assertTrue(result)
        self.assertEqual(SocialMediaAccount.objects.filter(profile=self.profile).count(), 0)

    def test_search_profile_view_get(self):
        response = self.client.get(reverse("search_profile"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "profiles/search.html")

    def test_search_profile_view_post(self):
        response = self.client.post(reverse("search_profile"), {"username": self.username})
        self.assertEqual(response.status_code, 302) # Should redirect to dashboard

    def test_profile_dashboard_view(self):
        response = self.client.get(reverse("profile_dashboard", args=[self.profile.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.profile.username)

    def test_unscrape_view(self):
        SocialMediaAccount.objects.create(profile=self.profile, platform="Twitter", bio="Data")
        response = self.client.post(reverse("unscrape_twitter", args=[self.username]))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SocialMediaAccount.objects.filter(profile=self.profile).count(), 0)
