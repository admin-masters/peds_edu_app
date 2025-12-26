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
    VideoLanguage,
    VideoCluster,
    VideoClusterLanguage,
    VideoClusterVideo,
)


_CATALOG_CACHE_KEY = "clinic_catalog_payload_v6"
_CATALOG_CACHE_SECONDS = 60 * 60  # 1 hour


def build_whatsapp_message_prefixes(doctor_name: str) -> Dict[str, str]:
    """
    Generates WhatsApp prefix strings for each supported language.
    Final message is: prefix + patient_link
    """
    doctor = doctor_name.strip() or "your doctor"

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
        "gu": (
            "તમારા ડોક્ટર {doctor} એ તમને નીચેના વિડિયો/વિડિયો મોકલ્યા છે. "
            "કૃપા કરીને તેને ધ્યાનથી જુઓ અને વિડિયોમાં આપેલા સૂચનોનું પાલન કરો, "
            "કારણ કે આ તમારા ડોક્ટરના મહત્વના નિરીક્ષણો માટે છે. "
            "તમારા બાળકનું સ્વાસ્થ્ય અને કલ્યાણ વિડિયોમાં આપેલા સૂચનોનું પાલન કરવા પર આધાર રાખે છે. "
        ),
        "mr": (
            "तुमचे डॉक्टर {doctor} यांनी तुम्हाला खालील व्हिडिओ/व्हिडिओ पाठवले आहेत. "
            "कृपया ते काळजीपूर्वक पहा आणि व्हिडिओमध्ये दिलेल्या सूचनांचे पालन करा, "
            "कारण हे तुमच्या डॉक्टरांच्या महत्त्वाच्या निरीक्षणांसाठी आहेत. "
            "तुमच्या मुलाचे आरोग्य आणि कल्याण व्हिडिओमधील सूचनांचे पालन करण्यावर अवलंबून आहे. "
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
            "আপনার সন্তানের স্বাস্থ্য ও কল্যাণ ভিডিওতে দেওয়া নির্দেশনা অনুসরণ করার উপর নির্ভর করে। "
        ),
        "te": (
            "మీ డాక్టర్ {doctor} మీకు క్రింది వీడియో/వీడియోలను పంపించారు. "
            "దయచేసి వాటిని జాగ్రత్తగా చూడండి మరియు వీడియోలో ఇచ్చిన సూచనలను అనుసరించండి, "
            "ఎందుకంటే ఇవి మీ డాక్టర్ యొక్క ముఖ్యమైన పరిశీలనల కోసం. "
            "మీ పిల్లల ఆరోగ్యం మరియు శ్రేయస్సు వీడియోల్లో ఉన్న సూచనలను అనుసరించడంపై ఆధారపడి ఉంటుంది. "
        ),
    }

    out: Dict[str, str] = {}
    for lang, tmpl in templates.items():
        out[lang] = tmpl.format(doctor=doctor)
    return out


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
        therapy = getattr(trigger, "primary_therapy", None)
        topic = getattr(trigger, "cluster", None)

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
        .select_related("primary_therapy", "primary_trigger", "primary_trigger__cluster")
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

        bundle_name_tokens: List[str] = []
        for bc in bundle_codes:
            names = bundle_names_by_code.get(bc, {})
            bundle_name_tokens.append(bc)
            bundle_name_tokens.extend([n for n in names.values() if n])

        search_parts: List[str] = []
        search_parts.extend([t for t in titles.values() if t])
        search_parts.append(v.code)
        search_parts.append(v.description or "")

        if trigger:
            search_parts.extend(
                [
                    trigger.code or "",
                    trigger.display_name or "",
                    getattr(trigger, "doctor_trigger_label", "") or "",
                    getattr(trigger, "subtopic_title", "") or "",
                    getattr(trigger, "search_keywords", "") or "",
                    getattr(trigger, "navigation_pathways", "") or "",
                ]
            )

        if therapy:
            search_parts.extend(
                [
                    therapy.code or "",
                    therapy.display_name or "",
                    therapy.description or "",
                ]
            )

        if topic:
            search_parts.extend(
                [
                    topic.code or "",
                    topic.display_name or "",
                    getattr(topic, "description", "") or "",
                ]
            )

        # Bundle codes + names across languages
        search_parts.extend(bundle_name_tokens)

        search_text = " ".join([p for p in search_parts if p]).lower()

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
        "message_prefixes": build_whatsapp_message_prefixes("your doctor"),
    }


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
