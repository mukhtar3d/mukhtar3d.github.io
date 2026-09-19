from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("filters", views.filters, name="filters"),
    path("recommend", views.recommend, name="recommend"),
    path("universities", views.universities, name="universities"),
    path("universities/<int:pk>", views.university_detail, name="university-detail"),
    path("universities/<int:pk>/images", views.university_images, name="university-images"),
]
