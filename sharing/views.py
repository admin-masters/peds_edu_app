from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import DoctorProfile
from catalog.constants import LANGUAGE_CODES, LANGUAGES
from catalog.models import Video, VideoLanguage, VideoCluster

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

    catalog_json = get_catalog_json_cached(force_refresh=True)

    # Make message prefixes doctor-specific (template uses catalog.message_prefixes)
    catalog_json = {
        **catalog_json,
        "message_prefixes": build_whatsapp_message_prefixes(doctor.full_name),
    }

    return render(
        request,
        "sharing/share.html",
        {
            "doctor": doctor,
            "catalog_json": catalog_json,
            "languages": LANGUAGES,
        },
    )


def patient_video(request: HttpRequest, doctor_id: str, video_code: str) -> HttpResponse:
    doctor = get_object_or_404(DoctorProfile.objects.select_related("clinic", "user"), doctor_id=doctor_id)

    lang = request.GET.get("lang", "en")
    if lang not in LANGUAGE_CODES:
        lang = "en"

    video = get_object_or_404(Video, code=video_code)

    vlang = (
        VideoLanguage.objects.filter(video=video, language_code=lang).first()
        or VideoLanguage.objects.filter(video=video, language_code="en").first()
    )

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
    """
    Required because sharing/urls.py references this view.
    Shows a simple cluster landing page listing videos in a VideoCluster.

    cluster_code is treated as:
      - VideoCluster.code if present
      - otherwise as numeric PK string
    """
    doctor = get_object_or_404(DoctorProfile.objects.select_related("clinic", "user"), doctor_id=doctor_id)

    lang = request.GET.get("lang", "en")
    if lang not in LANGUAGE_CODES:
        lang = "en"

    # Resolve cluster by code or pk
    cluster = None
    try:
        cluster = VideoCluster.objects.filter(code=cluster_code).first()
    except Exception:
        cluster = None

    if cluster is None and cluster_code.isdigit():
        cluster = get_object_or_404(VideoCluster, pk=int(cluster_code))
    elif cluster is None:
        # Hard 404 if neither matched
        cluster = get_object_or_404(VideoCluster, pk=-1)

    # Fetch videos in this cluster (if M2M exists)
    try:
        videos = cluster.videos.all().order_by("sort_order", "id")
    except Exception:
        videos = cluster.videos.all().order_by("id")

    # Build language-specific title/url
    items = []
    for v in videos:
        vlang = (
            VideoLanguage.objects.filter(video=v, language_code=lang).first()
            or VideoLanguage.objects.filter(video=v, language_code="en").first()
        )
        items.append(
            {
                "video": v,
                "title": (vlang.title if vlang else v.code),
                "url": (vlang.youtube_url if vlang else ""),
            }
        )

    return render(
        request,
        "sharing/patient_cluster.html",
        {
            "doctor": doctor,
            "clinic": doctor.clinic,
            "cluster": cluster,
            "items": items,
            "languages": LANGUAGES,
            "selected_lang": lang,
        },
    )
