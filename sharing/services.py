from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.cache import cache

from catalog.models import TriggerCluster, Video, VideoCluster


# Cache key/versioning
_CATALOG_CACHE_KEY = "clinic_catalog_json_v1"
_CATALOG_CACHE_SECONDS = int(getattr(settings, "CATALOG_CACHE_SECONDS", 3600) or 3600)


def _safe_str(x: Any) -> str:
    return "" if x is None else str(x)


def _trigger_cluster_id(tc: TriggerCluster) -> str:
    """
    Backward-compatible cluster identifier.
    Some DB/model versions may not have tc.code.
    """
    code = getattr(tc, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip()
    return str(tc.pk)


def _video_cluster_id(vc: VideoCluster) -> str:
    code = getattr(vc, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip()
    return str(vc.pk)


def build_whatsapp_message_prefixes() -> Dict[str, str]:
    """
    sharing/views.py imports this.
    Keep it simple and safe:
    - Provide at least English
    - Optionally extend based on settings.LANGUAGES if present
    """
    prefixes: Dict[str, str] = {"en": "Please see: "}
    langs = getattr(settings, "LANGUAGES", None)
    if isinstance(langs, (list, tuple)):
        for code, _name in langs:
            if code not in prefixes:
                prefixes[code] = prefixes["en"]
    return prefixes


def _build_catalog_payload() -> Dict[str, Any]:
    """
    Build the JSON payload used by doctor_share page.
    Must be backward compatible with older DB schemas.
    """
    # Trigger clusters
    # Some schemas may not have sort_order; order by id as fallback.
    tc_qs = TriggerCluster.objects.all()
    try:
        tc_qs = tc_qs.order_by("sort_order", "id")
    except Exception:
        tc_qs = tc_qs.order_by("id")

    clusters_payload: List[Dict[str, Any]] = []
    for tc in tc_qs:
        clusters_payload.append(
            {
                "id": _trigger_cluster_id(tc),
                "display_name": _safe_str(getattr(tc, "display_name", "") or tc),
            }
        )

    # Video clusters (bundles)
    vc_qs = VideoCluster.objects.all()
    try:
        vc_qs = vc_qs.order_by("sort_order", "id")
    except Exception:
        vc_qs = vc_qs.order_by("id")

    video_cluster_pk_to_id: Dict[int, str] = {}
    for vc in vc_qs:
        video_cluster_pk_to_id[int(vc.pk)] = _video_cluster_id(vc)

    # Videos
    v_qs = Video.objects.all()
    try:
        v_qs = v_qs.order_by("sort_order", "id")
    except Exception:
        v_qs = v_qs.order_by("id")

    videos_payload: List[Dict[str, Any]] = []
    for v in v_qs:
        # Cluster ids for this video (M2M may not exist in older schema)
        cluster_ids: List[str] = []
        try:
            for vc in v.clusters.all():
                cluster_ids.append(video_cluster_pk_to_id.get(int(vc.pk), str(vc.pk)))
        except Exception:
            cluster_ids = []

        titles: Dict[str, str] = {}
        urls: Dict[str, str] = {}

        # Preferred: per-language rows
        try:
            for lang in v.languages.all():
                titles[lang.language_code] = _safe_str(lang.title)
                urls[lang.language_code] = _safe_str(lang.youtube_url)
        except Exception:
            # Fallback: old schema may not have languages table
            titles["en"] = _safe_str(getattr(v, "code", "") or "Video")
            # If you don’t have youtube_url per language, keep blank; UI will still render.
            urls["en"] = ""

        videos_payload.append(
            {
                "id": _safe_str(getattr(v, "code", None) or v.pk),
                "cluster_ids": cluster_ids,
                "titles": titles,
                "urls": urls,
                "trigger_names": [],
                "search_text": (_safe_str(getattr(v, "code", "")).lower()),
            }
        )

    payload = {
        "clusters": clusters_payload,
        "videos": videos_payload,
        "message_prefixes": build_whatsapp_message_prefixes(),
    }
    return payload


def get_catalog_json_cached(force_refresh: bool = False) -> str:
    """
    sharing/views.py imports this.
    Returns JSON string for embedding into templates.
    """
    if not force_refresh:
        cached = cache.get(_CATALOG_CACHE_KEY)
        if isinstance(cached, str) and cached.strip():
            return cached

    payload = _build_catalog_payload()
    data = json.dumps(payload, ensure_ascii=False)
    cache.set(_CATALOG_CACHE_KEY, data, timeout=_CATALOG_CACHE_SECONDS)
    return data
