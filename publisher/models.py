from __future__ import annotations

from django.db import models


def _banner_small_upload_to(instance: "Campaign", filename: str) -> str:
    return f"campaign_banners/{instance.campaign_id}/small/{filename}"


def _banner_large_upload_to(instance: "Campaign", filename: str) -> str:
    return f"campaign_banners/{instance.campaign_id}/large/{filename}"


class Campaign(models.Model):
    """
    NOTE:
    - This model maps to the manually-created MySQL table `publisher_campaign`.
    - `managed = False` so Django does not attempt to create/alter it via migrations.
    """

    campaign_id = models.CharField(max_length=100, unique=True, db_index=True)
    new_video_cluster_name = models.CharField(max_length=255)

    # JSON string of selections: [{"type":"video","id":1}, {"type":"cluster","id":2}]
    selection_json = models.TextField(blank=False, default="")

    doctors_supported = models.PositiveIntegerField(default=0)

    banner_small = models.FileField(upload_to=_banner_small_upload_to, max_length=500)
    banner_large = models.FileField(upload_to=_banner_large_upload_to, max_length=500)

    banner_target_url = models.URLField(max_length=500)

    start_date = models.DateField()
    end_date = models.DateField()

    # New video-cluster created for this campaign
    video_cluster = models.OneToOneField(
        "catalog.VideoCluster",
        on_delete=models.PROTECT,
        related_name="campaign",
    )

    # Publisher identity from JWT
    publisher_sub = models.CharField(max_length=100, blank=True, default="")
    publisher_username = models.CharField(max_length=150, blank=True, default="")
    publisher_roles = models.CharField(max_length=255, blank=True, default="")
    # Campaign messaging (new fields)
    email_registration = models.TextField(blank=True, default="")
    wa_addition = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "publisher_campaign"
        managed = False

    def __str__(self) -> str:
        return f"{self.campaign_id} ({self.new_video_cluster_name})"
