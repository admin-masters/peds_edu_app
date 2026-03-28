from __future__ import annotations

import hashlib
import hmac
import re
import uuid

from django.conf import settings
from django.db import models


class DoctorShareSummary(models.Model):
    doctor_id = models.CharField(max_length=32, unique=True)
    doctor_name_snapshot = models.CharField(max_length=255, blank=True, default="")
    clinic_name_snapshot = models.CharField(max_length=255, blank=True, default="")
    total_shares = models.PositiveBigIntegerField(default=0)
    last_shared_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["doctor_id"]
        indexes = [
            models.Index(fields=["last_shared_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.doctor_id} ({self.total_shares} shares)"


class ShareActivity(models.Model):
    class SharedItemType(models.TextChoices):
        VIDEO = "video", "Single video"
        CLUSTER = "cluster", "Video bundle/cluster"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    doctor_summary = models.ForeignKey(
        DoctorShareSummary,
        on_delete=models.CASCADE,
        related_name="shares",
    )
    doctor_id = models.CharField(max_length=32, db_index=True)
    doctor_name_snapshot = models.CharField(max_length=255, blank=True, default="")
    clinic_name_snapshot = models.CharField(max_length=255, blank=True, default="")
    share_channel = models.CharField(max_length=30, default="whatsapp")
    shared_by_role = models.CharField(max_length=30, blank=True, default="")
    shared_item_type = models.CharField(
        max_length=20,
        choices=SharedItemType.choices,
        db_index=True,
    )
    shared_item_code = models.CharField(max_length=80)
    shared_item_name = models.CharField(max_length=255)
    language_code = models.CharField(max_length=10, default="en")
    recipient_reference = models.CharField(max_length=80, db_index=True)
    recipient_reference_version = models.PositiveSmallIntegerField(default=1)
    shared_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-shared_at"]
        indexes = [
            models.Index(fields=["doctor_id", "shared_at"]),
            models.Index(fields=["shared_item_type", "shared_item_code"]),
        ]

    def __str__(self) -> str:
        return f"{self.doctor_id} -> {self.shared_item_type}:{self.shared_item_code}"


class SharePlaybackEvent(models.Model):
    class EventType(models.TextChoices):
        PLAY = "play", "Video play"
        PROGRESS = "progress", "View progress milestone"

    share = models.ForeignKey(
        ShareActivity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="playback_events",
    )
    share_public_id = models.UUIDField(null=True, blank=True, db_index=True)
    doctor_summary = models.ForeignKey(
        DoctorShareSummary,
        on_delete=models.CASCADE,
        related_name="playback_events",
    )
    doctor_id = models.CharField(max_length=32, db_index=True)
    page_item_type = models.CharField(
        max_length=20,
        choices=ShareActivity.SharedItemType.choices,
    )
    event_type = models.CharField(
        max_length=20,
        choices=EventType.choices,
        db_index=True,
    )
    video_code = models.CharField(max_length=80)
    video_name = models.CharField(max_length=255, blank=True, default="")
    milestone_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(fields=["doctor_id", "occurred_at"]),
            models.Index(fields=["video_code", "event_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.doctor_id} {self.event_type} {self.video_code}"


class ShareBannerClickEvent(models.Model):
    class PageType(models.TextChoices):
        DOCTOR = "doctor", "Doctor"
        CLINIC = "clinic", "Clinic"

    doctor_summary = models.ForeignKey(
        DoctorShareSummary,
        on_delete=models.CASCADE,
        related_name="banner_clicks",
    )
    doctor_id = models.CharField(max_length=32, db_index=True)
    page_type = models.CharField(
        max_length=20,
        choices=PageType.choices,
        db_index=True,
    )
    banner_id = models.CharField(max_length=80, blank=True, default="", db_index=True)
    banner_name = models.CharField(max_length=255, blank=True, default="")
    banner_target_url = models.URLField(max_length=500, blank=True, default="")
    clicked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-clicked_at"]
        indexes = [
            models.Index(fields=["doctor_id", "clicked_at"], name="sharing_banner_doctor_time_idx"),
            models.Index(fields=["banner_id", "clicked_at"], name="sharing_banner_id_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.doctor_id} {self.page_type} {self.banner_name or self.banner_id}"


def normalize_recipient_identifier(raw_value: str) -> str:
    digits = re.sub(r"\D", "", str(raw_value or ""))
    if digits:
        return digits
    return str(raw_value or "").strip().lower()


def build_anonymized_recipient_reference(*, doctor_id: str, recipient_identifier: str) -> str:
    normalized = normalize_recipient_identifier(recipient_identifier)
    if not normalized:
        return ""

    digest = hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        f"{doctor_id}:{normalized}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"v1_{digest}"
