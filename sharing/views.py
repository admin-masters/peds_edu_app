from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import DoctorProfile
from catalog.constants import LANGUAGE_CODES, LANGUAGES
from catalog.models import Video, VideoLanguage, VideoCluster, VideoClusterLanguage

from .services import build_whatsapp_message_prefixes, get_catalog_json_cached


@login_required
def home(request: HttpRequest) -> HttpResponse:
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor:
        return redirect("accounts:logout")
    return redirect("sharing:doctor_share", doctor_id=doctor.doctor_id)


@login_required
def doctor_share(request: HttpRequest, doctor_id: str) -> HttpResponse:
    doctor = getattr(request.user, "doctor_profile", None)
    if not doctor or doctor.doctor_id != doctor_id:
        return HttpResponseForbidden("Not allowed")

    catalog_json = get_catalog_json_cached()
    message_prefixes = build_whatsapp_message_prefixes(request.user.full_name)

    return render(
        request,
        "sharing/share.html",
        {
            "doctor": doctor,
            "catalog_json": catalog_json,
            "message_prefixes": message_prefixes,
            "languages": LANGUAGES,
        },
    )


def patient_video(request: HttpRequest, doctor_id: str, video_code: str) -> HttpResponse:
    doctor = get_object_or_404(DoctorProfile.objects.select_related("clinic", "user"), doctor_id=doctor_id)
    lang = request.GET.get("lang", "en")
    if lang not in LANGUAGE_CODES:
        lang = "en"

    video = get_object_or_404(Video, code=video_code)
    vlang = VideoLanguage.objects.filter(video=video, language_code=lang).first() or VideoLanguage.objects.filter(
        video=video, language_code="en"
    ).first()

    return render(
        request,
        "sharing/patient_video.html",
        {
            "doctor": doctor,
            "clinic": doctor.clinic,
            "video": video,
            "vlang": vlang,
            "languages": LANGUAGES,
            "selected_lang": lang,
        },
    )


def patient_cluster(request: HttpRequest, doctor_id: str, cluster_code: str) -> HttpResponse:
    doctor = get_object_or_404(DoctorProfile.objects.select_related("clinic", "user"), doctor_id=doctor_id)
    lang = request.GET.get("lang", "en")
    if lang not in LANGUAGE_CODES:
        lang = "en"

    cluster = get_object_or_404(
        VideoCluster.objects.select_related("trigger").prefetch_related("cluster_videos__video"), code=cluster_code
    )

    cluster_name = (
        VideoClusterLanguage.objects.filter(video_cluster=cluster, language_code=lang).first()
        or VideoClusterLanguage.objects.filter(video_cluster=cluster, language_code="en").first()
    )

    # Build ordered list of videos with localized titles
    videos = []
    for cv in cluster.cluster_videos.all().order_by("sort_order"):
        v = cv.video
        vlang = VideoLanguage.objects.filter(video=v, language_code=lang).first() or VideoLanguage.objects.filter(
            video=v, language_code="en"
        ).first()
        videos.append({"video": v, "vlang": vlang})

    return render(
        request,
        "sharing/patient_cluster.html",
        {
            "doctor": doctor,
            "clinic": doctor.clinic,
            "cluster": cluster,
            "cluster_lang": cluster_name,
            "videos": videos,
            "languages": LANGUAGES,
            "selected_lang": lang,
        },
    )
