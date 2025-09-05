from django.shortcuts import render, redirect, get_object_or_404
from .models import Profile, SocialMediaAccount
from .forms import UsernameSearchForm
from .utils import scrape_twitter_bio, unscrape_twitter_bio, scrape_github_profile, unscrape_github_profile
# from profiles.utils import unscrape_twitter_bio
from django.contrib import messages

# Create your views here.
def search_profile(request):
    if request.method == 'POST':
        form = UsernameSearchForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username'].strip()
            platform = form.cleaned_data['platform']

            # --- TWITTER ---
            if platform == 'Twitter':
               bio = scrape_twitter_bio(username)
               profile, _ = Profile.objects.get_or_create(username=username, platform='Twitter')
               profile.full_name = username.title()
               profile.avatar_url = f"https://x.com/{username}/photo"
               profile.save()

               SocialMediaAccount.objects.update_or_create(
                  profile=profile,  
                  platform='Twitter',
                  defaults={ 
                    'bio': bio,
                    'followers': 0,
                    'posts_collected': 0,
                   }
                )

            # Scrape GitHub profile
            elif platform == 'GitHub':
                github_data = scrape_github_profile(username)
                profile, _ = Profile.objects.get_or_create(username=username, platform='GitHub')
                profile.full_name = github_data['name']
                profile.avatar_url = f"https://github.com/{username}.png"
                profile.save()

                 # Save or update social media account info
                SocialMediaAccount.objects.update_or_create(
                    profile=profile,  
                    platform='GitHub',
                    defaults={ 
                      'bio': github_data['bio'],
                      'followers': 0,
                      'posts_collected': 0,
                    }
                )    
            return redirect('profile_dashboard', pk=profile.pk)
    else:
            form = UsernameSearchForm()
    return render(request, 'profiles/search.html', {'form': form})

def profile_dashboard(request, pk):
    profile = get_object_or_404(Profile, pk=pk)
    return render(request, 'profiles/dashboard.html', {'profile': profile})

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

def profile_dashboard_all(request, username):
     # Make case-insensitive match
     profiles = Profile.objects.filter(username__iexact=username)
     accounts = SocialMediaAccount.objects.filter(profile__in=profiles)
     return render(request, 'profiles/dashboard.html', {
          'profiles': profiles,
          'accounts': accounts
           })


   
    
          