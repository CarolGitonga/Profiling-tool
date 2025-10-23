from django.shortcuts import render

def landing_page(request):
    # just render the landing page with empty results
    return render(request, "pages/landing.html", {"profile": []})

def about_page(request):
    return render(request, "pages/about.html")
