from django.urls import path

from . import views

app_name = "sharing"

urlpatterns = [
    path("", views.home, name="home"),
    path("clinic/<str:doctor_id>/share/", views.doctor_share, name="doctor_share"),
    path("api/share-activity/", views.create_share_activity, name="create_share_activity"),
    path("api/playback-event/", views.log_playback_event, name="log_playback_event"),
    path("api/banner-click/", views.log_banner_click, name="log_banner_click"),
    path("tracking/login/", views.tracking_login, name="tracking_login"),
    path("tracking/logout/", views.tracking_logout, name="tracking_logout"),
    path("tracking/", views.tracking_dashboard, name="tracking_dashboard"),
    path("p/<str:doctor_id>/v/<str:video_code>/", views.patient_video, name="patient_video"),
    path("p/<str:doctor_id>/c/<str:cluster_code>/", views.patient_cluster, name="patient_cluster"),
]
