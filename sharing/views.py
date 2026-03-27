from __future__ import annotations

import json
import uuid

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import connections, transaction
from django.db.models import F
from django.http import HttpRequest, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from catalog.constants import LANGUAGE_CODES, LANGUAGES
from catalog.models import Video, VideoLanguage, VideoCluster, VideoClusterLanguage

from peds_edu.master_db import (
    fetch_master_doctor_row_by_id,
    master_row_to_template_context,
    build_patient_link_payload,
    sign_patient_payload,
    unsign_patient_payload,
    fetch_pe_campaign_support_for_doctor_email,
)

from .models import (
    DoctorShareSummary,
    ShareActivity,
    SharePlaybackEvent,
    build_anonymized_recipient_reference,
)
from .services import build_whatsapp_message_prefixes, get_catalog_json_cached

# ---------------------------------------------------------------------
# Patient page UI strings (minimal inline translations for label text)
# ---------------------------------------------------------------------
# We keep this local (instead of full Django i18n) to avoid touching global settings.
_PATIENT_UI_STRINGS = {
    "en": {
        "clinic_phone": "Clinic phone:",
        "whatsapp": "WhatsApp:",
        "educational_content": "Educational content provided by PE {clinic_name}",
    },
    "hi": {
        "clinic_phone": "क्लिनिक फ़ोन:",
        "whatsapp": "व्हाट्सएप:",
        "educational_content": "PE {clinic_name} द्वारा प्रदत्त शैक्षिक सामग्री",
    },
    "mr": {
        "clinic_phone": "क्लिनिक फोन:",
        "whatsapp": "व्हॉट्सअॅप:",
        "educational_content": "PE {clinic_name} कडून दिलेली शैक्षणिक सामग्री",
    },
    "te": {
        "clinic_phone": "క్లినిక్ ఫోన్:",
        "whatsapp": "వాట్సాప్:",
        "educational_content": "PE {clinic_name} అందించిన విద్యా సమాచారం",
    },
    "ml": {
        "clinic_phone": "ക്ലിനിക് ഫോൺ:",
        "whatsapp": "വാട്‌സ്ആപ്പ്:",
        "educational_content": "PE {clinic_name} നൽകുന്ന വിദ്യാഭ്യാസ ഉള്ളടക്കം",
    },
    "kn": {
        "clinic_phone": "ಕ್ಲಿನಿಕ್ ಫೋನ್:",
        "whatsapp": "ವಾಟ್ಸಾಪ್:",
        "educational_content": "PE {clinic_name} ನೀಡಿದ ಶಿಕ್ಷಣ ವಿಷಯ",
    },
    "ta": {
        "clinic_phone": "கிளினிக் தொலைபேசி:",
        "whatsapp": "வாட்ஸ்அப்:",
        "educational_content": "PE {clinic_name} வழங்கும் கல்வி உள்ளடக்கம்",
    },
    "bn": {
        "clinic_phone": "ক্লিনিক ফোন:",
        "whatsapp": "হোয়াটসঅ্যাপ:",
        "educational_content": "PE {clinic_name} প্রদানিত শিক্ষামূলক বিষয়বস্তু",
    },
}


def _patient_ui_strings(lang_code: str, *, clinic_name: str) -> dict[str, str]:
    base = _PATIENT_UI_STRINGS.get(lang_code) or _PATIENT_UI_STRINGS["en"]
    try:
        edu = (base.get("educational_content") or "").format(clinic_name=clinic_name or "")
    except Exception:
        edu = (base.get("educational_content") or "").replace("{clinic_name}", clinic_name or "")

    return {
        "clinic_phone": base.get("clinic_phone") or _PATIENT_UI_STRINGS["en"]["clinic_phone"],
        "whatsapp": base.get("whatsapp") or _PATIENT_UI_STRINGS["en"]["whatsapp"],
        "educational_content": edu,
    }


def _parse_json_body(request: HttpRequest) -> dict:
    if not request.body:
        return {}
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _normalize_language_code(raw_value: str) -> str:
    lang = str(raw_value or "en").strip().lower()
    return lang if lang in LANGUAGE_CODES else "en"


def _parse_uuid(raw_value: str) -> uuid.UUID | None:
    value = str(raw_value or "").strip()
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except (TypeError, ValueError, AttributeError):
        return None


def _get_or_create_doctor_share_summary(*, doctor_id: str, doctor_name: str, clinic_name: str) -> DoctorShareSummary:
    summary, _ = DoctorShareSummary.objects.get_or_create(
        doctor_id=doctor_id,
        defaults={
            "doctor_name_snapshot": doctor_name,
            "clinic_name_snapshot": clinic_name,
        },
    )

    update_fields: list[str] = []
    if doctor_name and summary.doctor_name_snapshot != doctor_name:
        summary.doctor_name_snapshot = doctor_name
        update_fields.append("doctor_name_snapshot")
    if clinic_name and summary.clinic_name_snapshot != clinic_name:
        summary.clinic_name_snapshot = clinic_name
        update_fields.append("clinic_name_snapshot")

    if update_fields:
        summary.save(update_fields=update_fields + ["updated_at"])

    return summary


def _resolve_shared_item_details(*, shared_item_type: str, shared_item_code: str, language_code: str) -> tuple[str, str]:
    if shared_item_type == ShareActivity.SharedItemType.VIDEO:
        video = Video.objects.filter(code=shared_item_code).first()
        if not video and shared_item_code.isdigit():
            video = Video.objects.filter(pk=int(shared_item_code)).first()
        if not video:
            return shared_item_code, shared_item_code

        vlang = (
            VideoLanguage.objects.filter(video=video, language_code=language_code).first()
            or VideoLanguage.objects.filter(video=video, language_code="en").first()
        )
        return video.code, (vlang.title if vlang and vlang.title else video.code)

    cluster = VideoCluster.objects.filter(code=shared_item_code).first()
    if not cluster and shared_item_code.isdigit():
        cluster = VideoCluster.objects.filter(pk=int(shared_item_code)).first()
    if not cluster:
        return shared_item_code, shared_item_code

    clang = (
        VideoClusterLanguage.objects.filter(video_cluster=cluster, language_code=language_code).first()
        or VideoClusterLanguage.objects.filter(video_cluster=cluster, language_code="en").first()
    )
    return cluster.code, (clang.name if clang and clang.name else cluster.display_name or cluster.code)


# def _tracking_audit_user_email() -> str:
#     return str(getattr(settings, "TRACKING_AUDIT_USER_EMAIL", "") or "").strip().lower()


# def _is_tracking_audit_user(user) -> bool:
#     return bool(getattr(user, "is_authenticated", False) and str(getattr(user, "email", "") or "").strip().lower() == _tracking_audit_user_email())

def _is_tracking_audit_user(user) -> bool:
    return bool(
        getattr(user, "is_authenticated", False)
        and getattr(user, "is_superuser", False)
    )



# -----------------------
# Required by sharing/urls.py
# -----------------------
def home(request: HttpRequest) -> HttpResponse:
    # Keep behaviour minimal + safe
    return redirect("accounts:login")


# -----------------------
# Campaign bundle helpers (read-only)
# -----------------------
def _fetch_all_campaign_bundle_codes() -> set[str]:
    try:
        with connections["default"].cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT vc.code
                FROM publisher_campaign pc
                JOIN catalog_videocluster vc ON vc.id = pc.video_cluster_id
                WHERE pc.video_cluster_id IS NOT NULL
                """
            )
            rows = cur.fetchall()
        return {str(r[0]).strip() for r in (rows or []) if r and r[0]}
    except Exception:
        return set()


def _fetch_allowed_bundle_codes_for_campaigns(campaign_ids: list[str]) -> set[str]:
    ids = [str(c).strip().replace("-", "") for c in (campaign_ids or []) if str(c).strip()]
    if not ids:
        return set()

    placeholders = ", ".join(["%s"] * len(ids))
    sql = f"""
        SELECT DISTINCT vc.code
        FROM publisher_campaign pc
        JOIN catalog_videocluster vc ON vc.id = pc.video_cluster_id
        WHERE REPLACE(pc.campaign_id, '-', '') IN ({placeholders})
          AND pc.video_cluster_id IS NOT NULL
    """

    try:
        with connections["default"].cursor() as cur:
            cur.execute(sql, ids)
            rows = cur.fetchall()
        return {str(r[0]).strip() for r in (rows or []) if r and r[0]}
    except Exception:
        return set()


@ensure_csrf_cookie
@login_required
def doctor_share(request: HttpRequest, doctor_id: str) -> HttpResponse:
    session_doctor_id = str(request.session.get("master_doctor_id") or "").strip()

    profile_doctor_id = ""
    try:
        profile_doctor_id = str(request.user.doctor_profile.doctor_id or "").strip()
    except Exception:
        profile_doctor_id = ""

    effective_doctor_id = session_doctor_id or profile_doctor_id

    if not effective_doctor_id or effective_doctor_id != doctor_id:
        return HttpResponseForbidden("Not allowed")

    if not session_doctor_id and profile_doctor_id == doctor_id:
        request.session["master_doctor_id"] = doctor_id
        request.session["master_login_email"] = getattr(request.user, "email", "") or ""
        request.session["master_login_role"] = "doctor"


    row = fetch_master_doctor_row_by_id(doctor_id)
    if not row:
        return HttpResponseForbidden("Doctor not found")

    doctor_ctx, clinic_ctx = master_row_to_template_context(row)
    doctor_name = ((doctor_ctx.get("user") or {}).get("full_name") or "").strip()

    login_email = (getattr(request.user, "email", "") or "").strip()
    doctor_email = ((doctor_ctx.get("user") or {}).get("email") or "").strip()

    extra_emails = [
        login_email,
        doctor_email,
        str(row.get("clinic_user1_email") or "").strip(),
        str(row.get("clinic_user2_email") or "").strip(),
        str(row.get("clinic_user3_email") or "").strip(),
    ]
    phones = [
        str(doctor_ctx.get("whatsapp_number") or "").strip(),
        str(clinic_ctx.get("clinic_phone") or "").strip(),
        str(clinic_ctx.get("clinic_whatsapp_number") or "").strip(),
    ]

    try:
        pe_campaign_support = fetch_pe_campaign_support_for_doctor_email(
            doctor_email or login_email,
            extra_emails=extra_emails,
            phones=phones,
        )
    except Exception:
        pe_campaign_support = []

    catalog_json = get_catalog_json_cached(force_refresh=True)
    if isinstance(catalog_json, str):
        try:
            catalog_json = json.loads(catalog_json)
        except Exception:
            catalog_json = {}
    catalog_json = dict(catalog_json or {})

    catalog_json["doctor_id"] = doctor_id
    catalog_json["message_prefixes"] = build_whatsapp_message_prefixes(doctor_name)

    patient_payload = build_patient_link_payload(doctor_ctx, clinic_ctx)
    catalog_json["doctor_payload"] = sign_patient_payload(patient_payload)

    # ------------------------------------------------------------------
    # Campaign-specific bundle filtering
    # ------------------------------------------------------------------
    all_campaign_bundle_codes = _fetch_all_campaign_bundle_codes()

    allowed_campaign_ids = [
        str(item.get("campaign_id"))
        for item in (pe_campaign_support or [])
        if isinstance(item, dict) and item.get("campaign_id")
    ]
    allowed_bundle_codes = _fetch_allowed_bundle_codes_for_campaigns(allowed_campaign_ids)

    if all_campaign_bundle_codes and isinstance(catalog_json.get("bundles"), list):
        filtered_bundles = []
        allowed_video_ids = set()

        for b in catalog_json.get("bundles", []):
            if not isinstance(b, dict):
                continue
            bcode = str(b.get("code") or "").strip()
            if not bcode:
                continue

            # keep default bundles OR allowed campaign bundles
            if bcode not in all_campaign_bundle_codes or bcode in allowed_bundle_codes:
                filtered_bundles.append(b)
                for vid in (b.get("video_codes") or []):
                    if vid:
                        allowed_video_ids.add(str(vid))

        catalog_json["bundles"] = filtered_bundles

        # ✅ CRITICAL FIX:
        # videos payload uses "id" (video code), not "code".:contentReference[oaicite:4]{index=4}
        if isinstance(catalog_json.get("videos"), list):
            catalog_json["videos"] = [
                v for v in catalog_json.get("videos", [])
                if isinstance(v, dict) and str(v.get("id") or "").strip() in allowed_video_ids
            ]

    return render(
        request,
        "sharing/share.html",
        {
            "doctor": doctor_ctx,
            "clinic": clinic_ctx,
            "catalog_json": catalog_json,
            "languages": LANGUAGES,
            "show_modify_clinic_details": False,
            "pe_campaign_support": pe_campaign_support,
        },
    )


@ensure_csrf_cookie
def patient_video(request: HttpRequest, doctor_id: str, video_code: str) -> HttpResponse:
    token = (request.GET.get("d") or "").strip()
    payload = unsign_patient_payload(token) or {}

    doctor = payload.get("doctor") if isinstance(payload.get("doctor"), dict) else {}
    clinic = payload.get("clinic") if isinstance(payload.get("clinic"), dict) else {}

    if not isinstance(doctor.get("user"), dict):
        doctor["user"] = {"full_name": ""}

    doctor["doctor_id"] = doctor_id
    doctor.setdefault("photo", None)

    clinic.setdefault("display_name", "")
    clinic.setdefault("clinic_phone", "")
    clinic.setdefault("clinic_whatsapp_number", "")
    clinic.setdefault("address_text", "")
    clinic.setdefault("state", "")
    clinic.setdefault("postal_code", "")

    lang = request.GET.get("lang", "en")
    if lang not in LANGUAGE_CODES:
        lang = "en"
    ui = _patient_ui_strings(lang, clinic_name=str(clinic.get("display_name") or ""))

    video = get_object_or_404(Video, code=video_code)
    vlang = (
        VideoLanguage.objects.filter(video=video, language_code=lang).first()
        or VideoLanguage.objects.filter(video=video, language_code="en").first()
    )

    share_public_id = _parse_uuid(request.GET.get("s"))

    return render(
        request,
        "sharing/patient_video.html",
        {
            "doctor": doctor,
            "clinic": clinic,
            "video": video,
            "vlang": vlang,
            "selected_lang": lang,
            "share_public_id": str(share_public_id) if share_public_id else "",
            "ui": ui,
            "languages": LANGUAGES,
            "show_auth_links": False,
        },
    )


@ensure_csrf_cookie
def patient_cluster(request: HttpRequest, doctor_id: str, cluster_code: str) -> HttpResponse:
    token = (request.GET.get("d") or "").strip()
    payload = unsign_patient_payload(token) or {}

    doctor = payload.get("doctor") if isinstance(payload.get("doctor"), dict) else {}
    clinic = payload.get("clinic") if isinstance(payload.get("clinic"), dict) else {}

    if not isinstance(doctor.get("user"), dict):
        doctor["user"] = {"full_name": ""}

    doctor["doctor_id"] = doctor_id
    doctor.setdefault("photo", None)

    clinic.setdefault("display_name", "")
    clinic.setdefault("clinic_phone", "")
    clinic.setdefault("clinic_whatsapp_number", "")
    clinic.setdefault("address_text", "")
    clinic.setdefault("state", "")
    clinic.setdefault("postal_code", "")

    lang = request.GET.get("lang", "en")
    if lang not in LANGUAGE_CODES:
        lang = "en"
    ui = _patient_ui_strings(lang, clinic_name=str(clinic.get("display_name") or ""))

    cluster = VideoCluster.objects.filter(code=cluster_code).first()
    if cluster is None and cluster_code.isdigit():
        cluster = get_object_or_404(VideoCluster, pk=int(cluster_code))
    elif cluster is None:
        cluster = get_object_or_404(VideoCluster, pk=-1)

    cl_lang = (
        VideoClusterLanguage.objects.filter(video_cluster=cluster, language_code=lang).first()
        or VideoClusterLanguage.objects.filter(video_cluster=cluster, language_code="en").first()
    )
    cluster_title = cl_lang.name if cl_lang else cluster.code

    try:
        videos = cluster.videos.all().order_by("sort_order", "id")
    except Exception:
        videos = cluster.videos.all().order_by("id")

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

    share_public_id = _parse_uuid(request.GET.get("s"))

    return render(
        request,
        "sharing/patient_cluster.html",
        {
            "doctor": doctor,
            "clinic": clinic,
            "cluster": cluster,
            "cluster_title": cluster_title,
            "items": items,
            "languages": LANGUAGES,
            "selected_lang": lang,
            "share_public_id": str(share_public_id) if share_public_id else "",
            "ui": ui,
            "show_auth_links": False,
        },
    )


@login_required
@require_POST
def create_share_activity(request: HttpRequest) -> HttpResponse:
    doctor_id = str(request.session.get("master_doctor_id") or "").strip()
    if not doctor_id:
        return HttpResponseForbidden("Not allowed")

    payload = _parse_json_body(request)
    share_public_id = _parse_uuid(payload.get("share_public_id"))
    shared_item_type = str(payload.get("shared_item_type") or "").strip().lower()
    shared_item_code = str(payload.get("shared_item_code") or "").strip()
    recipient_identifier = str(payload.get("recipient_identifier") or "").strip()
    language_code = _normalize_language_code(payload.get("language_code"))

    if not share_public_id:
        return JsonResponse({"ok": False, "error": "Invalid share_public_id."}, status=400)
    if shared_item_type not in ShareActivity.SharedItemType.values:
        return JsonResponse({"ok": False, "error": "Invalid shared_item_type."}, status=400)
    if not shared_item_code:
        return JsonResponse({"ok": False, "error": "shared_item_code is required."}, status=400)
    if not recipient_identifier:
        return JsonResponse({"ok": False, "error": "recipient_identifier is required."}, status=400)

    row = fetch_master_doctor_row_by_id(doctor_id)
    if not row:
        return JsonResponse({"ok": False, "error": "Doctor not found."}, status=404)

    doctor_ctx, clinic_ctx = master_row_to_template_context(row)
    doctor_name = str(((doctor_ctx.get("user") or {}).get("full_name")) or "").strip()
    clinic_name = str(clinic_ctx.get("display_name") or "").strip()
    shared_item_code, shared_item_name = _resolve_shared_item_details(
        shared_item_type=shared_item_type,
        shared_item_code=shared_item_code,
        language_code=language_code,
    )
    recipient_reference = build_anonymized_recipient_reference(
        doctor_id=doctor_id,
        recipient_identifier=recipient_identifier,
    )
    if not recipient_reference:
        return JsonResponse({"ok": False, "error": "recipient_identifier is invalid."}, status=400)

    summary = _get_or_create_doctor_share_summary(
        doctor_id=doctor_id,
        doctor_name=doctor_name,
        clinic_name=clinic_name,
    )

    with transaction.atomic():
        share, created = ShareActivity.objects.get_or_create(
            public_id=share_public_id,
            defaults={
                "doctor_summary": summary,
                "doctor_id": doctor_id,
                "doctor_name_snapshot": doctor_name,
                "clinic_name_snapshot": clinic_name,
                "share_channel": "whatsapp",
                "shared_by_role": str(request.session.get("master_login_role") or "").strip(),
                "shared_item_type": shared_item_type,
                "shared_item_code": shared_item_code,
                "shared_item_name": shared_item_name,
                "language_code": language_code,
                "recipient_reference": recipient_reference,
                "recipient_reference_version": 1,
            },
        )

        if created:
            DoctorShareSummary.objects.filter(pk=summary.pk).update(
                total_shares=F("total_shares") + 1,
                last_shared_at=share.shared_at,
            )

    return JsonResponse(
        {
            "ok": True,
            "created": created,
            "share_public_id": str(share.public_id),
            "shared_item_name": share.shared_item_name,
        }
    )


@require_POST
def log_playback_event(request: HttpRequest) -> HttpResponse:
    payload = _parse_json_body(request)
    share_public_id = _parse_uuid(payload.get("share_public_id"))
    page_item_type = str(payload.get("page_item_type") or "").strip().lower()
    event_type = str(payload.get("event_type") or "").strip().lower()
    video_code = str(payload.get("video_code") or "").strip()
    video_name = str(payload.get("video_name") or "").strip()
    milestone_raw = payload.get("milestone_percent")

    if page_item_type not in ShareActivity.SharedItemType.values:
        return JsonResponse({"ok": False, "error": "Invalid page_item_type."}, status=400)
    if event_type not in SharePlaybackEvent.EventType.values:
        return JsonResponse({"ok": False, "error": "Invalid event_type."}, status=400)
    if not video_code:
        return JsonResponse({"ok": False, "error": "video_code is required."}, status=400)

    milestone_percent = None
    if milestone_raw not in (None, ""):
        try:
            milestone_percent = int(milestone_raw)
        except (TypeError, ValueError):
            return JsonResponse({"ok": False, "error": "milestone_percent must be an integer."}, status=400)
        if not 0 <= milestone_percent <= 100:
            return JsonResponse({"ok": False, "error": "milestone_percent must be between 0 and 100."}, status=400)

    share = None
    doctor_summary = None
    doctor_id = ""
    if share_public_id:
        share = ShareActivity.objects.select_related("doctor_summary").filter(public_id=share_public_id).first()

    if share:
        doctor_summary = share.doctor_summary
        doctor_id = share.doctor_id
    else:
        doctor_id = str(payload.get("doctor_id") or "").strip()
        doctor_name = str(payload.get("doctor_name") or "").strip()
        clinic_name = str(payload.get("clinic_name") or "").strip()
        if not doctor_id:
            return JsonResponse({"ok": False, "error": "doctor_id is required when share is unknown."}, status=400)
        doctor_summary = _get_or_create_doctor_share_summary(
            doctor_id=doctor_id,
            doctor_name=doctor_name,
            clinic_name=clinic_name,
        )

    SharePlaybackEvent.objects.create(
        share=share,
        share_public_id=share_public_id,
        doctor_summary=doctor_summary,
        doctor_id=doctor_id,
        page_item_type=page_item_type,
        event_type=event_type,
        video_code=video_code,
        video_name=video_name,
        milestone_percent=milestone_percent,
    )

    return JsonResponse({"ok": True})


def tracking_login(request: HttpRequest) -> HttpResponse:
    if _is_tracking_audit_user(request.user):
        return redirect("sharing:tracking_dashboard")

    if request.method == "POST":
        email = str(request.POST.get("email") or "").strip().lower()
        password = str(request.POST.get("password") or "")

        user = authenticate(request, email=email, password=password)
        if user is not None and user.is_superuser:
            login(request, user)
            return redirect("sharing:tracking_dashboard")

        messages.error(request, "Only a superuser can access this page.")

    return render(
        request,
        "sharing/tracking_login.html",
        {
            "show_auth_links": False,
        },
    )
   
@login_required
def tracking_dashboard(request: HttpRequest) -> HttpResponse:
    
    if not _is_tracking_audit_user(request.user):
        return HttpResponseForbidden("Not allowed")

    summary_rows = DoctorShareSummary.objects.order_by("-total_shares", "doctor_id")
    recent_shares = ShareActivity.objects.select_related("doctor_summary").order_by("-shared_at")[:100]
    recent_playback = SharePlaybackEvent.objects.select_related("doctor_summary", "share").order_by("-occurred_at")[:100]

    stats = {
        "doctor_count": summary_rows.count(),
        "share_count": ShareActivity.objects.count(),
        "playback_event_count": SharePlaybackEvent.objects.count(),
        "unique_items_shared": ShareActivity.objects.values("shared_item_type", "shared_item_code").distinct().count(),
    }

    return render(
        request,
        "sharing/tracking_dashboard.html",
        {
            "stats": stats,
            "summary_rows": summary_rows,
            "recent_shares": recent_shares,
            "recent_playback": recent_playback,
            "show_auth_links": False,
        },
    )


@login_required
def tracking_logout(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("sharing:tracking_login")
