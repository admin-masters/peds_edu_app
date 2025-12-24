from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import DoctorProfile
from catalog.constants import LANGUAGE_CODES, LANGUAGES
from catalog.models import Video, VideoLanguage

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

    # IMPORTANT: force refresh so stale cache cannot hide data
    catalog_json = get_catalog_json_cached(force_refresh=True)
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
