from django.contrib import admin

from .models import (
    TherapyArea,
    TriggerCluster,
    Trigger,
    Video,
    VideoLanguage,
    VideoCluster,
    VideoClusterLanguage,
    VideoClusterVideo,
    VideoTriggerMap,
)


@admin.register(TriggerCluster)
class TriggerClusterAdmin(admin.ModelAdmin):
    list_display = ("code", "display_name", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("code", "display_name")


@admin.register(TherapyArea)
class TherapyAreaAdmin(admin.ModelAdmin):
    list_display = ("code", "display_name", "sort_order", "is_active")
    list_editable = ("sort_order", "is_active")
    search_fields = ("code", "display_name")


@admin.register(Trigger)
class TriggerAdmin(admin.ModelAdmin):
    list_display = ("code", "doctor_trigger_label", "cluster", "primary_therapy", "is_active")
    list_filter = ("cluster", "primary_therapy", "is_active")
    search_fields = ("code", "doctor_trigger_label", "subtopic_title", "search_keywords")


class VideoLanguageInline(admin.TabularInline):
    model = VideoLanguage
    extra = 0


@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ("code", "primary_trigger", "is_published")
    list_filter = ("is_published",)
    search_fields = ("code", "search_keywords")
    inlines = [VideoLanguageInline]


class VideoClusterLanguageInline(admin.TabularInline):
    model = VideoClusterLanguage
    extra = 0


class VideoClusterVideoInline(admin.TabularInline):
    model = VideoClusterVideo
    extra = 0


@admin.register(VideoCluster)
class VideoClusterAdmin(admin.ModelAdmin):
    list_display = ("code", "trigger", "sort_order", "is_published")
    list_filter = ("is_published", "trigger")
    search_fields = ("code", "search_keywords")
    inlines = [VideoClusterLanguageInline, VideoClusterVideoInline]


@admin.register(VideoTriggerMap)
class VideoTriggerMapAdmin(admin.ModelAdmin):
    list_display = ("video", "trigger", "is_primary", "sort_order")
    list_filter = ("is_primary",)
    search_fields = ("video__code", "trigger__code")
