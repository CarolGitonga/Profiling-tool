from django.shortcuts import render, redirect, get_object_or_404
from profiles.utils.github_scraper import scrape_github_profile, unscrape_github_profile
from profiles.utils.instagram_scraper import scrape_instagram_profile, unscrape_instagram_profile
from profiles.utils.tiktok_scraper import scrape_tiktok_profile, unscrape_tiktok_profile
from profiles.utils.twitter_scraper import get_twitter_profile, unscrape_twitter_bio
from .models import Profile, SocialMediaAccount
from .forms import UsernameSearchForm
from django.contrib import messages
from dateutil.parser import parse as parse_date


# Create your views here.
def search_profile(request):
    if request.method == 'POST':
        form = UsernameSearchForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username'].strip()
            platform = form.cleaned_data['platform']

            # --- TWITTER ---
            if platform == 'Twitter':
               twitter_data = get_twitter_profile(username)

               if not twitter_data:
                   messages.error(request, f"Could not retrieve Twitter profile for {username}.")
                   return redirect('search_profile')
               
               
               profile, _ = Profile.objects.get_or_create(username=username, platform='Twitter')
               profile.full_name = twitter_data['name']
               profile.avatar_url = twitter_data['avatar_url']
               profile.profile_created_at = twitter_data['created_at'] 
               profile.save()

               SocialMediaAccount.objects.update_or_create(
                  profile=profile,  
                  platform='Twitter',
                  defaults={ 
                    'bio': twitter_data['bio'],
                    'followers': twitter_data['followers_count'],
                    'posts_collected': 0,
                   }
                )

            # Scrape GitHub profile
            elif platform == 'GitHub':
                github_data = scrape_github_profile(username)
                profile, _ = Profile.objects.get_or_create(username=username, platform='GitHub')
                profile.full_name = github_data['name']
                profile.avatar_url = f"https://github.com/{username}.png"

                if github_data['created_at']:
                    profile.github_created_at = parse_date(github_data['created_at'])

                profile.location = github_data.get('location')
                profile.company = github_data.get('company') 
                profile.blog = github_data.get('blog')   
                profile.save()

                 # Save or update social media account info
                SocialMediaAccount.objects.update_or_create(
                    profile=profile,  
                    platform='GitHub',
                    defaults={ 
                      'bio': github_data['bio'],
                      'followers': github_data['followers'] or 0,
                      'following': github_data['following'] or 0,
                      'public_repos': github_data['public_repos'] or 0,
                      'posts_collected': 0,
                    }
                )  
             # --- INSTAGRAM ---
            elif platform == 'Instagram':
                insta_data = scrape_instagram_profile(username)
                if not insta_data:
                    messages.error(request, f"Could not retrieve Instagram profile for {username}.")
                    return redirect('search_profile')
                
                profile, _ = Profile.objects.get_or_create(username=username, platform='Instagram')
                profile.full_name = insta_data['full_name']
                profile.avatar_url = insta_data['profile_pic_url']
                profile.save()

                SocialMediaAccount.objects.update_or_create(
                    profile=profile,
                    platform='Instagram',
                    defaults={
                        'bio': insta_data['bio'],
                        'followers': insta_data['followers'],
                        'following': insta_data['following'],
                        'posts_collected': insta_data['posts'],
                    }
                )
            # --- TIKTOK ---
            elif platform == 'TikTok':
                tiktok_data = scrape_tiktok_profile(username)
                if not tiktok_data or 'error' in tiktok_data:
                    messages.error(request, f"Could not retrieve TikTok profile for {username}.")
                    return redirect('search_profile')
                
                profile, _ = Profile.objects.get_or_create(username=username, platform='TikTok')
                profile.full_name = tiktok_data['nickname']
                profile.avatar_url = tiktok_data['avatar']
                profile.verified = tiktok_data['verified']
                profile.save()

                SocialMediaAccount.objects.update_or_create(
                    profile=profile,
                    platform='TikTok',
                    defaults={
                        'bio': tiktok_data['bio'],
                        'followers': tiktok_data['followers'],
                        'following': tiktok_data['following'],
                        'hearts': tiktok_data['likes'],
                        'videos': tiktok_data['video_count'],
                        'verified': tiktok_data['verified'],
                        'posts_collected': 0,
                    }
                )

            return redirect('profile_dashboard', pk=profile.pk)
    else: 
            form = UsernameSearchForm()
    return render(request, 'profiles/search.html', {'form': form})

def delete_twitter_data(request, username):
    success = unscrape_twitter_bio(username)
    if success:
         messages.success(request, "Twitter data removed successfully.")
    else:
         messages.error(request, "Profile not found or already removed.")
    return redirect('search_profile')

def delete_github_data(request, username):
    success = unscrape_github_profile(username)
    if success:
        messages.success(request, "GitHub data removed successfully.")
    else:
        messages.error(request, "GitHub profile not found or already removed.")
    return redirect('search_profile')

def delete_instagram_data(request, username):
    success = unscrape_instagram_profile(username)
    if success:
        messages.success(request, "Instagram data removed successfully.")
    else:
        messages.error(request, "Instagram profile not found or already removed.")
    return redirect('search_profile')

def delete_tiktok_data(request, username):
    success = unscrape_tiktok_profile(username)
    if success:
        messages.success(request, "TikTok data removed successfully.")
    else:
        messages.error(request, "TikTok profile not found or already removed.")
    return redirect('search_profile')

def profile_dashboard(request, pk):
    profile = get_object_or_404(Profile, pk=pk)
    profiles = [profile]  # wrap single profile in a list
    accounts = SocialMediaAccount.objects.filter(profile=profile)
    return render(request, 'profiles/dashboard.html', {
        'profiles': profiles,
        'accounts': accounts,
    })



   
    
          