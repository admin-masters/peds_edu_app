from __future__ import annotations

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.utils.encoding import force_bytes, force_str
from django.db import transaction

from .forms import DoctorRegistrationForm, EmailAuthenticationForm, DoctorSetPasswordForm
from .models import Clinic, DoctorProfile, User, extract_postal_code
from .sendgrid_utils import send_email_via_sendgrid
from .tokens import doctor_password_token

logger = logging.getLogger(__name__)


def _build_absolute_url(path: str) -> str:
    base = settings.APP_BASE_URL.rstrip("/")
    return f"{base}{path}"


def _send_doctor_links_email(doctor: DoctorProfile, *, password_setup: bool) -> None:
    clinic_link = _build_absolute_url(reverse("sharing:doctor_share", kwargs={"doctor_id": doctor.doctor_id}))
    if password_setup:
        uid = urlsafe_base64_encode(force_bytes(doctor.user.pk))
        token = doctor_password_token.make_token(doctor.user)
        password_link = _build_absolute_url(reverse("accounts:password_reset", kwargs={"uidb64": uid, "token": token}))
        subject = "Your clinic education link + set your password"
        text = (
            f"Hello Dr. {doctor.user.full_name},\n\n"
            f"Your clinic's patient education system link is:\n{clinic_link}\n\n"
            "To set your password (first time), open this link:\n"
            f"{password_link}\n\n"
            "Regards,\nPatient Education Team\n"
        )
    else:
        subject = "Your clinic patient education system link"
        text = (
            f"Hello Dr. {doctor.user.full_name},\n\n"
            f"Your clinic's patient education system link is:\n{clinic_link}\n\n"
            "Regards,\nPatient Education Team\n"
        )
    send_email_via_sendgrid(doctor.user.email, subject, text)


def register_doctor(request: HttpRequest) -> HttpResponse:
    """Doctor registration + whitelabel creation.

    Creates:
    - User (email login) with unusable password
    - Clinic
    - DoctorProfile

    Then emails doctor the clinic link and password setup link.
    """

    if request.method == "GET":
        # Generate a provisional doctor_id to show in the form.
        provisional_id = DoctorProfile._meta.get_field("doctor_id").default()
        form = DoctorRegistrationForm(initial={"doctor_id": provisional_id})
        return render(request, "accounts/register.html", {"form": form})

    form = DoctorRegistrationForm(request.POST, request.FILES)
    if not form.is_valid():
        return render(request, "accounts/register.html", {"form": form})

    doctor_id = form.cleaned_data["doctor_id"].strip()
    full_name = form.cleaned_data["full_name"].strip()
    email = form.cleaned_data["email"].strip().lower()
    whatsapp_number = form.cleaned_data["whatsapp_number"].strip()
    imc_number = form.cleaned_data["imc_number"].strip()
    clinic_number = (form.cleaned_data.get("clinic_number") or "").strip()
    address_text = form.cleaned_data["address_text"].strip()
    state = form.cleaned_data["state"]
    photo = form.cleaned_data.get("photo")

    # Derive postal code (best-effort)
    postal_code = extract_postal_code(address_text) or ""

    with transaction.atomic():
        if User.objects.filter(email=email).exists():
            form.add_error("email", "This email is already registered.")
            return render(request, "accounts/register.html", {"form": form})

        if DoctorProfile.objects.filter(doctor_id=doctor_id).exists():
            # Rare collision: generate a new one.
            doctor_id = DoctorProfile._meta.get_field("doctor_id").default()

        user = User.objects.create_user(email=email, full_name=full_name, password=None)

        clinic_display_name = f"Dr. {full_name}"  # simple default branding
        clinic = Clinic.objects.create(
            display_name=clinic_display_name,
            clinic_phone=clinic_number,
            address_text=address_text,
            postal_code=postal_code,
            state=state,
        )

        doctor = DoctorProfile.objects.create(
            user=user,
            doctor_id=doctor_id,
            clinic=clinic,
            whatsapp_number=whatsapp_number,
            imc_number=imc_number,
            photo=photo,
        )

    # Email doctor with clinic link + password setup link
    _send_doctor_links_email(doctor, password_setup=True)

    clinic_link_path = reverse("sharing:doctor_share", kwargs={"doctor_id": doctor.doctor_id})
    clinic_link = _build_absolute_url(clinic_link_path)

    return render(
        request,
        "accounts/register_success.html",
        {
            "doctor": doctor,
            "clinic_link": clinic_link,
        },
    )


def doctor_login(request: HttpRequest) -> HttpResponse:
    """Email+password login.

    - Email must be same as used during doctor registration.
    - If password is not set yet, we send a password setup link and show a generic message.
    """

    if request.user.is_authenticated:
        return redirect("sharing:home")

    form = EmailAuthenticationForm(request, data=request.POST or None)

    if request.method == "POST" and form.is_valid():
        # AuthenticationForm has already authenticated and attached user
        user = form.get_user()
        login(request, user)
        next_url = request.GET.get("next") or reverse("sharing:home")
        return redirect(next_url)

    if request.method == "POST" and not form.is_valid():
        # If credentials invalid, check if email exists and password not set → trigger setup email.
        email = (request.POST.get("username") or "").strip().lower()
        if email:
            user = User.objects.filter(email=email).first()
            if user and not user.has_usable_password():
                _send_password_reset_email(user)
                messages.success(request, "Password setup instructions have been sent to your email address")
                # Clear errors to avoid confusing messaging.
                form = EmailAuthenticationForm(request)

    return render(request, "accounts/login.html", {"form": form})


@login_required
def doctor_logout(request: HttpRequest) -> HttpResponse:
    logout(request)
    return redirect("accounts:login")


def _send_password_reset_email(user: User) -> None:
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = doctor_password_token.make_token(user)
    link = _build_absolute_url(reverse("accounts:password_reset", kwargs={"uidb64": uid, "token": token}))

    subject = "Reset your password"
    text = (
        f"Hello {user.full_name},\n\n"
        "Password reset instructions:\n"
        f"{link}\n\n"
        "If you did not request this, you can ignore this message.\n\n"
        "Regards,\nPatient Education Team\n"
    )
    send_email_via_sendgrid(user.email, subject, text)


def request_password_reset(request: HttpRequest) -> HttpResponse:
    """Forgot password page.

    Per requirement, always respond with:
    "password reset instructions have been sent to your email address"

    (We do not reveal whether the email exists.)
    """

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip().lower()
        user = User.objects.filter(email=email).first()
        if user:
            _send_password_reset_email(user)
        messages.success(request, "password reset instructions have been sent to your email address")
        return redirect("accounts:login")

    return render(request, "accounts/password_request.html")


def password_reset(request: HttpRequest, uidb64: str, token: str) -> HttpResponse:
    """Set a new password via emailed link."""

    try:
        uid = force_str(urlsafe_base64_decode(uidb64))
        user = User.objects.get(pk=uid)
    except Exception:
        user = None

    if user is None or not doctor_password_token.check_token(user, token):
        return render(request, "accounts/password_reset_invalid.html")

    form = DoctorSetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Password updated. Please log in again with your new password.")
        return redirect("accounts:login")

    return render(request, "accounts/password_reset.html", {"form": form})
