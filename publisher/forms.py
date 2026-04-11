from __future__ import annotations

from typing import Optional

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db.models import Q
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet

from catalog.constants import LANGUAGE_CODES
from catalog.models import (
    TherapyArea,
    Video,
    VideoCluster,
    VideoClusterLanguage,
    VideoClusterVideo,
    VideoLanguage,
    VideoTriggerMap,
    Trigger,
    TriggerCluster,
)


class TherapyAreaForm(forms.ModelForm):
    class Meta:
        model = TherapyArea
        fields = ["code", "display_name", "description", "is_active"]


class VideoClusterForm(forms.ModelForm):
    class Meta:
        model = VideoCluster
        fields = ["code", "display_name", "description", "trigger", "is_published", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "trigger" in self.fields:
            self.fields["trigger"].queryset = Trigger.objects.all().order_by("display_name", "code")


class VideoForm(forms.ModelForm):
    clusters = forms.ModelMultipleChoiceField(
        queryset=VideoCluster.objects.none(),
        required=True,
        widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text="Select at least 1 bundle/cluster. A video cannot exist standalone.",
    )

    class Meta:
        model = Video
        fields = ["code", "thumbnail_url", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            existing_ids = list(self.instance.clusters.values_list("pk", flat=True))
            qs = (
                VideoCluster.objects.filter(Q(is_active=True) | Q(pk__in=existing_ids))
                .order_by("display_name", "code")
            )
            self.fields["clusters"].initial = list(self.instance.clusters.all())
        else:
            qs = VideoCluster.objects.filter(is_active=True).order_by("display_name", "code")

        self.fields["clusters"].queryset = qs


class VideoLanguageForm(forms.ModelForm):
    class Meta:
        model = VideoLanguage
        fields = ["language_code", "title", "youtube_url"]


class BaseVideoLanguageFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()

        seen = set()
        missing = set(LANGUAGE_CODES)

        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue

            code = form.cleaned_data.get("language_code")
            title = (form.cleaned_data.get("title") or "").strip()
            url = (form.cleaned_data.get("youtube_url") or "").strip()

            if not code:
                continue

            if code in seen:
                raise ValidationError("Duplicate language detected. Each language must be entered exactly once.")

            seen.add(code)
            missing.discard(code)

            if not title or not url:
                raise ValidationError("Please provide both Title and YouTube URL for every language.")

        if missing:
            raise ValidationError("Please provide Title and YouTube URL for all languages: " + ", ".join(sorted(missing)))


def make_video_language_formset(extra: int = 0):
    return inlineformset_factory(
        Video,
        VideoLanguage,
        form=VideoLanguageForm,
        formset=BaseVideoLanguageFormSet,
        fields=["language_code", "title", "youtube_url"],
        extra=extra,
        can_delete=False,
    )


class VideoClusterLanguageForm(forms.ModelForm):
    class Meta:
        model = VideoClusterLanguage
        fields = ["language_code", "name"]


class VideoClusterVideoForm(forms.ModelForm):
    sort_order = forms.IntegerField(required=False)

    class Meta:
        model = VideoClusterVideo
        fields = ["video", "sort_order"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "video" in self.fields:
            self.fields["video"].queryset = Video.objects.all().order_by("code")
            # Enable JS-based type-to-filter by adding a stable CSS hook.
            self.fields["video"].widget.attrs.update({"class": "video-select"})


def make_cluster_language_formset(extra: int = 5):
    return inlineformset_factory(
        VideoCluster,
        VideoClusterLanguage,
        form=VideoClusterLanguageForm,
        fields=["language_code", "name"],
        extra=extra,
        can_delete=True,
    )


def make_cluster_video_formset(extra: int = 5):
    return inlineformset_factory(
        VideoCluster,
        VideoClusterVideo,
        form=VideoClusterVideoForm,
        fields=["video", "sort_order"],
        extra=extra,
        can_delete=True,
    )


class TriggerForm(forms.ModelForm):
    class Meta:
        model = Trigger
        fields = ["code", "display_name", "cluster", "primary_therapy", "doctor_trigger_label", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if "cluster" in self.fields:
            self.fields["cluster"].queryset = TriggerCluster.objects.all().order_by("display_name", "code")
        if "primary_therapy" in self.fields:
            self.fields["primary_therapy"].queryset = TherapyArea.objects.all().order_by("display_name", "code")


class TriggerClusterForm(forms.ModelForm):
    class Meta:
        model = TriggerCluster
        fields = ["code", "display_name", "description", "is_active"]


class BundleTriggerMapForm(forms.Form):
    bundle = forms.ModelChoiceField(queryset=VideoCluster.objects.none(), required=True)
    trigger = forms.ModelChoiceField(queryset=Trigger.objects.none(), required=True)

    def __init__(self, *args, bundle_instance: Optional[VideoCluster] = None, **kwargs):
        super().__init__(*args, **kwargs)

        self.bundle_instance = bundle_instance

        if bundle_instance and bundle_instance.pk:
            bqs = VideoCluster.objects.filter(Q(is_active=True) | Q(pk=bundle_instance.pk)).order_by("display_name", "code")
        else:
            bqs = VideoCluster.objects.filter(is_active=True).order_by("display_name", "code")

        if bundle_instance and getattr(bundle_instance, "trigger_id", None):
            tqs = Trigger.objects.filter(Q(is_active=True) | Q(pk=bundle_instance.trigger_id)).order_by("display_name", "code")
        else:
            tqs = Trigger.objects.filter(is_active=True).order_by("display_name", "code")

        self.fields["bundle"].queryset = bqs
        self.fields["trigger"].queryset = tqs

        if bundle_instance and bundle_instance.pk:
            self.fields["bundle"].initial = bundle_instance
            self.fields["bundle"].disabled = True
            if getattr(bundle_instance, "trigger_id", None):
                self.fields["trigger"].initial = bundle_instance.trigger_id

    def clean_bundle(self):
        if self.bundle_instance and self.bundle_instance.pk:
            return self.bundle_instance
        return self.cleaned_data["bundle"]


class VideoTriggerMapForm(forms.ModelForm):
    sort_order = forms.IntegerField(required=False)

    class Meta:
        model = VideoTriggerMap
        fields = ["trigger", "video", "is_primary", "sort_order"]


_digits_or_blank = RegexValidator(r"^\d*$", "Digits only.")
_postal_code_validator = RegexValidator(r"^(\d{6})?$", "PIN must be 6 digits.")


class FieldRepRecordForm(forms.Form):
    full_name = forms.CharField(max_length=255, required=True, label="Full name")
    phone_number = forms.CharField(max_length=30, required=True, label="Phone number")
    brand_supplied_field_rep_id = forms.CharField(
        max_length=80,
        required=True,
        label="Brand field rep ID",
    )
    state = forms.CharField(max_length=255, required=False, label="State")
    is_active = forms.BooleanField(required=False, label="Active")

    def clean(self):
        cleaned = super().clean()
        for key in ("full_name", "phone_number", "brand_supplied_field_rep_id", "state"):
            if key in cleaned:
                cleaned[key] = (cleaned.get(key) or "").strip()
        return cleaned


class DoctorRecordForm(forms.Form):
    first_name = forms.CharField(max_length=100, required=True, label="First name")
    last_name = forms.CharField(max_length=100, required=False, label="Last name")
    email = forms.EmailField(required=True, label="Email")
    whatsapp_no = forms.CharField(
        max_length=20,
        required=False,
        label="Doctor WhatsApp",
        validators=[_digits_or_blank],
    )
    clinic_name = forms.CharField(max_length=255, required=True, label="Clinic name")
    clinic_phone = forms.CharField(
        max_length=20,
        required=False,
        label="Clinic phone",
        validators=[_digits_or_blank],
    )
    clinic_appointment_number = forms.CharField(
        max_length=20,
        required=False,
        label="Appointment phone",
        validators=[_digits_or_blank],
    )
    clinic_address = forms.CharField(
        required=False,
        label="Clinic address",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    postal_code = forms.CharField(
        max_length=6,
        required=False,
        label="Postal code",
        validators=[_postal_code_validator],
    )
    state = forms.CharField(max_length=64, required=False, label="State")
    district = forms.CharField(max_length=100, required=False, label="District")
    receptionist_whatsapp_number = forms.CharField(
        max_length=20,
        required=False,
        label="Clinic WhatsApp",
        validators=[_digits_or_blank],
    )
    imc_registration_number = forms.CharField(
        max_length=30,
        required=False,
        label="IMC registration number",
        validators=[_digits_or_blank],
    )
    field_rep_id = forms.CharField(max_length=64, required=False, label="Field rep ID")
    recruited_via = forms.CharField(max_length=20, required=False, label="Recruited via")
    clinic_user1_name = forms.CharField(max_length=120, required=False, label="Clinic user 1 name")
    clinic_user1_email = forms.EmailField(required=False, label="Clinic user 1 email")
    clinic_user2_name = forms.CharField(max_length=120, required=False, label="Clinic user 2 name")
    clinic_user2_email = forms.EmailField(required=False, label="Clinic user 2 email")

    def clean(self):
        cleaned = super().clean()
        for key in (
            "first_name",
            "last_name",
            "clinic_name",
            "clinic_phone",
            "clinic_appointment_number",
            "clinic_address",
            "postal_code",
            "state",
            "district",
            "receptionist_whatsapp_number",
            "imc_registration_number",
            "field_rep_id",
            "recruited_via",
            "clinic_user1_name",
            "clinic_user2_name",
        ):
            if key in cleaned:
                cleaned[key] = (cleaned.get(key) or "").strip()

        for key in ("email", "clinic_user1_email", "clinic_user2_email"):
            if key in cleaned:
                cleaned[key] = (cleaned.get(key) or "").strip().lower()

        return cleaned


class PERecordsLoginForm(forms.Form):
    email = forms.EmailField(label="Email")
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
        strip=False,
    )

    def clean(self):
        cleaned = super().clean()
        if "email" in cleaned:
            cleaned["email"] = (cleaned.get("email") or "").strip().lower()
        return cleaned


class MasterCampaignRecordForm(forms.Form):
    name = forms.CharField(max_length=255, required=True, label="Campaign name")
    num_doctors_supported = forms.IntegerField(
        min_value=0,
        required=True,
        label="Doctors supported",
    )
    add_to_campaign_message = forms.CharField(
        required=True,
        label="Add-to-campaign WhatsApp message",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    register_message = forms.CharField(
        required=True,
        label="Registration message",
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    banner_small_url = forms.URLField(
        max_length=500,
        required=False,
        label="Small banner URL",
    )
    banner_large_url = forms.URLField(
        max_length=500,
        required=False,
        label="Large banner URL",
    )
    banner_target_url = forms.URLField(
        max_length=500,
        required=False,
        label="Banner target URL",
    )
    brand_id = forms.IntegerField(
        min_value=1,
        required=False,
        label="Brand ID",
    )
    system_pe = forms.BooleanField(
        required=False,
        label="Mark as PE campaign",
    )
    start_date = forms.DateField(
        required=True,
        label="Start date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    def clean(self):
        cleaned = super().clean()
        for key in (
            "name",
            "add_to_campaign_message",
            "register_message",
            "banner_small_url",
            "banner_large_url",
            "banner_target_url",
        ):
            if key in cleaned:
                cleaned[key] = (cleaned.get(key) or "").strip()
        return cleaned
