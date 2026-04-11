from __future__ import annotations

from functools import wraps
from typing import Optional

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from accounts import master_db
from accounts.models import Clinic, DoctorProfile, User
from catalog.models import (
    TherapyArea,
    Trigger,
    TriggerCluster,
    Video,
    VideoCluster,
    VideoTriggerMap,
    VideoClusterVideo,
)
from publisher.forms import (
    BundleTriggerMapForm,
    DoctorRecordForm,
    FieldRepRecordForm,
    MasterCampaignRecordForm,
    PERecordsLoginForm,
    TherapyAreaForm,
    TriggerClusterForm,
    TriggerForm,
    VideoClusterForm,
    VideoForm,
    VideoTriggerMapForm,  # legacy, retained
    make_cluster_language_formset,
    make_cluster_video_formset,
    make_video_language_formset,
)
from publisher.models import Campaign


PE_RECORDS_SESSION_USER_ID = "pe_records_user_id"
PE_RECORDS_SESSION_EMAIL = "pe_records_user_email"


@staff_member_required
def dashboard(request):
    return render(request, "publisher/dashboard.html")


def _is_system_superuser(user) -> bool:
    return bool(
        user is not None
        and getattr(user, "is_authenticated", False)
        and getattr(user, "is_active", False)
        and getattr(user, "is_superuser", False)
    )


def superuser_required(view_func):
    @wraps(view_func)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not _is_system_superuser(request.user):
            return HttpResponseForbidden("Not allowed")
        return view_func(request, *args, **kwargs)

    return _wrapped


def _clear_pe_records_session(request) -> None:
    for key in (PE_RECORDS_SESSION_USER_ID, PE_RECORDS_SESSION_EMAIL):
        try:
            request.session.pop(key, None)
        except Exception:
            continue


def _get_pe_records_user(request):
    raw_user_id = request.session.get(PE_RECORDS_SESSION_USER_ID)
    try:
        user_id = int(raw_user_id)
    except (TypeError, ValueError):
        return None

    return (
        User.objects.filter(pk=user_id, is_active=True, is_superuser=True)
        .only("id", "email", "full_name", "is_active", "is_staff")
        .first()
    )


def pe_records_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        user = _get_pe_records_user(request)
        if user is None:
            _clear_pe_records_session(request)
            return redirect("publisher:pe_records_login")
        request.pe_records_user = user
        return view_func(request, *args, **kwargs)

    return _wrapped


def _normalize_campaign_identifier(value: str) -> str:
    return master_db.normalize_campaign_id(str(value or ""))


def _get_pe_master_campaign_records():
    return master_db.list_master_campaign_records(pe_only=True)


def _get_pe_campaign_id_set() -> set[str]:
    return {
        _normalize_campaign_identifier(record.campaign_id)
        for record in _get_pe_master_campaign_records()
        if _normalize_campaign_identifier(record.campaign_id)
    }


def _build_local_campaign_map(target_campaign_ids: Optional[set[str]] = None) -> dict[str, Campaign]:
    campaigns = Campaign.objects.select_related("video_cluster").order_by("-updated_at", "campaign_id")
    mapping: dict[str, Campaign] = {}
    for campaign in campaigns:
        normalized_id = _normalize_campaign_identifier(campaign.campaign_id)
        if not normalized_id:
            continue
        if target_campaign_ids and normalized_id not in target_campaign_ids:
            continue
        mapping.setdefault(normalized_id, campaign)
    return mapping


def _find_local_campaign_record(campaign_id: str):
    target = _normalize_campaign_identifier(campaign_id)
    if not target:
        return None
    return _build_local_campaign_map({target}).get(target)


def _delete_local_campaign_record(campaign_id: str) -> bool:
    campaign = _find_local_campaign_record(campaign_id)
    if campaign is None:
        return False

    cluster = campaign.video_cluster
    campaign.delete()
    if cluster is not None:
        cluster.delete()
    return True


def _campaign_row_matches_search(row: dict, term: str) -> bool:
    lowered = (term or "").strip().lower()
    if not lowered:
        return True

    master_record = row.get("master_record")
    local_campaign = row.get("local_campaign")
    haystacks = [
        row.get("campaign_id"),
        row.get("display_campaign_id"),
        getattr(master_record, "name", ""),
        getattr(master_record, "banner_target_url", ""),
        getattr(master_record, "start_date", ""),
        getattr(local_campaign, "new_video_cluster_name", "") if local_campaign else "",
        getattr(local_campaign, "publisher_username", "") if local_campaign else "",
        getattr(local_campaign, "start_date", "") if local_campaign else "",
        getattr(local_campaign, "end_date", "") if local_campaign else "",
    ]
    return any(lowered in str(value or "").lower() for value in haystacks)


def _build_pe_records_context(*, campaign_q: str = "", field_rep_q: str = "", doctor_q: str = "") -> dict:
    master_campaigns = _get_pe_master_campaign_records()
    master_campaign_ids = {
        _normalize_campaign_identifier(record.campaign_id)
        for record in master_campaigns
        if _normalize_campaign_identifier(record.campaign_id)
    }
    master_campaign_id_list = sorted(master_campaign_ids)
    local_campaign_map = _build_local_campaign_map(master_campaign_ids)

    campaign_rows = []
    for record in master_campaigns:
        normalized_id = _normalize_campaign_identifier(record.campaign_id)
        local_campaign = local_campaign_map.get(normalized_id)
        campaign_rows.append(
            {
                "campaign_id": record.campaign_id,
                "normalized_campaign_id": normalized_id,
                "display_campaign_id": local_campaign.campaign_id if local_campaign else record.campaign_id,
                "master_record": record,
                "local_campaign": local_campaign,
                "has_local_campaign": local_campaign is not None,
            }
        )

    if campaign_q:
        campaign_rows = [row for row in campaign_rows if _campaign_row_matches_search(row, campaign_q)]

    local_campaign_ids = set(local_campaign_map.keys())

    field_rep_rows = []
    for record in master_db.list_pe_field_rep_records(field_rep_q, campaign_ids=master_campaign_id_list):
        pe_campaign_ids = tuple(record.linked_campaign_ids)
        field_rep_rows.append(
            {
                "record": record,
                "pe_campaign_ids": pe_campaign_ids,
                "local_campaign_count": sum(
                    1 for campaign_id in pe_campaign_ids if _normalize_campaign_identifier(campaign_id) in local_campaign_ids
                ),
            }
        )

    doctors = []
    doctor_records = master_db.list_pe_doctor_records(doctor_q, campaign_ids=master_campaign_id_list)
    local_profiles = {
        profile.doctor_id: profile
        for profile in DoctorProfile.objects.select_related("user", "clinic").filter(
            doctor_id__in=[record.doctor_id for record in doctor_records]
        )
    }
    for record in doctor_records:
        pe_campaign_ids = tuple(record.linked_campaign_ids)

        local_profile = local_profiles.get(record.doctor_id)
        doctors.append(
            {
                "record": record,
                "pe_campaign_ids": pe_campaign_ids,
                "has_local_profile": local_profile is not None,
                "local_profile": local_profile,
                "local_campaign_count": sum(
                    1 for campaign_id in pe_campaign_ids if _normalize_campaign_identifier(campaign_id) in local_campaign_ids
                ),
            }
        )

    return {
        "campaign_rows": campaign_rows,
        "field_rep_rows": field_rep_rows,
        "doctor_rows": doctors,
        "campaign_q": campaign_q,
        "field_rep_q": field_rep_q,
        "doctor_q": doctor_q,
        "stats": {
            "master_campaigns": len(master_campaigns),
            "local_campaigns": len(local_campaign_map),
            "field_reps": len(field_rep_rows),
            "doctors": len(doctors),
        },
    }


def _normalize_local_mobile(value: str) -> str:
    digits = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not digits:
        return ""
    return digits[-10:]


def _validate_local_doctor_sync(profile, *, email: str, whatsapp_number: str) -> None:
    if profile is None:
        return

    if User.objects.exclude(pk=profile.user_id).filter(email=email).exists():
        raise ValueError("Another local portal user already uses this email address.")

    if whatsapp_number and DoctorProfile.objects.exclude(pk=profile.pk).filter(whatsapp_number=whatsapp_number).exists():
        raise ValueError("Another local portal doctor already uses this WhatsApp number.")


def _sync_local_doctor_record(profile, payload: dict) -> bool:
    if profile is None:
        return False

    full_name = (f"{payload.get('first_name') or ''} {payload.get('last_name') or ''}").strip() or profile.doctor_id
    email = str(payload.get("email") or "").strip().lower()
    whatsapp_number = _normalize_local_mobile(
        payload.get("whatsapp_no")
        or payload.get("receptionist_whatsapp_number")
        or profile.whatsapp_number
    )
    clinic_whatsapp = _normalize_local_mobile(
        payload.get("receptionist_whatsapp_number")
        or payload.get("whatsapp_no")
        or profile.clinic.clinic_whatsapp_number
    )

    user = profile.user
    if user.email != email or (user.full_name or "").strip() != full_name:
        user.email = email
        user.full_name = full_name
        user.save(update_fields=["email", "full_name"])

    clinic = profile.clinic
    clinic.display_name = str(payload.get("clinic_name") or "").strip()
    clinic.clinic_phone = str(payload.get("clinic_phone") or "").strip()
    clinic.clinic_whatsapp_number = clinic_whatsapp or None
    clinic.address_text = str(payload.get("clinic_address") or "").strip()
    clinic.postal_code = str(payload.get("postal_code") or "").strip()
    clinic.state = str(payload.get("state") or "").strip()
    clinic.save(
        update_fields=[
            "display_name",
            "clinic_phone",
            "clinic_whatsapp_number",
            "address_text",
            "postal_code",
            "state",
        ]
    )

    profile.whatsapp_number = whatsapp_number or profile.whatsapp_number
    profile.imc_number = str(payload.get("imc_registration_number") or "").strip()
    profile.postal_code = str(payload.get("postal_code") or "").strip() or None
    profile.save(update_fields=["whatsapp_number", "imc_number", "postal_code"])
    return True


def _delete_local_doctor_record(doctor_id: str) -> bool:
    profile = (
        DoctorProfile.objects.select_related("user", "clinic")
        .filter(doctor_id=doctor_id)
        .first()
    )
    if profile is None:
        return False

    user_id = profile.user_id
    clinic_id = profile.clinic_id
    can_delete_user = not bool(profile.user.is_staff or profile.user.is_superuser)

    profile.delete()

    if clinic_id and not DoctorProfile.objects.filter(clinic_id=clinic_id).exists():
        Clinic.objects.filter(pk=clinic_id).delete()

    if can_delete_user and user_id and not DoctorProfile.objects.filter(user_id=user_id).exists():
        User.objects.filter(pk=user_id).delete()

    return True


def _render_field_rep_record_edit(request, field_rep_id: int, *, redirect_name: str, hub_url: str, record=None):
    record = record or master_db.get_field_rep_record(field_rep_id)
    if record is None:
        raise Http404("Field rep not found.")

    if request.method == "POST":
        form = FieldRepRecordForm(request.POST)
        if form.is_valid():
            try:
                master_db.update_field_rep_record(field_rep_id, **form.cleaned_data)
            except Exception:
                form.add_error(None, "Unable to update the field rep record right now.")
            else:
                messages.success(request, "Field rep updated successfully.")
                return redirect(redirect_name)
    else:
        form = FieldRepRecordForm(
            initial={
                "full_name": record.full_name,
                "phone_number": record.phone_number,
                "brand_supplied_field_rep_id": record.brand_supplied_field_rep_id,
                "state": record.state,
                "is_active": record.is_active,
            }
        )

    return render(
        request,
        "publisher/field_rep_record_form.html",
        {
            "form": form,
            "record": record,
            "hub_url": hub_url,
            "show_auth_links": False,
        },
    )


def _delete_field_rep_record_response(request, field_rep_id: int, *, redirect_name: str):
    if request.method != "POST":
        return HttpResponseForbidden("Not allowed")

    try:
        master_db.delete_field_rep_record(field_rep_id)
    except Exception:
        messages.error(request, "Unable to delete the field rep record right now.")
    else:
        messages.success(request, "Field rep deleted successfully.")

    return redirect(redirect_name)


def _render_doctor_record_edit(request, doctor_id: str, *, redirect_name: str, hub_url: str, record=None):
    record = record or master_db.get_doctor_record(doctor_id)
    if record is None:
        raise Http404("Doctor not found.")

    local_profile = (
        DoctorProfile.objects.select_related("user", "clinic")
        .filter(doctor_id=doctor_id)
        .first()
    )

    if request.method == "POST":
        form = DoctorRecordForm(request.POST)
        if form.is_valid():
            email = str(form.cleaned_data.get("email") or "").strip().lower()
            whatsapp_number = _normalize_local_mobile(
                form.cleaned_data.get("whatsapp_no")
                or form.cleaned_data.get("receptionist_whatsapp_number")
                or (local_profile.whatsapp_number if local_profile else "")
            )

            try:
                _validate_local_doctor_sync(local_profile, email=email, whatsapp_number=whatsapp_number)
            except ValueError as exc:
                form.add_error(None, str(exc))
            else:
                try:
                    master_db.update_doctor_record(doctor_id, **form.cleaned_data)
                except Exception:
                    form.add_error(None, "Unable to update the doctor record right now.")
                else:
                    local_sync_warning = ""
                    if local_profile is not None:
                        try:
                            _sync_local_doctor_record(local_profile, form.cleaned_data)
                        except Exception:
                            local_sync_warning = (
                                "The master doctor record was updated, but the local portal profile could not be synced."
                            )

                    if local_sync_warning:
                        messages.warning(request, local_sync_warning)
                    else:
                        messages.success(request, "Doctor updated successfully.")
                    return redirect(redirect_name)
    else:
        form = DoctorRecordForm(
            initial={
                "first_name": record.first_name,
                "last_name": record.last_name,
                "email": record.email,
                "whatsapp_no": record.whatsapp_no,
                "clinic_name": record.clinic_name,
                "clinic_phone": record.clinic_phone,
                "clinic_appointment_number": record.clinic_appointment_number,
                "clinic_address": record.clinic_address,
                "postal_code": record.postal_code,
                "state": record.state,
                "district": record.district,
                "receptionist_whatsapp_number": record.receptionist_whatsapp_number,
                "imc_registration_number": record.imc_registration_number,
                "field_rep_id": record.field_rep_id,
                "recruited_via": record.recruited_via,
                "clinic_user1_name": record.clinic_user1_name,
                "clinic_user1_email": record.clinic_user1_email,
                "clinic_user2_name": record.clinic_user2_name,
                "clinic_user2_email": record.clinic_user2_email,
            }
        )

    return render(
        request,
        "publisher/doctor_record_form.html",
        {
            "form": form,
            "record": record,
            "has_local_profile": local_profile is not None,
            "hub_url": hub_url,
            "show_auth_links": False,
        },
    )


def _delete_doctor_record_response(request, doctor_id: str, *, redirect_name: str):
    if request.method != "POST":
        return HttpResponseForbidden("Not allowed")

    local_deleted = False
    try:
        local_deleted = _delete_local_doctor_record(doctor_id)
        master_db.delete_doctor_record(doctor_id)
    except Exception:
        if local_deleted:
            messages.warning(
                request,
                "The local portal doctor profile was removed, but the master doctor record still needs cleanup.",
            )
        else:
            messages.error(request, "Unable to delete the doctor record right now.")
    else:
        messages.success(request, "Doctor deleted successfully.")

    return redirect(redirect_name)


def pe_records_login(request):
    if _get_pe_records_user(request) is not None:
        return redirect("publisher:pe_records_dashboard")

    form = PERecordsLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = authenticate(
            request,
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
        )
        if user is not None and _is_system_superuser(user):
            request.session.cycle_key()
            request.session[PE_RECORDS_SESSION_USER_ID] = user.pk
            request.session[PE_RECORDS_SESSION_EMAIL] = user.email or ""
            return redirect("publisher:pe_records_dashboard")
        form.add_error(None, "Only a system superuser can access the PE records dashboard.")

    return render(
        request,
        "publisher/pe_records_login.html",
        {
            "form": form,
            "show_auth_links": False,
        },
    )


@pe_records_required
def pe_records_logout(request):
    _clear_pe_records_session(request)
    messages.info(request, "Logged out of the PE records dashboard.")
    return redirect("publisher:pe_records_login")


@pe_records_required
def pe_records_dashboard(request):
    campaign_q = (request.GET.get("campaign_q") or "").strip()
    field_rep_q = (request.GET.get("field_rep_q") or "").strip()
    doctor_q = (request.GET.get("doctor_q") or "").strip()

    context = _build_pe_records_context(
        campaign_q=campaign_q,
        field_rep_q=field_rep_q,
        doctor_q=doctor_q,
    )
    context.update(
        {
            "access_user": getattr(request, "pe_records_user", None),
            "show_auth_links": False,
        }
    )
    return render(request, "publisher/pe_records_dashboard.html", context)


@pe_records_required
def pe_campaign_record_edit(request, campaign_id: str):
    record = master_db.get_master_campaign_record(campaign_id, pe_only=None)
    if record is None:
        raise Http404("Campaign not found.")

    local_campaign = _find_local_campaign_record(campaign_id)

    if request.method == "POST":
        form = MasterCampaignRecordForm(request.POST)
        if form.is_valid():
            try:
                master_db.update_master_campaign_record(campaign_id, **form.cleaned_data)
            except Exception:
                form.add_error(None, "Unable to update the master campaign record right now.")
            else:
                messages.success(request, "Master PE campaign updated successfully.")
                return redirect("publisher:pe_records_dashboard")
    else:
        form = MasterCampaignRecordForm(
            initial={
                "name": record.name,
                "num_doctors_supported": record.num_doctors_supported,
                "add_to_campaign_message": record.add_to_campaign_message,
                "register_message": record.register_message,
                "banner_small_url": record.banner_small_url,
                "banner_large_url": record.banner_large_url,
                "banner_target_url": record.banner_target_url,
                "brand_id": record.brand_id,
                "system_pe": record.system_pe,
                "start_date": record.start_date,
            }
        )

    return render(
        request,
        "publisher/pe_master_campaign_form.html",
        {
            "form": form,
            "record": record,
            "local_campaign": local_campaign,
            "hub_url": reverse("publisher:pe_records_dashboard"),
            "show_auth_links": False,
        },
    )


@pe_records_required
def pe_campaign_record_delete(request, campaign_id: str):
    if request.method != "POST":
        return HttpResponseForbidden("Not allowed")

    master_deleted = False
    local_deleted = False
    try:
        master_db.delete_master_campaign_record(campaign_id)
        master_deleted = True
        local_deleted = _delete_local_campaign_record(campaign_id)
    except Exception:
        if master_deleted:
            messages.warning(
                request,
                "The master campaign was removed, but the local PE portal setup still needs cleanup.",
            )
        else:
            messages.error(request, "Unable to delete the master campaign record right now.")
    else:
        if local_deleted:
            messages.success(request, "Master PE campaign and local portal setup deleted successfully.")
        else:
            messages.success(request, "Master PE campaign deleted successfully.")

    return redirect("publisher:pe_records_dashboard")


@pe_records_required
def pe_field_rep_record_edit(request, field_rep_id: int):
    pe_campaign_ids = _get_pe_campaign_id_set()
    record = master_db.get_pe_field_rep_record(field_rep_id, campaign_ids=sorted(pe_campaign_ids))
    if record is None:
        raise Http404("Field rep not found.")
    return _render_field_rep_record_edit(
        request,
        field_rep_id,
        redirect_name="publisher:pe_records_dashboard",
        hub_url=reverse("publisher:pe_records_dashboard"),
        record=record,
    )


@pe_records_required
def pe_field_rep_record_delete(request, field_rep_id: int):
    pe_campaign_ids = _get_pe_campaign_id_set()
    record = master_db.get_pe_field_rep_record(field_rep_id, campaign_ids=sorted(pe_campaign_ids))
    if record is None:
        raise Http404("Field rep not found.")
    return _delete_field_rep_record_response(
        request,
        field_rep_id,
        redirect_name="publisher:pe_records_dashboard",
    )


@pe_records_required
def pe_doctor_record_edit(request, doctor_id: str):
    pe_campaign_ids = _get_pe_campaign_id_set()
    record = master_db.get_pe_doctor_record(doctor_id, campaign_ids=sorted(pe_campaign_ids))
    if record is None:
        raise Http404("Doctor not found.")
    return _render_doctor_record_edit(
        request,
        doctor_id,
        redirect_name="publisher:pe_records_dashboard",
        hub_url=reverse("publisher:pe_records_dashboard"),
        record=record,
    )


@pe_records_required
def pe_doctor_record_delete(request, doctor_id: str):
    pe_campaign_ids = _get_pe_campaign_id_set()
    record = master_db.get_pe_doctor_record(doctor_id, campaign_ids=sorted(pe_campaign_ids))
    if record is None:
        raise Http404("Doctor not found.")
    return _delete_doctor_record_response(
        request,
        doctor_id,
        redirect_name="publisher:pe_records_dashboard",
    )


@superuser_required
def system_records(request):
    campaign_q = (request.GET.get("campaign_q") or "").strip()
    field_rep_q = (request.GET.get("field_rep_q") or "").strip()
    doctor_q = (request.GET.get("doctor_q") or "").strip()

    campaigns = Campaign.objects.select_related("video_cluster").order_by("-updated_at", "campaign_id")
    if campaign_q:
        campaigns = campaigns.filter(
            Q(campaign_id__icontains=campaign_q)
            | Q(new_video_cluster_name__icontains=campaign_q)
            | Q(publisher_username__icontains=campaign_q)
        )
    campaign_rows = list(campaigns)

    field_reps = master_db.list_field_rep_records(field_rep_q)
    doctors = master_db.list_doctor_records(doctor_q)

    local_doctor_ids = set(
        DoctorProfile.objects.filter(doctor_id__in=[record.doctor_id for record in doctors]).values_list("doctor_id", flat=True)
    )
    doctor_rows = [
        {
            "record": record,
            "has_local_profile": record.doctor_id in local_doctor_ids,
        }
        for record in doctors
    ]

    return render(
        request,
        "publisher/system_records.html",
        {
            "campaign_rows": campaign_rows,
            "field_rep_rows": field_reps,
            "doctor_rows": doctor_rows,
            "campaign_q": campaign_q,
            "field_rep_q": field_rep_q,
            "doctor_q": doctor_q,
            "stats": {
                "campaigns": len(campaign_rows),
                "field_reps": len(field_reps),
                "doctors": len(doctors),
            },
            "show_auth_links": False,
        },
    )


@superuser_required
@transaction.atomic
def campaign_record_delete(request, campaign_id):
    if request.method != "POST":
        return HttpResponseForbidden("Not allowed")

    try:
        deleted = _delete_local_campaign_record(campaign_id)
    except Exception:
        messages.error(request, "Unable to delete the campaign record right now.")
    else:
        if deleted:
            messages.success(request, "Campaign deleted from the Patient Education portal.")
        else:
            messages.info(request, "No local Patient Education campaign record matched that campaign ID.")

    return redirect("publisher:system_records")


@superuser_required
def field_rep_record_edit(request, field_rep_id: int):
    return _render_field_rep_record_edit(
        request,
        field_rep_id,
        redirect_name="publisher:system_records",
        hub_url=reverse("publisher:system_records"),
    )


@superuser_required
def field_rep_record_delete(request, field_rep_id: int):
    return _delete_field_rep_record_response(
        request,
        field_rep_id,
        redirect_name="publisher:system_records",
    )


@superuser_required
def doctor_record_edit(request, doctor_id: str):
    return _render_doctor_record_edit(
        request,
        doctor_id,
        redirect_name="publisher:system_records",
        hub_url=reverse("publisher:system_records"),
    )


@superuser_required
def doctor_record_delete(request, doctor_id: str):
    return _delete_doctor_record_response(
        request,
        doctor_id,
        redirect_name="publisher:system_records",
    )


# ---------------------------
# Therapy Areas
# ---------------------------
@staff_member_required
def therapy_list(request):
    q = (request.GET.get("q") or "").strip()
    rows = TherapyArea.objects.all().order_by("display_name", "code")
    if q:
        rows = rows.filter(Q(code__icontains=q) | Q(display_name__icontains=q))
    return render(request, "publisher/therapy_list.html", {"rows": rows, "q": q})


@staff_member_required
def therapy_create(request):
    if request.method == "POST":
        form = TherapyAreaForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Therapy area created.")
            return redirect("publisher:therapy_list")
    else:
        form = TherapyAreaForm()
    return render(request, "publisher/therapy_form.html", {"form": form, "object": None})


@staff_member_required
def therapy_edit(request, pk):
    obj = get_object_or_404(TherapyArea, pk=pk)
    if request.method == "POST":
        form = TherapyAreaForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Therapy area updated.")
            return redirect("publisher:therapy_list")
    else:
        form = TherapyAreaForm(instance=obj)
    return render(request, "publisher/therapy_form.html", {"form": form, "object": obj})


# ---------------------------
# Trigger Clusters
# ---------------------------
@staff_member_required
def trigger_cluster_list(request):
    q = (request.GET.get("q") or "").strip()
    rows = TriggerCluster.objects.all().order_by("display_name", "code")
    if q:
        rows = rows.filter(Q(code__icontains=q) | Q(display_name__icontains=q))
    return render(request, "publisher/trigger_cluster_list.html", {"rows": rows, "q": q})


@staff_member_required
def trigger_cluster_create(request):
    if request.method == "POST":
        form = TriggerClusterForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Trigger cluster created.")
            return redirect("publisher:triggercluster_list")
    else:
        form = TriggerClusterForm()
    return render(request, "publisher/triggercluster_form.html", {"form": form, "object": None})


@staff_member_required
def trigger_cluster_edit(request, pk):
    obj = get_object_or_404(TriggerCluster, pk=pk)
    if request.method == "POST":
        form = TriggerClusterForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Trigger cluster updated.")
            return redirect("publisher:triggercluster_list")
    else:
        form = TriggerClusterForm(instance=obj)
    return render(request, "publisher/triggercluster_form.html", {"form": form, "object": obj})


# ---------------------------
# Triggers
# ---------------------------
@staff_member_required
def trigger_list(request):
    q = (request.GET.get("q") or "").strip()
    rows = Trigger.objects.select_related("cluster", "primary_therapy").all().order_by("display_name", "code")
    if q:
        rows = rows.filter(Q(code__icontains=q) | Q(display_name__icontains=q))
    return render(request, "publisher/trigger_list.html", {"rows": rows, "q": q})


@staff_member_required
def trigger_create(request):
    if request.method == "POST":
        form = TriggerForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Trigger created.")
            return redirect("publisher:trigger_list")
    else:
        form = TriggerForm()
    return render(request, "publisher/trigger_form.html", {"form": form, "object": None})


@staff_member_required
def trigger_edit(request, pk):
    obj = get_object_or_404(Trigger, pk=pk)
    if request.method == "POST":
        form = TriggerForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Trigger updated.")
            return redirect("publisher:trigger_list")
    else:
        form = TriggerForm(instance=obj)
    return render(request, "publisher/trigger_form.html", {"form": form, "object": obj})


# ---------------------------
# Videos
# ---------------------------
@staff_member_required
def video_list(request):
    q = (request.GET.get("q") or "").strip()
    rows = Video.objects.all().order_by("code")
    if q:
        rows = rows.filter(Q(code__icontains=q))
    return render(request, "publisher/video_list.html", {"rows": rows, "q": q})


@staff_member_required
def video_create(request):
    FormSet = make_video_language_formset(extra=8)

    if request.method == "POST":
        form = VideoForm(request.POST)
        formset = FormSet(request.POST)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                video = form.save()

                clusters = list(form.cleaned_data.get("clusters") or [])
                for cluster in clusters:
                    VideoClusterVideo.objects.get_or_create(
                        video=video,
                        video_cluster=cluster,
                        defaults={"sort_order": 0},
                    )

                formset.instance = video
                formset.save()

            messages.success(request, "Video created.")
            return redirect("publisher:video_list")
    else:
        form = VideoForm()
        initial = [{"language_code": code} for code in ("en", "hi", "mr", "te", "ta", "bn", "ml", "kn")]
        formset = FormSet(initial=initial)

    return render(request, "publisher/video_form.html", {"form": form, "formset": formset, "object": None})


@staff_member_required
def video_edit(request, pk):
    video = get_object_or_404(Video, pk=pk)

    for code in ("en", "hi", "mr", "te", "ta", "bn", "ml", "kn"):
        video.languages.get_or_create(language_code=code, defaults={"title": "", "youtube_url": ""})

    FormSet = make_video_language_formset(extra=0)

    if request.method == "POST":
        form = VideoForm(request.POST, instance=video)
        formset = FormSet(request.POST, instance=video)

        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                form.save()
                formset.save()

                selected_clusters = list(form.cleaned_data.get("clusters") or [])
                selected_ids = {c.id for c in selected_clusters}
                existing_ids = set(video.clusters.values_list("id", flat=True))

                to_add = selected_ids - existing_ids
                to_remove = existing_ids - selected_ids

                if to_remove:
                    VideoClusterVideo.objects.filter(video=video, video_cluster_id__in=to_remove).delete()
                for cid in to_add:
                    VideoClusterVideo.objects.get_or_create(
                        video=video,
                        video_cluster_id=cid,
                        defaults={"sort_order": 0},
                    )

            messages.success(request, "Video updated.")
            return redirect("publisher:video_list")
    else:
        form = VideoForm(instance=video)
        formset = FormSet(instance=video)

    return render(request, "publisher/video_form.html", {"form": form, "formset": formset, "object": video})


# ---------------------------
# Bundles / Clusters
# ---------------------------
@staff_member_required
def cluster_list(request):
    q = (request.GET.get("q") or "").strip()
    rows = VideoCluster.objects.select_related("trigger").all().order_by("display_name", "code")
    if q:
        rows = rows.filter(Q(code__icontains=q) | Q(display_name__icontains=q))
    return render(request, "publisher/cluster_list.html", {"rows": rows, "q": q})


@staff_member_required
def cluster_create(request):
    # IMPORTANT: template expects lang_fs / vid_fs and cluster / is_new
    LangFS = make_cluster_language_formset(extra=8)
    VidFS = make_cluster_video_formset(extra=8)

    cluster = VideoCluster()

    if request.method == "POST":
        form = VideoClusterForm(request.POST)
        lang_fs = LangFS(request.POST, instance=cluster)
        vid_fs = VidFS(request.POST, instance=cluster)

        if form.is_valid() and lang_fs.is_valid() and vid_fs.is_valid():
            with transaction.atomic():
                cluster = form.save()
                lang_fs.instance = cluster
                vid_fs.instance = cluster
                lang_fs.save()
                vid_fs.save()

            messages.success(request, "Bundle created.")
            return redirect("publisher:cluster_list")
    else:
        form = VideoClusterForm()
        lang_fs = LangFS(instance=cluster)
        vid_fs = VidFS(instance=cluster)

    return render(
        request,
        "publisher/cluster_form.html",
        {
            "form": form,
            "cluster": cluster,
            "is_new": True,
            "lang_fs": lang_fs,
            "vid_fs": vid_fs,
            # Back-compat if any template still reads these
            "lang_formset": lang_fs,
            "video_formset": vid_fs,
            "object": None,
        },
    )


@staff_member_required
def cluster_edit(request, pk):
    cluster = get_object_or_404(VideoCluster, pk=pk)

    LangFS = make_cluster_language_formset(extra=5)
    VidFS = make_cluster_video_formset(extra=8)

    if request.method == "POST":
        form = VideoClusterForm(request.POST, instance=cluster)
        lang_fs = LangFS(request.POST, instance=cluster)
        vid_fs = VidFS(request.POST, instance=cluster)

        if form.is_valid() and lang_fs.is_valid() and vid_fs.is_valid():
            with transaction.atomic():
                form.save()
                lang_fs.save()
                vid_fs.save()

            messages.success(request, "Bundle updated.")
            return redirect("publisher:cluster_list")
    else:
        form = VideoClusterForm(instance=cluster)
        lang_fs = LangFS(instance=cluster)
        vid_fs = VidFS(instance=cluster)

    return render(
        request,
        "publisher/cluster_form.html",
        {
            "form": form,
            "cluster": cluster,
            "is_new": False,
            "lang_fs": lang_fs,
            "vid_fs": vid_fs,
            "lang_formset": lang_fs,
            "video_formset": vid_fs,
            "object": cluster,
        },
    )


# ---------------------------
# Bundle Trigger Maps (replaces Video Trigger Maps)
# ---------------------------
@staff_member_required
def map_list(request):
    q = (request.GET.get("q") or "").strip()

    bundles = VideoCluster.objects.select_related("trigger", "trigger__primary_therapy").all().order_by("display_name", "code")
    if q:
        bundles = bundles.filter(
            Q(code__icontains=q)
            | Q(display_name__icontains=q)
            | Q(trigger__code__icontains=q)
            | Q(trigger__display_name__icontains=q)
        )

    return render(request, "publisher/map_list.html", {"items": bundles, "q": q})


@staff_member_required
def map_create(request):
    if request.method == "POST":
        form = BundleTriggerMapForm(request.POST)
        if form.is_valid():
            bundle = form.cleaned_data["bundle"]
            trigger = form.cleaned_data["trigger"]
            bundle.trigger = trigger
            bundle.save(update_fields=["trigger"])
            messages.success(request, "Bundle trigger mapping saved.")
            return redirect("publisher:map_list")
    else:
        form = BundleTriggerMapForm()

    return render(request, "publisher/map_form.html", {"form": form, "object": None})


@staff_member_required
def map_edit(request, pk):
    bundle = get_object_or_404(VideoCluster, pk=pk)

    if request.method == "POST":
        form = BundleTriggerMapForm(request.POST, bundle_instance=bundle)
        if form.is_valid():
            trigger = form.cleaned_data["trigger"]
            bundle.trigger = trigger
            bundle.save(update_fields=["trigger"])
            messages.success(request, "Bundle trigger mapping updated.")
            return redirect("publisher:map_list")
    else:
        form = BundleTriggerMapForm(bundle_instance=bundle, initial={"trigger": bundle.trigger_id})

    return render(request, "publisher/map_form.html", {"form": form, "object": bundle})


@staff_member_required
def legacy_video_trigger_map_list(request):
    q = (request.GET.get("q") or "").strip()
    items = VideoTriggerMap.objects.select_related("trigger", "video").all().order_by("trigger__code", "video__code")
    if q:
        items = items.filter(Q(video__code__icontains=q) | Q(trigger__code__icontains=q))
    return render(request, "publisher/map_list.html", {"rows": items, "q": q})
