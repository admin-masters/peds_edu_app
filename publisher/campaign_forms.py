from __future__ import annotations

import json
from typing import Any, Dict, List

from django import forms
from django.core.exceptions import ValidationError


class FieldRepWhatsAppForm(forms.Form):
    whatsapp_number = forms.CharField(
        label="Enter doctor’s WhatsApp number",
        max_length=20,
        required=True,
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. 9876543210",
                "inputmode": "numeric",
            }
        ),
    )


class CampaignCreateForm(forms.Form):
    # Master campaign id (UUID)
    campaign_id = forms.CharField(widget=forms.HiddenInput())

    # Editable in Project2
    new_video_cluster_name = forms.CharField(
        max_length=255,
        label="New video-cluster name",
    )

    # Hidden JSON payload: [{"type":"video","id":1}, {"type":"cluster","id":2}]
    selected_items_json = forms.CharField(
        widget=forms.HiddenInput(),
        required=True,
    )

    # Campaign messaging (editable here)
    email_registration = forms.CharField(
        label="Email message for registering a new doctor",
        widget=forms.Textarea(attrs={"rows": 4}),
        required=True,
    )

    wa_addition = forms.CharField(
        label="WhatsApp message for adding an already registered doctor",
        widget=forms.Textarea(attrs={"rows": 4}),
        required=True,
    )

    start_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="Start date",
    )
    end_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date"}),
        label="End date",
    )

    def clean_selected_items_json(self) -> str:
        raw = (self.cleaned_data.get("selected_items_json") or "").strip()
        if not raw:
            raise ValidationError("Please select at least one video or video-cluster.")

        try:
            data = json.loads(raw)
        except Exception:
            raise ValidationError("Invalid selection payload.")

        if not isinstance(data, list) or not data:
            raise ValidationError("Please select at least one video or video-cluster.")

        cleaned: List[Dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue

            t = str(item.get("type") or "").strip().lower()
            if t not in ("video", "cluster"):
                continue

            try:
                i = int(item.get("id"))
            except Exception:
                continue

            cleaned.append({"type": t, "id": i})

        if not cleaned:
            raise ValidationError("Please select at least one valid video or video-cluster.")

        return json.dumps(cleaned)

    def clean(self):
        cleaned = super().clean()

        # Normalize name
        name = (cleaned.get("new_video_cluster_name") or "").strip()
        if name:
            cleaned["new_video_cluster_name"] = name

        # Date sanity
        sd = cleaned.get("start_date")
        ed = cleaned.get("end_date")
        if sd and ed and sd > ed:
            self.add_error("end_date", "End date must be on or after start date.")

        # Strip message bodies
        if "email_registration" in cleaned:
            cleaned["email_registration"] = (cleaned.get("email_registration") or "").strip()
        if "wa_addition" in cleaned:
            cleaned["wa_addition"] = (cleaned.get("wa_addition") or "").strip()

        return cleaned


class CampaignEditForm(CampaignCreateForm):
    """Same fields as create.

    IMPORTANT:
    - Banners (small/large + target URL) and num_doctors_supported are sourced from the MASTER DB.
    - Therefore they are intentionally NOT editable in this Project2 add/edit screen.
    """

    pass
