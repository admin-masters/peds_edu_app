# sharing/services.py
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.cache import cache

from catalog.models import Video, VideoCluster, VideoClusterVideo


# Bump the key to avoid serving old cached *string* JSON that breaks the UI
_CATALOG_CACHE_KEY = "clinic_catalog_payload_v5"
_CATALOG_CACHE_SECONDS = 15 * 60  # 15 min


def _safe_str(v: Any) -> str:
    return "" if v is None else str(v)


def build_whatsapp_message_prefixes(doctor_name: Optional[str] = None) -> Dict[str, str]:
    """
    Returns per-language WhatsApp message prefixes.
    Keys must match the <select> values (language codes like 'en', 'hi', etc.).
    """
    doctor_name = (doctor_name or "").strip()
    if doctor_name:
        base = f"Dr. {doctor_name} shared a patient education video:\n\n"
    else:
        base = "Please see this patient education video:\n\n"

    out: Dict[str, str] = {}
    for code, _label in getattr(settings, "LANGUAGES", [("en", "English")]):
        out[code] = base
    out.setdefault("en", base)
    return out


def _build_catalog_payload() -> Dict[str, Any]:
    # 1) Clusters (bundles)
    c_qs = VideoCluster.objects.all()
    try:
        c_qs = c_qs.order_by("sort_order", "id")
    except Exception:
        c_qs = c_qs.order_by("id")

    clusters = list(c_qs)

    cluster_id_to_name: Dict[str, str] = {}
    for c in clusters:
        cid = str(c.pk)
        cluster_id_to_name[cid] = (
            _safe_str(getattr(c, "display_name", ""))  # your DB has display_name
            or _safe_str(getattr(c, "code", ""))       # fallback
            or cid
        )

    # 2) Videos
    v_qs = Video.objects.all().prefetch_related("languages")
    try:
        v_qs = v_qs.order_by("sort_order", "id")
    except Exception:
        v_qs = v_qs.order_by("id")

    videos = list(v_qs)

    # 3) Map video -> cluster_ids using the DB join table catalog_videoclustervideo
    video_to_cluster_ids: Dict[int, List[str]] = defaultdict(list)

    try:
        # If the join table is populated, this is the correct mapping
        rows = (
            VideoClusterVideo.objects
            .all()
            .order_by("sort_order", "id")
            .values_list("video_id", "cluster_id")
        )
        for vid, cid in rows:
            video_to_cluster_ids[int(vid)].append(str(cid))
    except Exception:
        # Fallback: try the M2M if present/usable
        for v in videos:
            try:
                for c in v.clusters.all():  # type: ignore[attr-defined]
                    video_to_cluster_ids[int(v.pk)].append(str(c.pk))
            except Exception:
                pass

    # If still no mapping at all, force a usable UI:
    # create a single "All Videos" cluster and assign all videos to it.
    has_any_mapping = any(video_to_cluster_ids.values())
    if not has_any_mapping:
        clusters_payload = [{"id": "all", "display_name": "All Videos"}]
    else:
        # keep only clusters that actually have videos
        used_cluster_ids = set()
        for cids in video_to_cluster_ids.values():
            used_cluster_ids.update(cids)

        clusters_payload = []
        for c in clusters:
            cid = str(c.pk)
            if cid in used_cluster_ids:
                clusters_payload.append(
                    {"id": cid, "display_name": cluster_id_to_name.get(cid, cid)}
                )

    videos_payload: List[Dict[str, Any]] = []
    for v in videos:
        vid_int = int(v.pk)

        if not has_any_mapping:
            cluster_ids = ["all"]
            trigger_names = []
        else:
            cluster_ids = video_to_cluster_ids.get(vid_int, [])
            trigger_names = [cluster_id_to_name.get(cid, cid) for cid in cluster_ids]

        titles: Dict[str, str] = {}
        urls: Dict[str, str] = {}

        try:
            for lang in v.languages.all():
                lc = _safe_str(getattr(lang, "language_code", "")).strip() or "en"
                titles[lc] = _safe_str(getattr(lang, "title", "")).strip() or _safe_str(getattr(v, "code", "") or "Video")
                urls[lc] = _safe_str(getattr(lang, "youtube_url", "")).strip()
        except Exception:
            titles["en"] = _safe_str(getattr(v, "code", "") or "Video")
            urls["en"] = ""

        search_blob = " ".join([*titles.values(), *trigger_names, _safe_str(getattr(v, "code", ""))]).lower()

        videos_payload.append(
            {
                # IMPORTANT: patient_video view expects Video.code
                "id": _safe_str(getattr(v, "code", None) or v.pk),
                "cluster_ids": cluster_ids,
                "titles": titles,
                "urls": urls,
                "trigger_names": trigger_names,
                "search_text": search_blob,
            }
        )

    return {
        "clusters": clusters_payload,
        "videos": videos_payload,
        "message_prefixes": build_whatsapp_message_prefixes(),
    }


def get_catalog_json_cached(force_refresh: bool = False) -> Dict[str, Any]:
    """
    NOTE: despite the name, we return a Python dict (JSON-serializable),
    because templates use `json_script` and JS does JSON.parse once.
    """
    if not force_refresh:
        cached = cache.get(_CATALOG_CACHE_KEY)
        if isinstance(cached, dict) and cached.get("clusters") is not None:
            return cached
        # If old cache contains a JSON string, try to recover safely:
        if isinstance(cached, str) and cached.strip():
            try:
                parsed = json.loads(cached)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass

    payload = _build_catalog_payload()
    cache.set(_CATALOG_CACHE_KEY, payload, timeout=_CATALOG_CACHE_SECONDS)
    return payload
