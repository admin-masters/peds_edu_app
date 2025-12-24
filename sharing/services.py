from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from catalog.models import TriggerCluster, Video, VideoCluster


@dataclass
class ClinicCatalog:
    clusters: List[Dict[str, Any]]
    videos: List[Dict[str, Any]]
    message_prefixes: Dict[str, str]


def _cluster_id(tc: TriggerCluster) -> str:
    """
    Backward-compatible cluster identifier.
    Older DB/model versions may not have tc.code.
    """
    code = getattr(tc, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip()
    return str(tc.pk)


def build(doctor) -> Dict[str, Any]:
    """
    Build the JSON payload used by doctor_share page.
    Must be backward compatible with older DB schemas.
    """
    # Trigger clusters
    trigger_clusters = TriggerCluster.objects.all().order_by("sort_order", "id")

    clusters_payload: List[Dict[str, Any]] = []
    for tc in trigger_clusters:
        clusters_payload.append(
            {
                "id": _cluster_id(tc),
                "display_name": getattr(tc, "display_name", "") or str(tc),
            }
        )

    # Video clusters (bundles)
    video_clusters = VideoCluster.objects.all().order_by("sort_order", "id")
    video_cluster_map = {}
    for vc in video_clusters:
        vc_id = getattr(vc, "code", None)
        if not vc_id:
            vc_id = str(vc.pk)
        video_cluster_map[vc.pk] = str(vc_id)

    # Videos
    videos_qs = Video.objects.all().order_by("sort_order", "id")
    videos_payload: List[Dict[str, Any]] = []

    for v in videos_qs:
        # Collect cluster ids for this video (if M2M exists)
        cluster_ids: List[str] = []
        try:
            for vc in v.clusters.all():
                cluster_ids.append(video_cluster_map.get(vc.pk, str(vc.pk)))
        except Exception:
            cluster_ids = []

        # Titles/URLs are expected as dicts by share.html
        titles = {}
        urls = {}

        # If language objects exist
        try:
            for lang in v.languages.all():
                titles[lang.language_code] = lang.title
                urls[lang.language_code] = lang.youtube_url
        except Exception:
            # Fallback: single title/url if older schema
            titles["en"] = getattr(v, "code", "") or "Video"
            urls["en"] = getattr(v, "thumbnail_url", "") or ""

        videos_payload.append(
            {
                "id": getattr(v, "code", None) or str(v.pk),
                "cluster_ids": cluster_ids,
                "titles": titles,
                "urls": urls,
                "trigger_names": [],
                "search_text": (getattr(v, "code", "") or "").lower(),
            }
        )

    # WhatsApp message prefixes per language (fallback)
    message_prefixes = {"en": "Please see: "}

    return {
        "clusters": clusters_payload,
        "videos": videos_payload,
        "message_prefixes": message_prefixes,
    }
