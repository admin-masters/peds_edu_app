from __future__ import annotations

import os

from django import forms
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm
from django.core.validators import RegexValidator

from .models import INDIA_STATE_CHOICES


class DoctorRegistrationForm(forms.Form):
    doctor_id = forms.CharField(
        label="Doctor ID",
        required=True,
        widget=forms.TextInput(attrs={"readonly": "readonly"}),
    )
    full_name = forms.CharField(label="Full Name", required=True, max_length=255)
    email = forms.EmailField(label="Email Address", required=True)
    whatsapp_number = forms.CharField(
        label="WhatsApp Number",
        required=True,
        validators=[RegexValidator(r"^\d{10}$", "Enter a 10-digit mobile number (without country code).")],
    )
    imc_number = forms.CharField(label="IMC Number", required=True, max_length=64)
    clinic_number = forms.CharField(
        label="Clinic Number",
        required=False,
        validators=[RegexValidator(r"^\d{6,15}$", "Enter a valid contact number (digits only).")],
    )
    address_text = forms.CharField(label="Address with postal code", required=True, widget=forms.Textarea)
    state = forms.ChoiceField(label="State", required=True, choices=INDIA_STATE_CHOICES)
    photo = forms.ImageField(label="Upload Photo", required=False)

    def clean_photo(self):
        f = self.cleaned_data.get("photo")
        if not f:
            return f
        ext = os.path.splitext(f.name)[1].lower()
        if ext not in {".jpg", ".jpeg", ".png", ".gif"}:
            raise forms.ValidationError("Please upload an image (JPG, JPEG, PNG, GIF).")
        # 5 MB limit (adjust as needed)
        if f.size and f.size > 5 * 1024 * 1024:
            raise forms.ValidationError("Image file is too large (max 5MB).")
        return f


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autofocus": True}))


class DoctorSetPasswordForm(SetPasswordForm):
    """For setting a new password (first-time setup or reset)."""

    new_password1 = forms.CharField(label="New password", widget=forms.PasswordInput)
    new_password2 = forms.CharField(label="Confirm new password", widget=forms.PasswordInput)
