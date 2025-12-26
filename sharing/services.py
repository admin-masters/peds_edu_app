# sharing/services.py
from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Optional

from django.conf import settings
from django.core.cache import cache

from catalog.models import (
    TherapyArea,
    Trigger,
    TriggerCluster,
    Video,
    VideoCluster,
    VideoClusterLanguage,
    VideoClusterVideo,
)

# Bump cache key to invalidate old payload
_CATALOG_CACHE_KEY = "clinic_catalog_payload_v6"
_CATALOG_CACHE_SECONDS = 15 * 60  # 15 min


def _safe_str(v: Any) -> str:
    return "" if v is None else str(v)


# ---------------------------------------------------------------------
# WhatsApp message prefixes (NO caching of doctor-specific text)
# ---------------------------------------------------------------------
def build_whatsapp_message_prefixes(
    doctor_name: Optional[str] = None,
) -> Dict[str, str]:
    doctor = (doctor_name or "").strip()
    dn_en = doctor if doctor else "your doctor"
    dn_local = doctor if doctor else ""

    templates = {
        "en": (
            "Your doctor {doctor} has sent you the following video/videos. "
            "It is very important that you view them and follow the instructions, "
            "as these are for important observations by your doctor. "
            "Your child's health and wellbeing depend upon following the instructions in the videos. "
        ),
        "hi": (
            "आपके डॉक्टर {doctor} ने आपको निम्न वीडियो/वीडियो भेजे हैं। "
            "कृपया इन्हें ध्यान से देखें और वीडियो में दिए गए निर्देशों का पालन करें, "
            "क्योंकि ये आपके डॉक्टर के महत्वपूर्ण निरीक्षणों के लिए हैं। "
            "आपके बच्चे का स्वास्थ्य और भलाई इन वीडियो में दिए गए निर्देशों का पालन करने पर निर्भर है। "
        ),
        "te": (
            "మీ డాక్టర్ {doctor} మీకు క్రింది వీడియో/వీడియోలను పంపించారు. "
            "దయచేసి వాటిని జాగ్రత్తగా వీక్షించి, వీడియోలలో ఇచ్చిన సూచనలను అనుసరించండి, "
            "ఎందుకంటే ఇవి మీ డాక్టర్ చేసిన ముఖ్యమైన పరిశీలనల కోసం. "
            "మీ పిల్లల ఆరోగ్యం మరియు శ్రేయస్సు ఈ వీడియోల సూచనలను అనుసరించడంపై ఆధారపడి ఉంటుంది. "
        ),
        "ml": (
            "നിങ്ങളുടെ ഡോക്ടർ {doctor} നിങ്ങള്‍ക്കായി താഴെ പറയുന്ന വീഡിയോ/വീഡിയോകള്‍ അയച്ചിട്ടുണ്ട്. "
            "ദയവായി അവ ശ്രദ്ധാപൂർവ്വം കാണുകയും വീഡിയോയിലെ നിർദ്ദേശങ്ങൾ പാലിക്കുകയും ചെയ്യുക, "
            "കാരണം ഇവ നിങ്ങളുടെ ഡോക്ടറുടെ പ്രധാനപ്പെട്ട നിരീക്ഷണങ്ങൾക്കായാണ്. "
            "നിങ്ങളുടെ കുട്ടിയുടെ ആരോഗ്യവും ക്ഷേമവും വീഡിയോയിലെ നിർദ്ദേശങ്ങൾ പാലിക്കുന്നതിനെ ആശ്രയിച്ചിരിക്കുന്നു. "
        ),
        "mr": (
            "आपल्या डॉक्टर {doctor} यांनी आपल्याला खालील व्हिडिओ/व्हिडिओ पाठवले आहेत. "
            "कृपया ते काळजीपूर्वक पाहा आणि व्हिडिओमध्ये दिलेल्या सूचनांचे पालन करा, "
            "कारण हे आपल्या डॉक्टरांच्या महत्त्वाच्या निरीक्षणांसाठी आहेत. "
            "आपल्या मुलाचे आरोग्य आणि कल्याण हे व्हिडिओमधील सूचनांचे पालन करण्यावर अवलंबून आहे. "
        ),
        "kn": (
            "ನಿಮ್ಮ ವೈದ್ಯರು {doctor} ಅವರು ನಿಮಗೆ ಕೆಳಗಿನ ವೀಡಿಯೊ/ವೀಡಿಯೊಗಳನ್ನು ಕಳುಹಿಸಿದ್ದಾರೆ. "
            "ದಯವಿಟ್ಟು ಅವನ್ನು ಗಮನದಿಂದ ನೋಡಿ ಹಾಗೂ ವೀಡಿಯೊಗಳಲ್ಲಿ ನೀಡಿರುವ ಸೂಚನೆಗಳನ್ನು ಅನುಸರಿಸಿ, "
            "ಏಕೆಂದರೆ ಇವು ನಿಮ್ಮ ವೈದ್ಯರ ಮಹತ್ವದ ಗಮನಿಸಿಕೆಗಳಿಗಾಗಿ. "
            "ನಿಮ್ಮ ಮಗುವಿನ ಆರೋಗ್ಯ ಮತ್ತು ಕಲ್ಯಾಣವು ವೀಡಿಯೊಗಳ ಸೂಚನೆಗಳನ್ನು ಪಾಲಿಸುವುದರ ಮೇಲೆ ಅವಲಂಬಿತವಾಗಿದೆ. "
        ),
        "ta": (
            "உங்கள் மருத்துவர் {doctor} உங்களுக்கு கீழ்க்கண்ட வீடியோ/வீடியோக்களை அனுப்பியுள்ளார். "
            "தயவுசெய்து அவற்றை கவனமாகப் பார்த்து, வீடியோவில் கொடுக்கப்பட்ட வழிமுறைகளைப் பின்பற்றுங்கள், "
            "ஏனெனில் இவை உங்கள் மருத்துவரின் முக்கியமான கண்காணிப்புகளுக்கானவை. "
            "உங்கள் குழந்தையின் ஆரோக்கியமும் நலனும் இந்த வீடியோக்களில் உள்ள வழிமுறைகளைப் பின்பற்றுவதில் சார்ந்துள்ளது. "
        ),
        "bn": (
            "আপনার ডাক্তার {doctor} আপনাকে নিম্নলিখিত ভিডিও/ভিডিওগুলো পাঠিয়েছেন। "
            "অনুগ্রহ করে সেগুলো মনোযোগ দিয়ে দেখুন এবং ভিডিওতে দেওয়া নির্দেশনা অনুসরণ করুন, "
            "কারণ এগুলো আপনার ডাক্তারের গুরুত্বপূর্ণ পর্যবেক্ষণের জন্য। "
            "আপনার শিশুর স্বাস্থ্য ও সুস্থতা ভিডিওগুলোর নির্দেশনা অনুসরণের উপর নির্ভর করে। "
        ),
    }

    out: Dict[str, str] = {}
    for code, _label in getattr(settings, "LANGUAGES", [("en", "English")]):
        tmpl = templates.get(code, templates["en"])
        if code == "en":
            out[code] = tmpl.format(doctor=dn_en)
        else:
            if dn_local:
                out[code] = tmpl.format(doctor=dn_local)
            else:
                out[code] = (
                    tmpl.replace("{doctor} ", "")
                    .replace("{doctor}", "")
                    .strip()
                    + " "
                )
    return out


# ---------------------------------------------------------------------
# Catalog payload builder
# ---------------------------------------------------------------------
def _build_catalog_payload() -> Dict[str, Any]:
    # -----------------------------------------------------------------
    # Therapy Areas
    # -----------------------------------------------------------------
    therapy_areas = list(
        TherapyArea.objects.filter(is_active=True).order_by("sort_order", "id")
    )
    therapy_payload = [
        {
            "code": ta.code,
            "display_name": ta.display_name,
            "description": ta.description,
        }
        for ta in therapy_areas
    ]
    therapy_by_id = {ta.id: ta for ta in therapy_areas}

    # -----------------------------------------------------------------
    # Topics (TriggerClusters)
    # -----------------------------------------------------------------
    topic_qs = TriggerCluster.objects.filter(is_active=True).order_by("sort_order", "id")
    topics = list(topic_qs)
    topics_payload = [
        {
            "code": tc.code,
            "display_name": tc.display_name,
            "description": tc.description,
            "language_code": tc.language_code,
        }
        for tc in topics
    ]
    topic_by_id = {tc.id: tc for tc in topics}

    # -----------------------------------------------------------------
    # Bundles (VideoClusters)
    # -----------------------------------------------------------------
    bundles = list(
        VideoCluster.objects.filter(is_active=True)
        .select_related("trigger")
        .order_by("sort_order", "id")
    )

    bundle_names_by_code: Dict[str, Dict[str, str]] = defaultdict(dict)
    for bl in VideoClusterLanguage.objects.select_related("video_cluster"):
        bundle_names_by_code[bl.video_cluster.code][bl.language_code] = bl.name

    bundles_payload = []
    for b in bundles:
        trigger = b.trigger
        therapy = trigger.primary_therapy
        topic = trigger.cluster

        bundles_payload.append(
            {
                "code": b.code,
                "display_name": b.display_name,
                "names": bundle_names_by_code.get(b.code, {}),
                "trigger_code": trigger.code,
                "trigger_name": trigger.display_name,
                "therapy_code": therapy.code if therapy else "",
                "topic_code": topic.code if topic else "",
                "is_published": b.is_published,
            }
        )

    # -----------------------------------------------------------------
    # Videos
    # -----------------------------------------------------------------
    videos = list(
        Video.objects.filter(is_active=True)
        .select_related("primary_therapy", "primary_trigger")
        .prefetch_related("languages")
        .order_by("sort_order", "id")
    )

    video_to_bundle_codes: Dict[int, List[str]] = defaultdict(list)
    for row in VideoClusterVideo.objects.select_related("video_cluster").order_by(
        "sort_order", "id"
    ):
        video_to_bundle_codes[row.video_id].append(row.video_cluster.code)

    videos_payload: List[Dict[str, Any]] = []

    for v in videos:
        titles: Dict[str, str] = {}
        urls: Dict[str, str] = {}

        for lang in v.languages.all():
            lc = lang.language_code or "en"
            titles[lc] = lang.title
            urls[lc] = lang.youtube_url

        bundle_codes = video_to_bundle_codes.get(v.id, [])

        trigger = v.primary_trigger
        therapy = v.primary_therapy
        topic = trigger.cluster if trigger else None

        trigger_names = [trigger.display_name] if trigger else []

        search_text = " ".join(
            [
                *titles.values(),
                v.code,
                *(bundle_codes),
                *(trigger_names),
                therapy.code if therapy else "",
                topic.code if topic else "",
            ]
        ).lower()

        videos_payload.append(
            {
                "id": v.code,
                "titles": titles,
                "urls": urls,  # UI only; WhatsApp templates do NOT embed URLs
                "bundle_codes": bundle_codes,
                "trigger_names": trigger_names,
                "therapy_codes": [therapy.code] if therapy else [],
                "topic_codes": [topic.code] if topic else [],
                "search_text": search_text,
            }
        )

    return {
        "bundles": bundles_payload,
        "therapy_areas": therapy_payload,
        "topics": topics_payload,
        "videos": videos_payload,
        "message_prefixes": build_whatsapp_message_prefixes(),
    }


# ---------------------------------------------------------------------
# Cached accessor
# ---------------------------------------------------------------------
def get_catalog_json_cached(force_refresh: bool = False) -> Dict[str, Any]:
    if not force_refresh:
        cached = cache.get(_CATALOG_CACHE_KEY)
        if isinstance(cached, dict):
            return cached
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
