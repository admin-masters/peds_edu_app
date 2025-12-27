from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List

from django.conf import settings
from django.core.cache import cache

from catalog.constants import LANGUAGES
from catalog.models import (
    TherapyArea,
    Trigger,
    TriggerCluster,
    Video,
    VideoLanguage,
    VideoCluster,
    VideoClusterLanguage,
    VideoClusterVideo,
)

_CATALOG_CACHE_KEY = "clinic_catalog_payload_v7"
_CATALOG_CACHE_SECONDS = 60 * 60  # 1 hour


def build_whatsapp_message_prefixes(doctor_name: str) -> Dict[str, str]:
    """
    Prefix only. The final WhatsApp message is built in the front-end as:
      <prefix>\n\n<title>\n<link>

    NOTE: doctor_name is injected per-request in sharing.views.doctor_share.
    """
    doctor = (doctor_name or "").strip() or "your doctor"

    templates = {
        "en": (
            "Your doctor {doctor} has sent you the following video/videos. "
            "It is very important that you view them and follow the instructions, "
            "as these are for important observations by your doctor. "
            "Your child's health and wellbeing depend upon following the instructions in the videos."
        ),
        "hi": (
            "आपके डॉक्टर {doctor} ने आपको निम्न वीडियो/वीडियो भेजे हैं। "
            "कृपया इन्हें ध्यान से देखें और वीडियो में दिए गए निर्देशों का पालन करें, "
            "क्योंकि ये आपके डॉक्टर के महत्वपूर्ण निरीक्षणों के लिए हैं। "
            "आपके बच्चे का स्वास्थ्य और भलाई इन वीडियो में दिए गए निर्देशों का पालन करने पर निर्भर है।"
        ),
        "mr": (
            "तुमचे डॉक्टर {doctor} यांनी तुम्हाला खालील व्हिडिओ/व्हिडिओ पाठवले आहेत. "
            "कृपया ते काळजीपूर्वक पहा आणि व्हिडिओमध्ये दिलेल्या सूचनांचे पालन करा, "
            "कारण हे तुमच्या डॉक्टरांच्या महत्त्वाच्या निरीक्षणांसाठी आहेत. "
            "तुमच्या मुलाचे आरोग्य आणि कल्याण व्हिडिओमधील सूचनांचे पालन करण्यावर अवलंबून आहे."
        ),
        "te": (
            "మీ డాక్టర్ {doctor} మీకు క్రింది వీడియో/వీడియోలను పంపించారు. "
            "దయచేసి వాటిని జాగ్రత్తగా చూడండి మరియు వీడియోలో ఇచ్చిన సూచనలను అనుసరించండి, "
            "ఎందుకంటే ఇవి మీ డాక్టర్ యొక్క ముఖ్యమైన పరిశీలనల కోసం. "
            "మీ పిల్లల ఆరోగ్యం మరియు శ్రేయస్సు వీడియోల్లో ఉన్న సూచనలను అనుసరించడంపై ఆధారపడి ఉంటుంది."
        ),
        "ta": (
            "உங்கள் மருத்துவர் {doctor} உங்களுக்கு கீழ்க்கண்ட வீடியோ/வீடியோக்களை அனுப்பியுள்ளார். "
            "தயவுசெய்து அவற்றை கவனமாகப் பார்த்து, வீடியோவில் கொடுக்கப்பட்ட வழிமுறைகளைப் பின்பற்றுங்கள், "
            "ஏனெனில் இவை உங்கள் மருத்துவரின் முக்கியமான கண்காணிப்புகளுக்கானவை. "
            "உங்கள் குழந்தையின் ஆரோக்கியமும் நலனும் இந்த வீடியோக்களில் உள்ள வழிமுறைகளைப் பின்பற்றுவதில் சார்ந்துள்ளது."
        ),
        "bn": (
            "আপনার ডাক্তার {doctor} আপনাকে নিম্নলিখিত ভিডিও/ভিডিওগুলো পাঠিয়েছেন। "
            "অনুগ্রহ করে সেগুলো মনোযোগ দিয়ে দেখুন এবং ভিডিওতে দেওয়া নির্দেশনা অনুসরণ করুন, "
            "কারণ এগুলো আপনার ডাক্তারের গুরুত্বপূর্ণ পর্যবেক্ষণের জন্য। "
            "আপনার সন্তানের স্বাস্থ্য ও কল্যাণ ভিডিওতে দেওয়া নির্দেশনা অনুসরণ করার উপর নির্ভর করে।"
        ),
        "ml": (
            "നിങ്ങളുടെ ഡോക്ടർ {doctor} നിങ്ങള്‍ക്കായി താഴെ പറയുന്ന വീഡിയോ/വീഡിയോകള്‍ അയച്ചിട്ടുണ്ട്. "
            "ദയവായി അവ ശ്രദ്ധാപൂർവ്വം കാണുകയും വീഡിയോയിലെ നിർദ്ദേശങ്ങൾ പാലിക്കുകയും ചെയ്യുക, "
            "കാരണം ഇവ നിങ്ങളുടെ ഡോക്ടറുടെ പ്രധാനപ്പെട്ട നിരീക്ഷണങ്ങൾക്കായാണ്. "
            "നിങ്ങളുടെ കുട്ടിയുടെ ആരോഗ്യവും ക്ഷേമവും വീഡിയോയിലെ നിർദ്ദേശങ്ങൾ പാലിക്കുന്നതിനെ ആശ്രയിച്ചിരിക്കുന്നു."
        ),
        "kn": (
            "ನಿಮ್ಮ ವೈದ್ಯರು {doctor} ಅವರು ನಿಮಗೆ ಕೆಳಗಿನ ವೀಡಿಯೊ/ವೀಡಿಯೊಗಳನ್ನು ಕಳುಹಿಸಿದ್ದಾರೆ. "
            "ದಯವಿಟ್ಟು ಅವನ್ನು ಗಮನದಿಂದ ನೋಡಿ ಹಾಗೂ ವೀಡಿಯೊಗಳಲ್ಲಿ ನೀಡಿರುವ ಸೂಚನೆಗಳನ್ನು ಅನುಸರಿಸಿ, "
            "ಏಕೆಂದರೆ ಇವು ನಿಮ್ಮ ವೈದ್ಯರ ಮಹತ್ವದ ಗಮನಿಸಿಕೆಗಳಿಗಾಗಿ. "
            "ನಿಮ್ಮ ಮಗುವಿನ ಆರೋಗ್ಯ ಮತ್ತು ಕಲ್ಯಾಣವು ವೀಡಿಯೊಗಳ ಸೂಚನೆಗಳನ್ನು ಪಾಲಿಸುವುದರ ಮೇಲೆ ಅವಲಂಬಿತವಾಗಿದೆ."
        ),
    }

    out: Dict[str, str] = {}
    for code, _label in LANGUAGES:
        tmpl = templates.get(code, templates["en"])
        out[code] = tmpl.format(doctor=doctor)
    return out


def _build_catalog_payload() -> Dict[str, Any]:
    """
    Catalog payload for the doctor's video sharing UI.

    Design goals:
    - Trigger (not Topic) based browsing.
    - Bundles list includes its videos so the UI can render grouped results.
    - Default ordering is alphabetical (no reliance on sort_order for UI).
    """

    # -----------------------------------------------------------------
    # Therapy Areas
    # -----------------------------------------------------------------
    therapy_areas = list(TherapyArea.objects.filter(is_active=True).order_by("display_name", "code"))
    therapy_payload = [
        {"code": ta.code, "display_name": ta.display_name, "description": ta.description}
        for ta in therapy_areas
    ]
    therapy_by_id = {ta.id: ta for ta in therapy_areas}

    # -----------------------------------------------------------------
    # Triggers
    # -----------------------------------------------------------------
    triggers = list(
        Trigger.objects.filter(is_active=True)
        .select_related("primary_therapy", "cluster")
        .order_by("display_name", "code")
    )
    triggers_payload = []
    for tr in triggers:
        triggers_payload.append(
            {
                "code": tr.code,
                "display_name": tr.display_name,
                "therapy_code": tr.primary_therapy.code if getattr(tr, "primary_therapy_id", None) and tr.primary_therapy else "",
                "cluster_code": tr.cluster.code if getattr(tr, "cluster_id", None) and tr.cluster else "",
                "doctor_trigger_label": tr.doctor_trigger_label or "",
            }
        )

    # -----------------------------------------------------------------
    # Trigger Clusters (kept for backwards compatibility; UI no longer uses it)
    # -----------------------------------------------------------------
    topics = list(TriggerCluster.objects.filter(is_active=True).order_by("display_name", "code"))
    topics_payload = [
        {
            "code": tc.code,
            "display_name": tc.display_name,
            "description": tc.description,
            "language_code": tc.language_code,
        }
        for tc in topics
    ]

    # -----------------------------------------------------------------
    # Bundles (VideoClusters) + localized names + included videos
    # -----------------------------------------------------------------
    bundles = list(
        VideoCluster.objects.filter(is_active=True)
        .select_related("trigger", "trigger__primary_therapy", "trigger__cluster")
        .order_by("display_name", "code")
    )

    bundle_names_by_code: Dict[str, Dict[str, str]] = defaultdict(dict)
    for row in (
        VideoClusterLanguage.objects.filter(video_cluster__in=bundles)
        .select_related("video_cluster")
        .all()
    ):
        bundle_names_by_code[row.video_cluster.code][row.language_code] = row.name

    bundle_trigger_code_by_code: Dict[str, str] = {}
    bundle_therapy_code_by_code: Dict[str, str] = {}
    bundle_display_names_by_code: Dict[str, str] = {}

    for b in bundles:
        bundle_display_names_by_code[b.code] = (b.display_name or "").strip() or b.code
        trig = getattr(b, "trigger", None)
        bundle_trigger_code_by_code[b.code] = trig.code if trig else ""
        ta_code = ""
        if trig and getattr(trig, "primary_therapy_id", None) and trig.primary_therapy:
            ta_code = trig.primary_therapy.code
        bundle_therapy_code_by_code[b.code] = ta_code

    # Bundle -> ordered list of video codes
    bundle_video_codes_by_code: Dict[str, List[str]] = defaultdict(list)
    vcv_rows = (
        VideoClusterVideo.objects.filter(video_cluster__in=bundles)
        .select_related("video_cluster", "video")
        .order_by("video_cluster_id", "sort_order", "video__code")
    )
    for row in vcv_rows:
        bundle_video_codes_by_code[row.video_cluster.code].append(row.video.code)

    # Bundle search text (for keyword search on the share page)
    bundle_search_text_by_code: Dict[str, str] = {}
    for b in bundles:
        parts: List[str] = []
        parts.extend(
            [
                b.code,
                (b.display_name or ""),
                (b.description or ""),
                (b.search_keywords or ""),
            ]
        )
        trig = getattr(b, "trigger", None)
        if trig:
            parts.extend(
                [
                    trig.code,
                    (trig.display_name or ""),
                    (trig.doctor_trigger_label or ""),
                    (trig.subtopic_title or ""),
                    (trig.search_keywords or ""),
                ]
            )
            if getattr(trig, "primary_therapy_id", None):
                ta = therapy_by_id.get(trig.primary_therapy_id)
                if ta:
                    parts.extend([ta.code, (ta.display_name or "")])
        for nm in bundle_names_by_code.get(b.code, {}).values():
            parts.append(nm or "")

        bundle_search_text_by_code[b.code] = " ".join(
            sorted(set((p or "").strip().lower() for p in parts if (p or "").strip()))
        )

    bundles_payload = []
    for b in bundles:
        code = b.code
        bundles_payload.append(
            {
                "code": code,
                "display_name": bundle_display_names_by_code.get(code, code),
                "names": bundle_names_by_code.get(code, {}),
                "trigger_code": bundle_trigger_code_by_code.get(code, ""),
                "therapy_code": bundle_therapy_code_by_code.get(code, ""),
                "video_codes": bundle_video_codes_by_code.get(code, []),
                "search_text": bundle_search_text_by_code.get(code, ""),
            }
        )

    # -----------------------------------------------------------------
    # Videos (+ localized titles + URLs + derived trigger/therapy codes from bundles)
    # -----------------------------------------------------------------
    videos = list(Video.objects.filter(is_active=True).order_by("code"))

    vlang_rows = VideoLanguage.objects.filter(video__in=videos).select_related("video")

    titles_by_video_code: Dict[str, Dict[str, str]] = defaultdict(dict)
    url_by_video_code: Dict[str, Dict[str, str]] = defaultdict(dict)

    for row in vlang_rows:
        titles_by_video_code[row.video.code][row.language_code] = row.title
        url_by_video_code[row.video.code][row.language_code] = row.youtube_url

    # Video -> bundle codes
    bundle_map: Dict[str, List[str]] = defaultdict(list)
    for row in vcv_rows:
        bundle_map[row.video.code].append(row.video_cluster.code)

    # Video -> derived trigger/therapy codes based on bundle membership
    trigger_codes_by_video: Dict[str, List[str]] = defaultdict(list)
    therapy_codes_by_video: Dict[str, List[str]] = defaultdict(list)

    for vcode, bcodes in bundle_map.items():
        for bcode in bcodes:
            tr_code = bundle_trigger_code_by_code.get(bcode) or ""
            th_code = bundle_therapy_code_by_code.get(bcode) or ""
            if tr_code:
                trigger_codes_by_video[vcode].append(tr_code)
            if th_code:
                therapy_codes_by_video[vcode].append(th_code)

    videos_payload = []
    for v in videos:
        code = v.code
        titles = dict(titles_by_video_code.get(code, {}))
        if "en" not in titles:
            titles["en"] = code

        display_label = titles.get("en") or code

        search_parts: List[str] = []
        search_parts.append(code)
        search_parts.extend([t.lower() for t in titles.values() if t])
        search_parts.extend(
            [
                (v.description or "").lower(),
                (v.search_keywords or "").lower(),
            ]
        )

        # Bundle-aware search terms
        for bcode in bundle_map.get(code, []):
            search_parts.append(bcode.lower())
            search_parts.append((bundle_display_names_by_code.get(bcode, "") or "").lower())
            for lang_name in bundle_names_by_code.get(bcode, {}).values():
                if lang_name:
                    search_parts.append(lang_name.lower())
            # Trigger / therapy labels via bundle
            tr_code = bundle_trigger_code_by_code.get(bcode) or ""
            th_code = bundle_therapy_code_by_code.get(bcode) or ""
            if tr_code:
                search_parts.append(tr_code.lower())

        videos_payload.append(
            {
                "id": code,
                "display_name": display_label,
                "titles": titles,
                "urls": url_by_video_code.get(code, {}),
                "trigger_codes": sorted(set(trigger_codes_by_video.get(code, []))),
                "therapy_codes": sorted(set(therapy_codes_by_video.get(code, []))),
                "bundle_codes": bundle_map.get(code, []),
                "search_text": " ".join(sorted(set(p for p in search_parts if p))),
            }
        )

    return {
        "therapy_areas": therapy_payload,
        "triggers": triggers_payload,
        "topics": topics_payload,  # legacy
        "bundles": bundles_payload,
        "videos": videos_payload,
        "message_prefixes": build_whatsapp_message_prefixes("your doctor"),
    }


def get_catalog_json_cached(force_refresh: bool = False) -> Dict[str, Any]:
    cache_seconds = getattr(settings, "CATALOG_CACHE_SECONDS", _CATALOG_CACHE_SECONDS)

    if not force_refresh:
        cached = cache.get(_CATALOG_CACHE_KEY)
        if cached:
            return cached

    payload = _build_catalog_payload()
    cache.set(_CATALOG_CACHE_KEY, payload, cache_seconds)
    return payload
