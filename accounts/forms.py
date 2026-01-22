from __future__ import annotations


from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.core.validators import RegexValidator

import re
from django import forms
from django.core.validators import RegexValidator

# Keep the existing RegexValidator import if already present above; otherwise add it.

_digits_only = RegexValidator(r"^\d+$", "Digits only.")
_pin_6 = RegexValidator(r"^\d{6}$", "PIN must be 6 digits.")
_phone_like = RegexValidator(r"^\d{8,15}$", "Enter a valid phone number (digits only).")


class DoctorRegistrationForm(forms.Form):
    # passed in URL (and persisted via hidden fields)
    campaign_id = forms.CharField(required=False, widget=forms.HiddenInput())
    field_rep_id = forms.CharField(required=False, widget=forms.HiddenInput())

    first_name = forms.CharField(label="First Name", max_length=150, required=True)
    last_name = forms.CharField(label="Last name", max_length=150, required=True)
    email = forms.EmailField(label="Email", required=True)

    clinic_name = forms.CharField(label="Clinic name", max_length=255, required=True)

    imc_registration_number = forms.CharField(
        label="Doctor’s IMC Registration Number",
        max_length=30,
        required=True,
        validators=[_digits_only],
    )

    clinic_appointment_number = forms.CharField(
        label="Clinic Appointment Booking Number (phone)",
        max_length=20,
        required=True,
        validators=[_phone_like],
    )

    clinic_address = forms.CharField(
        label="Clinic Address (full address)",
        required=True,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    postal_code = forms.CharField(
        label="Postal Code (PIN – 6 digits)",
        max_length=6,
        required=True,
        validators=[_pin_6],
    )

    clinic_whatsapp_number = forms.CharField(
        label="Clinic WhatsApp Number",
        max_length=20,
        required=True,
        validators=[_phone_like],
    )

    photo = forms.ImageField(label="Doctor’s Photo (JPEG/JPG/PNG upload)", required=True)

    def save_to_master_db(
        self,
        *,
        doctor_id: str,
        state: str,
        district: str,
        photo_path: str,
        recruited_via: str,
    ) -> None:
        """
        Inserts into MASTER DB:
          1) Doctor
          2) DoctorCampaignEnrollment
        """
        if not self.is_valid():
            raise ValueError("Form must be valid before calling save_to_master_db().")

        from . import master_db  # local import
        from django.db import IntegrityError

        cd = self.cleaned_data

        campaign_id = (cd.get("campaign_id") or "").strip()
        field_rep_id = (cd.get("field_rep_id") or "").strip()

        master_db.insert_doctor_row(
            doctor_id=doctor_id,
            first_name=cd["first_name"].strip(),
            last_name=cd["last_name"].strip(),
            email=cd["email"].strip().lower(),
            clinic_name=cd["clinic_name"].strip(),
            imc_registration_number=cd["imc_registration_number"].strip(),
            clinic_phone=cd["clinic_appointment_number"].strip(),
            clinic_appointment_number=cd["clinic_appointment_number"].strip(),
            clinic_address=cd["clinic_address"].strip(),
            postal_code=cd["postal_code"].strip(),
            state=state or "",
            district=district or "",
            whatsapp_no=cd["clinic_whatsapp_number"].strip(),
            receptionist_whatsapp_number=cd["clinic_whatsapp_number"].strip(),
            photo_path=photo_path or "",
            field_rep_id=field_rep_id,
            recruited_via=recruited_via,
        )

        # Enrollment insert (only if campaign_id present)
        if campaign_id:
            try:
                master_db.ensure_enrollment(
                    doctor_id=doctor_id,
                    campaign_id=campaign_id,
                    registered_by=field_rep_id,
                )
            except IntegrityError:
                # ignore duplicates
                pass
