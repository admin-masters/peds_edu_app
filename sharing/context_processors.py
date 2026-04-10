from __future__ import annotations

from typing import Dict


def clinic_branding(request) -> Dict[str, str]:
    """Inject logged-in clinic branding into templates."""

    user = getattr(request, "user", None)
    if not user or not getattr(user, "is_authenticated", False):
        return {}

    doctor = getattr(user, "doctor_profile", None)
    if not doctor:
        return {}

    clinic = doctor.clinic
    return {
        "brand_doctor_name": user.full_name,
        "brand_clinic_name": clinic.display_name or f"Dr. {user.full_name}",
        "brand_clinic_code": clinic.clinic_code,
        "brand_doctor_id": doctor.doctor_id,
        "brand_photo_url": doctor.photo.url if doctor.photo else "",
    }
