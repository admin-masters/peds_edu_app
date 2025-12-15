from __future__ import annotations

import csv
import os
import re
from typing import Dict, Optional

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.constants import DEFAULT_THUMBNAIL_URL, DEFAULT_VIDEO_URL, LANGUAGE_CODES
from catalog.models import (
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


def parse_bool(v: str) -> bool:
    return str(v).strip().lower() in {"1", "true", "yes", "y"}


def normalize_for_translit(text: str) -> str:
    # AI4Bharat engine works best on "words"; clean punctuation a bit.
    text = (text or "").replace("&", "and")
    # Keep letters/digits/spaces; replace other chars with space
    text = re.sub(r"[^0-9A-Za-z\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


class TranslitEngines:
    def __init__(self):
        self._engines: Dict[str, object] = {}
        self.available = False
        try:
            from ai4bharat.transliteration import XlitEngine  # type: ignore

            self._XlitEngine = XlitEngine
            self.available = True
        except Exception:
            self._XlitEngine = None
            self.available = False

    def translit(self, text: str, lang_code: str) -> str:
        if lang_code == "en":
            return text
        if not text:
            return text
        if not self.available:
            return text
        try:
            engine = self._engines.get(lang_code)
            if engine is None:
                engine = self._XlitEngine(lang_code, beam_width=6, rescore=True)
                self._engines[lang_code] = engine

            cleaned = normalize_for_translit(text)
            if not cleaned:
                return text

            out = engine.translit_sentence(cleaned)
            # API returns dict {lang_code: "..."}
            if isinstance(out, dict) and lang_code in out and out[lang_code]:
                return out[lang_code]
            return text
        except Exception:
            # Fail safe: don't break import if transliteration fails for any row
            return text


CLUSTER_SEED = [
    {
        "code": "ACUTE_DIAGNOSED",
        "display_name": "Acute condition – diagnosed now",
        "description": "Clear acute diagnosis made today; home care & red flags.",
        "sort_order": 10,
    },
    {
        "code": "SUSPECTED_MONITORING",
        "display_name": "Suspected condition – monitoring / watchful waiting",
        "description": "Diagnosis not yet confirmed; symptom diary, warning signs, staged tests.",
        "sort_order": 20,
    },
    {
        "code": "CHRONIC_CONDITION",
        "display_name": "Chronic condition – long-term care",
        "description": "Known chronic disease; daily care, flare management, follow-up.",
        "sort_order": 30,
    },
    {
        "code": "DRUG_OR_DEVICE",
        "display_name": "Drug / device – use & adherence",
        "description": "Education tied to a specific medicine, device or regimen.",
        "sort_order": 40,
    },
    {
        "code": "PREVENTIVE_CARE",
        "display_name": "Prevention – vaccines / growth / development",
        "description": "Well-child visits: vaccines, nutrition, development, screening.",
        "sort_order": 50,
    },
]


class Command(BaseCommand):
    help = "Import trigger/video master data from the provided CSV files. Safe to re-run (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path",
            type=str,
            default=".",
            help="Folder containing trigger_master.csv, video_master.csv, video_cluster_master.csv, video_cluster_video_master.csv, video_trigger_map_master.csv",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        base_path = options["path"]

        trigger_csv = os.path.join(base_path, "trigger_master.csv")
        video_csv = os.path.join(base_path, "video_master.csv")
        cluster_csv = os.path.join(base_path, "video_cluster_master.csv")
        cluster_video_csv = os.path.join(base_path, "video_cluster_video_master.csv")
        video_trigger_map_csv = os.path.join(base_path, "video_trigger_map_master.csv")

        for p in [trigger_csv, video_csv, cluster_csv, cluster_video_csv, video_trigger_map_csv]:
            if not os.path.exists(p):
                raise FileNotFoundError(f"Missing required file: {p}")

        self.stdout.write(self.style.NOTICE("Seeding trigger clusters..."))
        for row in CLUSTER_SEED:
            TriggerCluster.objects.update_or_create(
                code=row["code"],
                defaults={
                    "display_name": row["display_name"],
                    "description": row["description"],
                    "sort_order": row["sort_order"],
                    "is_active": True,
                },
            )

        # Build therapy areas from triggers and videos
        therapy_names = set()
        with open(trigger_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                therapy_names.add((r.get("primary_therapy_area") or "").strip())
        with open(video_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                therapy_names.add((r.get("primary_therapy_area") or "").strip())
        therapy_names = {n for n in therapy_names if n}

        self.stdout.write(self.style.NOTICE(f"Upserting {len(therapy_names)} therapy areas..."))
        for name in sorted(therapy_names):
            code = TherapyArea.code_from_name(name)
            TherapyArea.objects.update_or_create(code=code, defaults={"display_name": name, "is_active": True})

        # Helper maps
        clusters_by_code = {c.code: c for c in TriggerCluster.objects.all()}
        therapy_by_name = {t.display_name: t for t in TherapyArea.objects.all()}

        self.stdout.write(self.style.NOTICE("Importing triggers..."))
        with open(trigger_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                code = (r.get("trigger_code") or "").strip()
                cluster_code = (r.get("cluster_code") or "").strip()
                therapy_name = (r.get("primary_therapy_area") or "").strip()

                Trigger.objects.update_or_create(
                    code=code,
                    defaults={
                        "cluster": clusters_by_code[cluster_code],
                        "primary_therapy": therapy_by_name[therapy_name],
                        "subtopic_title": (r.get("subtopic_title") or "").strip(),
                        "doctor_trigger_label": (r.get("doctor_trigger_label") or "").strip(),
                        "navigation_pathways": (r.get("navigation_pathways") or "").strip(),
                        "search_keywords": (r.get("trigger_search_keywords") or "").strip(),
                        "is_active": True,
                    },
                )

        triggers_by_code = {t.code: t for t in Trigger.objects.all()}

        translit = TranslitEngines()
        if translit.available:
            self.stdout.write(self.style.NOTICE("AI4Bharat transliteration engine detected; generating localized titles."))
        else:
            self.stdout.write(
                self.style.WARNING(
                    "AI4Bharat transliteration engine NOT installed. Localized titles will remain in English. "
                    "Install with: pip install ai4bharat-transliteration"
                )
            )

        self.stdout.write(self.style.NOTICE("Importing videos + language rows..."))
        with open(video_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                vcode = (r.get("video_code") or "").strip()
                title_en = (r.get("title") or "").strip()
                description = (r.get("description") or "").strip()
                primary_trigger_code = (r.get("primary_trigger_code") or "").strip()
                therapy_name = (r.get("primary_therapy_area") or "").strip()
                is_published = parse_bool(r.get("is_published") or "false")
                search_keywords = (r.get("video_search_keywords") or "").strip()

                video, _ = Video.objects.update_or_create(
                    code=vcode,
                    defaults={
                        "description": description,
                        "primary_trigger": triggers_by_code.get(primary_trigger_code),
                        "primary_therapy": therapy_by_name.get(therapy_name),
                        "thumbnail_url": DEFAULT_THUMBNAIL_URL,
                        "is_published": is_published,
                        "search_keywords": search_keywords,
                    },
                )

                for lang in LANGUAGE_CODES:
                    title_local = title_en if lang == "en" else translit.translit(title_en, lang)
                    VideoLanguage.objects.update_or_create(
                        video=video,
                        language_code=lang,
                        defaults={
                            "title": title_local,
                            "youtube_url": DEFAULT_VIDEO_URL,
                        },
                    )

        videos_by_code = {v.code: v for v in Video.objects.all()}

        self.stdout.write(self.style.NOTICE("Importing video clusters + language rows..."))
        with open(cluster_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                ccode = (r.get("video_cluster_code") or "").strip()
                tcode = (r.get("trigger_code") or "").strip()
                name_en = (r.get("name") or "").strip()
                description = (r.get("description") or "").strip()
                is_published = parse_bool(r.get("is_published") or "false")
                search_keywords = (r.get("cluster_search_keywords") or "").strip()

                cluster, _ = VideoCluster.objects.update_or_create(
                    code=ccode,
                    defaults={
                        "trigger": triggers_by_code[tcode],
                        "description": description,
                        "is_published": is_published,
                        "search_keywords": search_keywords,
                    },
                )

                for lang in LANGUAGE_CODES:
                    name_local = name_en if lang == "en" else translit.translit(name_en, lang)
                    VideoClusterLanguage.objects.update_or_create(
                        video_cluster=cluster,
                        language_code=lang,
                        defaults={"name": name_local},
                    )

        clusters_by_code = {c.code: c for c in VideoCluster.objects.all()}

        self.stdout.write(self.style.NOTICE("Importing video_cluster → video mappings..."))
        with open(cluster_video_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                ccode = (r.get("video_cluster_code") or "").strip()
                vcode = (r.get("video_code") or "").strip()
                sort_order = int((r.get("sort_order") or "0").strip() or 0)
                VideoClusterVideo.objects.update_or_create(
                    video_cluster=clusters_by_code[ccode],
                    video=videos_by_code[vcode],
                    defaults={"sort_order": sort_order},
                )

        self.stdout.write(self.style.NOTICE("Importing video → trigger map (optional multi-trigger)..."))
        with open(video_trigger_map_csv, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                vcode = (r.get("video_code") or "").strip()
                tcode = (r.get("trigger_code") or "").strip()
                is_primary = parse_bool(r.get("is_primary") or "false")
                sort_order = int((r.get("sort_order") or "0").strip() or 0)
                if vcode in videos_by_code and tcode in triggers_by_code:
                    VideoTriggerMap.objects.update_or_create(
                        video=videos_by_code[vcode],
                        trigger=triggers_by_code[tcode],
                        defaults={"is_primary": is_primary, "sort_order": sort_order},
                    )

        self.stdout.write(self.style.SUCCESS("Import complete."))
