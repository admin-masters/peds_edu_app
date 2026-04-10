from __future__ import annotations

from typing import Any
from urllib.parse import urlencode


HELP_CENTER_BASE_URL = "https://help.cpdinclinic.co.in"
SOURCE_SYSTEM = "Patient Education"

_SUPPORT_PAGES: dict[str, dict[str, str]] = {
    "doctor_credentials_email": {
        "user_type": "doctor",
        "role_title": "Doctor Support",
        "source_flow": "Flow1 / Doctor",
        "page_name": "Doctor Credentials Mail Page",
        "page_slug": "patient-education-flow1-doctor-doctor-credentials-mail-page",
        "context_label": "Patient Education / Access & Credentials",
    },
    "doctor_login": {
        "user_type": "doctor",
        "role_title": "Doctor Support",
        "source_flow": "Flow1 / Doctor",
        "page_name": "Doctor Login Page",
        "page_slug": "patient-education-flow1-doctor-doctor-login-page",
        "context_label": "Patient Education / Login & Account Access",
    },
    "doctor_clinic_sharing": {
        "user_type": "doctor",
        "role_title": "Doctor Support",
        "source_flow": "Flow1 / Doctor",
        "page_name": "Doctor / Clinic Sharing Page",
        "page_slug": "patient-education-flow1-doctor-doctor-clinic-sharing-page",
        "context_label": "Patient Education / Sharing Setup",
    },
    "patient_page": {
        "user_type": "patient",
        "role_title": "Patient Support",
        "source_flow": "Flow2 / Patient",
        "page_name": "Patient Page",
        "page_slug": "patient-education-flow2-patient-patient-page",
        "context_label": "Patient Education / Video Viewing",
    },
}

_ROUTE_TO_SUPPORT_PAGE = {
    "accounts:login": "doctor_login",
    "sharing:doctor_share": "doctor_clinic_sharing",
    "sharing:patient_video": "patient_page",
    "sharing:patient_cluster": "patient_page",
}


def _build_support_urls(*, user_type: str, page_slug: str, source_flow: str) -> dict[str, str]:
    query = urlencode({"system": SOURCE_SYSTEM, "flow": source_flow})
    page_path = f"/support/{user_type}/faq/page/{page_slug}/"
    widget_path = f"{page_path}widget/"
    api_path = f"/support/api/{user_type}/pages/{page_slug}/"

    return {
        "page_url": f"{HELP_CENTER_BASE_URL}{page_path}?{query}",
        "widget_url": f"{HELP_CENTER_BASE_URL}{widget_path}?{query}",
        "embed_url": f"{HELP_CENTER_BASE_URL}{widget_path}?{query}&embed=1",
        "api_url": f"{HELP_CENTER_BASE_URL}{api_path}?{query}",
    }


def get_support_page(page_key: str) -> dict[str, Any] | None:
    page = _SUPPORT_PAGES.get(page_key)
    if not page:
        return None

    config = dict(page)
    config["page_key"] = page_key
    config["launcher_label"] = "Support"
    config["iframe_title"] = f'{config["page_name"]} support'
    config.update(
        _build_support_urls(
            user_type=config["user_type"],
            page_slug=config["page_slug"],
            source_flow=config["source_flow"],
        )
    )
    return config


def get_support_widget_for_request(request) -> dict[str, Any] | None:
    resolver_match = getattr(request, "resolver_match", None)
    view_name = getattr(resolver_match, "view_name", "")
    page_key = _ROUTE_TO_SUPPORT_PAGE.get(view_name)
    if not page_key:
        return None
    return get_support_page(page_key)
