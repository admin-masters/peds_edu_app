from django.urls import path

from . import views

app_name = "sharing"

urlpatterns = [
    path("", views.home, name="home"),
    path("clinic/<str:doctor_id>/share/", views.doctor_share, name="doctor_share"),
    path("p/<str:doctor_id>/v/<str:video_code>/", views.patient_video, name="patient_video"),
    path("p/<str:doctor_id>/c/<str:cluster_code>/", views.patient_cluster, name="patient_cluster"),
]
