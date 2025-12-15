from __future__ import annotations

from django.db import models
from django.utils.text import slugify

from .constants import LANGUAGES


class TriggerCluster(models.Model):
    code = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "display_name")

    def __str__(self) -> str:
        return self.display_name


class TherapyArea(models.Model):
    code = models.CharField(max_length=50, unique=True)
    display_name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("sort_order", "display_name")

    def __str__(self) -> str:
        return self.display_name

    @staticmethod
    def code_from_name(name: str) -> str:
        return slugify(name).upper().replace("-", "_")[:50]


class Trigger(models.Model):
    code = models.CharField(max_length=80, unique=True)
    primary_therapy = models.ForeignKey(TherapyArea, on_delete=models.PROTECT, related_name="triggers")
    cluster = models.ForeignKey(TriggerCluster, on_delete=models.PROTECT, related_name="triggers")

    # What patient sees as page title
    subtopic_title = models.CharField(max_length=255)

    # What doctor/staff sees in the trigger list
    doctor_trigger_label = models.CharField(max_length=180)

    # Existing "pathways" string, if you want to keep
    navigation_pathways = models.TextField()

    search_keywords = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("doctor_trigger_label",)

    def __str__(self) -> str:
        return self.doctor_trigger_label


class Video(models.Model):
    code = models.CharField(max_length=80, unique=True)
    description = models.TextField(blank=True)
    primary_trigger = models.ForeignKey(
        Trigger, on_delete=models.SET_NULL, null=True, blank=True, related_name="primary_videos"
    )
    primary_therapy = models.ForeignKey(TherapyArea, on_delete=models.SET_NULL, null=True, blank=True)
    duration_seconds = models.IntegerField(null=True, blank=True)

    thumbnail_url = models.CharField(max_length=255, blank=True)

    is_published = models.BooleanField(default=False)
    search_keywords = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("code",)

    def __str__(self) -> str:
        return self.code


class VideoLanguage(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE, related_name="langs")
    language_code = models.CharField(max_length=10, choices=LANGUAGES)

    title = models.CharField(max_length=255)
    youtube_url = models.CharField(max_length=255)

    class Meta:
        unique_together = ("video", "language_code")

    def __str__(self) -> str:
        return f"{self.video.code} [{self.language_code}]"


class VideoCluster(models.Model):
    code = models.CharField(max_length=80, unique=True)
    trigger = models.ForeignKey(Trigger, on_delete=models.CASCADE, related_name="video_clusters")
    description = models.TextField(blank=True)
    sort_order = models.IntegerField(default=0)
    is_published = models.BooleanField(default=False)
    search_keywords = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("sort_order", "code")

    def __str__(self) -> str:
        return self.code


class VideoClusterLanguage(models.Model):
    video_cluster = models.ForeignKey(VideoCluster, on_delete=models.CASCADE, related_name="langs")
    language_code = models.CharField(max_length=10, choices=LANGUAGES)

    name = models.CharField(max_length=255)

    class Meta:
        unique_together = ("video_cluster", "language_code")

    def __str__(self) -> str:
        return f"{self.video_cluster.code} [{self.language_code}]"


class VideoClusterVideo(models.Model):
    video_cluster = models.ForeignKey(VideoCluster, on_delete=models.CASCADE, related_name="cluster_videos")
    video = models.ForeignKey(Video, on_delete=models.CASCADE)
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = ("video_cluster", "video")
        ordering = ("sort_order",)


class VideoTriggerMap(models.Model):
    video = models.ForeignKey(Video, on_delete=models.CASCADE)
    trigger = models.ForeignKey(Trigger, on_delete=models.CASCADE)
    is_primary = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0)

    class Meta:
        unique_together = ("video", "trigger")
        ordering = ("sort_order",)
