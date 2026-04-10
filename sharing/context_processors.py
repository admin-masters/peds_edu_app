from __future__ import annotations

from typing import Any

from .support_widget import get_support_widget_for_request


def clinic_branding(request) -> dict[str, Any]:
    """Inject clinic branding plus any page-level support widget config."""

    context: dict[str, Any] = {}
    support_widget = get_support_widget_for_request(request)
    if support_widget:
        context["support_widget"] = support_widget

    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return context

    doctor = getattr(user, "doctor_profile", None)
    if not doctor:
        return context

    clinic = doctor.clinic
    context.update(
        {
            "brand_doctor_name": user.full_name,
            "brand_clinic_name": clinic.display_name or f"Dr. {user.full_name}",
            "brand_clinic_code": clinic.clinic_code,
            "brand_doctor_id": doctor.doctor_id,
            "brand_photo_url": doctor.photo.url if doctor.photo else "",
        }
    )
    return context
