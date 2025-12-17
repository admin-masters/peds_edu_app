from django.urls import path
from . import views

app_name = "publisher"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    path("videos/", views.video_list, name="video_list"),
    path("videos/new/", views.video_create, name="video_create"),
    path("videos/<int:pk>/", views.video_edit, name="video_edit"),

    path("bundles/", views.cluster_list, name="cluster_list"),
    path("bundles/new/", views.cluster_create, name="cluster_create"),
    path("bundles/<int:pk>/", views.cluster_edit, name="cluster_edit"),

    path("trigger-maps/", views.map_list, name="map_list"),
    path("trigger-maps/new/", views.map_create, name="map_create"),
    path("trigger-maps/<int:pk>/", views.map_edit, name="map_edit"),
]
