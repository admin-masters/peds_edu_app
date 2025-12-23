from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError
from django.forms import inlineformset_factory
from django.forms.models import BaseInlineFormSet

from catalog.constants import LANGUAGE_CODES
from catalog.models import TherapyArea, Video, VideoCluster, VideoLanguage, Trigger, TriggerCluster


class TherapyAreaForm(forms.ModelForm):
    class Meta:
        model = TherapyArea
        fields = ["code", "display_name", "description", "is_active"]


class VideoClusterForm(forms.ModelForm):
    class Meta:
        model = VideoCluster
        fields = ["code", "display_name", "description", "is_active"]


class VideoForm(forms.ModelForm):
    class Meta:
        model = Video
        fields = ["code", "thumbnail_url", "is_active"]


class VideoLanguageForm(forms.ModelForm):
    class Meta:
        model = VideoLanguage
        fields = ["language_code", "title", "youtube_url"]


class BaseVideoLanguageFormSet(BaseInlineFormSet):
    """Enforce that all 8 languages are present and have title + URL."""

    def clean(self):
        super().clean()

        seen = set()
        missing = set(LANGUAGE_CODES)

        for form in self.forms:
            # If the form itself is invalid, skip; Django will surface field-level errors.
            if not hasattr(form, "cleaned_data"):
                continue

            code = form.cleaned_data.get("language_code")
            title = (form.cleaned_data.get("title") or "").strip()
            url = (form.cleaned_data.get("youtube_url") or "").strip()

            if not code:
                continue

            if code in seen:
                raise ValidationError(
                    "Duplicate language detected. Each language must be entered exactly once."
                )

            seen.add(code)
            missing.discard(code)

            # Fields are required by the model, but enforce here as well (esp. for edge cases)
            if not title or not url:
                raise ValidationError(
                    "Please provide both Title and YouTube URL for every language."
                )

        if missing:
            raise ValidationError(
                "Please provide Title and YouTube URL for all languages: " + ", ".join(sorted(missing))
            )


def make_video_language_formset(extra=0):
    return inlineformset_factory(
        Video,
        VideoLanguage,
        form=VideoLanguageForm,
        formset=BaseVideoLanguageFormSet,
        fields=["language_code", "title", "youtube_url"],
        extra=extra,
        can_delete=False,
    )


class TriggerForm(forms.ModelForm):
    class Meta:
        model = Trigger
        fields = ["display_name", "primary_therapy", "is_active"]


class TriggerClusterForm(forms.ModelForm):
    class Meta:
        model = TriggerCluster
        fields = ["display_name", "language_code", "is_active"]
