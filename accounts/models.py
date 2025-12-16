from __future__ import annotations

import re
import secrets
import string

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models
from django.utils import timezone
from .email_log import EmailLog  # noqa: F401


INDIA_STATES_AND_UTS = [
    # States (28)
    "Andhra Pradesh",
    "Arunachal Pradesh",
    "Assam",
    "Bihar",
    "Chhattisgarh",
    "Goa",
    "Gujarat",
    "Haryana",
    "Himachal Pradesh",
    "Jharkhand",
    "Karnataka",
    "Kerala",
    "Madhya Pradesh",
    "Maharashtra",
    "Manipur",
    "Meghalaya",
    "Mizoram",
    "Nagaland",
    "Odisha",
    "Punjab",
    "Rajasthan",
    "Sikkim",
    "Tamil Nadu",
    "Telangana",
    "Tripura",
    "Uttar Pradesh",
    "Uttarakhand",
    "West Bengal",
    # Union Territories (8)
    "Andaman and Nicobar Islands",
    "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi",
    "Jammu and Kashmir",
    "Ladakh",
    "Lakshadweep",
    "Puducherry",
]

INDIA_STATE_CHOICES = [(s, s) for s in INDIA_STATES_AND_UTS]


def _generate_code(prefix: str = "", length: int = 8) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return prefix + "".join(secrets.choice(alphabet) for _ in range(length))


# ✅ Migration-safe defaults (NO lambdas)
def default_clinic_code() -> str:
    return _generate_code("CL", 8)


def default_doctor_id() -> str:
    return _generate_code("", 8)


def extract_postal_code(address_text: str) -> str | None:
    """Best-effort extraction of Indian PIN code (6 digits) from address."""
    m = re.search(r"\b(\d{6})\b", address_text or "")
    return m.group(1) if m else None


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email: str, full_name: str, password: str | None, **extra_fields):
        if not email:
            raise ValueError("Email must be set")
        email = self.normalize_email(email)
        user = self.model(email=email, full_name=full_name, **extra_fields)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save(using=self._db)
        return user

    def create_user(self, email: str, full_name: str, password: str | None = None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, full_name, password, **extra_fields)

    def create_superuser(self, email: str, full_name: str, password: str, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True")
        return self._create_user(email, full_name, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """Custom user model using email as the primary identifier."""

    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    def __str__(self) -> str:
        return self.email


class Clinic(models.Model):
    clinic_code = models.CharField(
        max_length=12,
        unique=True,
        default=default_clinic_code,  # ✅ fixed
    )
    display_name = models.CharField(max_length=255, blank=True)
    clinic_phone = models.CharField(
        max_length=15,
        blank=True,
        validators=[RegexValidator(r"^\d{6,15}$", "Enter a valid phone number (digits only).")],
    )
    address_text = models.TextField()
    postal_code = models.CharField(max_length=6, blank=True)
    state = models.CharField(max_length=64, choices=INDIA_STATE_CHOICES)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.display_name or self.clinic_code


class DoctorProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="doctor_profile",
    )

    # System-generated doctor id shown on the registration form
    doctor_id = models.CharField(
        max_length=12,
        unique=True,
        default=default_doctor_id,  # ✅ fixed
    )

    clinic = models.ForeignKey(Clinic, on_delete=models.PROTECT, related_name="doctors")

    whatsapp_number = models.CharField(
        max_length=10,
        validators=[RegexValidator(r"^\d{10}$", "Enter a 10-digit WhatsApp number (without country code).")],
    )
    imc_number = models.CharField(max_length=64)

    photo = models.ImageField(upload_to="doctor_photos/", blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.user.full_name} ({self.doctor_id})"
