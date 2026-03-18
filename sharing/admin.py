from django.contrib import admin

from .models import DoctorShareSummary, ShareActivity, SharePlaybackEvent


@admin.register(DoctorShareSummary)
class DoctorShareSummaryAdmin(admin.ModelAdmin):
    list_display = ("doctor_id", "doctor_name_snapshot", "clinic_name_snapshot", "total_shares", "last_shared_at")
    search_fields = ("doctor_id", "doctor_name_snapshot", "clinic_name_snapshot")
    ordering = ("-last_shared_at", "doctor_id")


@admin.register(ShareActivity)
class ShareActivityAdmin(admin.ModelAdmin):
    list_display = (
        "doctor_id",
        "shared_item_type",
        "shared_item_name",
        "language_code",
        "recipient_reference",
        "shared_by_role",
        "shared_at",
    )
    search_fields = ("doctor_id", "doctor_name_snapshot", "clinic_name_snapshot", "shared_item_code", "shared_item_name")
    list_filter = ("shared_item_type", "language_code", "shared_by_role", "share_channel")
    ordering = ("-shared_at",)
    readonly_fields = ("public_id", "shared_at")


@admin.register(SharePlaybackEvent)
class SharePlaybackEventAdmin(admin.ModelAdmin):
    list_display = ("doctor_id", "page_item_type", "event_type", "video_code", "milestone_percent", "occurred_at")
    search_fields = ("doctor_id", "video_code", "video_name")
    list_filter = ("page_item_type", "event_type")
    ordering = ("-occurred_at",)
