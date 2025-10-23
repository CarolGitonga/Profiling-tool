from django.urls import path
from . import views

urlpatterns = [
    path("", views.landing_page, name="landing_page"),
    path("about/", views.about_page, name="about"),
     path("contact/", views.contact_page, name="contact"),
    

    
]
