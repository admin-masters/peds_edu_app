from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import (
    TherapyArea,
    Trigger,
    TriggerCluster,
    Video,
    VideoCluster,
    VideoClusterVideo,
    VideoTriggerMap,
)

# IMPORTANT:
# Share page uses clinic_catalog_payload_v6 (previously v5).
# Old signal only deleted catalog_json_v1, causing stale payloads.
CATALOG_CACHE_KEYS = [
    "clinic_catalog_payload_v5",
    "clinic_catalog_payload_v6",
]


def clear_catalog_cache() -> None:
    """
    Clear all catalog payload caches to prevent stale
    bundles / topics / therapy areas on the share page.
    """
    for key in CATALOG_CACHE_KEYS:
        try:
            cache.delete(key)
        except Exception:
            pass


@receiver(post_save, sender=TherapyArea)
@receiver(post_delete, sender=TherapyArea)
@receiver(post_save, sender=TriggerCluster)
@receiver(post_delete, sender=TriggerCluster)
@receiver(post_save, sender=Trigger)
@receiver(post_delete, sender=Trigger)
@receiver(post_save, sender=VideoCluster)
@receiver(post_delete, sender=VideoCluster)
@receiver(post_save, sender=Video)
@receiver(post_delete, sender=Video)
@receiver(post_save, sender=VideoClusterVideo)
@receiver(post_delete, sender=VideoClusterVideo)
@receiver(post_save, sender=VideoTriggerMap)
@receiver(post_delete, sender=VideoTriggerMap)
def _on_catalog_change(*args, **kwargs):
    clear_catalog_cache()
