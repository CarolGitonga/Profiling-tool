from django.shortcuts import render, redirect, get_object_or_404
from .models import Profile
from .forms import UsernameSearchForm
from .utils import scrape_twitter_bio
from profiles.utils import unscrape_twitter_bio
from django.contrib import messages

# Create your views here.
def search_profile(request):
    if request.method == 'POST':
        form = UsernameSearchForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            bio = scrape_twitter_bio(username)
            profile, _ = Profile.objects.get_or_create(username=username, platform='Twitter')
            profile.full_name = username.title()
            profile.save()
            return redirect('profile_dashboard', pk=profile.pk)
    else:
            form = UsernameSearchForm()
    return render(request, 'profiles/search.html', {'form': form})

def profile_dashboard(request, pk):
    profile = get_object_or_404(Profile, pk=pk)
    return render(request, 'profiles/dashboard.html', {'profile': profile})

def delete_twitter_data(request, username):
    if request.method == 'POST':
        success = unscrape_twitter_bio(username)
        if success:
            messages.success(request, "Twitter data removed successfully.")
        else:
            messages.error(request, "Profile not found.")
        return redirect('search_profile')
     # 🚨 Handle invalid request methods (e.g., GET)
    messages.error(request, "Invalid request method.")
    return redirect('search_profile')
    
          