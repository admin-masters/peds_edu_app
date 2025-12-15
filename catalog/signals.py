from django.core.cache import cache
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Trigger, TriggerCluster, Video, VideoCluster, VideoClusterVideo, VideoTriggerMap, TherapyArea


def clear_catalog_cache() -> None:
    cache.delete("catalog_json_v1")


@receiver(post_save, sender=TriggerCluster)
@receiver(post_delete, sender=TriggerCluster)
@receiver(post_save, sender=TherapyArea)
@receiver(post_delete, sender=TherapyArea)
@receiver(post_save, sender=Trigger)
@receiver(post_delete, sender=Trigger)
@receiver(post_save, sender=Video)
@receiver(post_delete, sender=Video)
@receiver(post_save, sender=VideoCluster)
@receiver(post_delete, sender=VideoCluster)
@receiver(post_save, sender=VideoClusterVideo)
@receiver(post_delete, sender=VideoClusterVideo)
@receiver(post_save, sender=VideoTriggerMap)
@receiver(post_delete, sender=VideoTriggerMap)
def _on_catalog_change(*args, **kwargs):
    clear_catalog_cache()
