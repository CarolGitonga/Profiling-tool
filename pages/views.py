from django.shortcuts import render

def landing_page(request):
    # just render the landing page with empty results
    return render(request, "pages/landing.html", {"profile": []})

def about_page(request):
    return render(request, "pages/about.html")

def contact_page(request):
    success = False
    if request.method == "POST":
        name = request.POST.get("name")
        email = request.POST.get("email")
        message = request.POST.get("message")

        # (Optional) You can later connect this to an email backend or database
        print(f"New message from {name} ({email}): {message}")
        success = True

    return render(request, "pages/contact.html", {"success": success})
