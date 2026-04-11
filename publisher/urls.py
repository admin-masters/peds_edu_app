from django.urls import path
from . import views

app_name = "publisher"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("pe-system/login/", views.pe_records_login, name="pe_records_login"),
    path("pe-system/logout/", views.pe_records_logout, name="pe_records_logout"),
    path("pe-system/", views.pe_records_dashboard, name="pe_records_dashboard"),
    path(
        "pe-system/campaigns/<str:campaign_id>/",
        views.pe_campaign_record_edit,
        name="pe_campaign_record_edit",
    ),
    path(
        "pe-system/campaigns/<str:campaign_id>/delete/",
        views.pe_campaign_record_delete,
        name="pe_campaign_record_delete",
    ),
    path(
        "pe-system/field-reps/<int:field_rep_id>/",
        views.pe_field_rep_record_edit,
        name="pe_field_rep_record_edit",
    ),
    path(
        "pe-system/field-reps/<int:field_rep_id>/delete/",
        views.pe_field_rep_record_delete,
        name="pe_field_rep_record_delete",
    ),
    path(
        "pe-system/doctors/<str:doctor_id>/",
        views.pe_doctor_record_edit,
        name="pe_doctor_record_edit",
    ),
    path(
        "pe-system/doctors/<str:doctor_id>/delete/",
        views.pe_doctor_record_delete,
        name="pe_doctor_record_delete",
    ),
    path("system-records/", views.system_records, name="system_records"),
    path(
        "system-records/campaigns/<str:campaign_id>/delete/",
        views.campaign_record_delete,
        name="campaign_record_delete",
    ),
    path(
        "system-records/field-reps/<int:field_rep_id>/",
        views.field_rep_record_edit,
        name="field_rep_record_edit",
    ),
    path(
        "system-records/field-reps/<int:field_rep_id>/delete/",
        views.field_rep_record_delete,
        name="field_rep_record_delete",
    ),
    path(
        "system-records/doctors/<str:doctor_id>/",
        views.doctor_record_edit,
        name="doctor_record_edit",
    ),
    path(
        "system-records/doctors/<str:doctor_id>/delete/",
        views.doctor_record_delete,
        name="doctor_record_delete",
    ),

    # Therapy Areas
    path("therapy-areas/", views.therapy_list, name="therapy_list"),
    path("therapy-areas/new/", views.therapy_create, name="therapy_create"),
    path("therapy-areas/<int:pk>/", views.therapy_edit, name="therapy_edit"),

    # Trigger Clusters
    path("trigger-clusters/", views.trigger_cluster_list, name="triggercluster_list"),
    path("trigger-clusters/new/", views.trigger_cluster_create, name="triggercluster_create"),
    path("trigger-clusters/<int:pk>/", views.trigger_cluster_edit, name="triggercluster_edit"),
    
    # Triggers
    path("triggers/", views.trigger_list, name="trigger_list"),
    path("triggers/new/", views.trigger_create, name="trigger_create"),
    path("triggers/<int:pk>/", views.trigger_edit, name="trigger_edit"),

    # Videos
    path("videos/", views.video_list, name="video_list"),
    path("videos/new/", views.video_create, name="video_create"),
    path("videos/<int:pk>/", views.video_edit, name="video_edit"),

    # Bundles (Video Clusters)
    path("bundles/", views.cluster_list, name="cluster_list"),
    path("bundles/new/", views.cluster_create, name="cluster_create"),
    path("bundles/<int:pk>/", views.cluster_edit, name="cluster_edit"),

    # Trigger Maps
    path("trigger-maps/", views.map_list, name="map_list"),
    path("trigger-maps/new/", views.map_create, name="map_create"),
    path("trigger-maps/<int:pk>/", views.map_edit, name="map_edit"),
]
