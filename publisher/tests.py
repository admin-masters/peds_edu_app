from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from publisher.forms import DoctorRecordForm, FieldRepRecordForm, MasterCampaignRecordForm


class DoctorRecordFormTests(SimpleTestCase):
    def test_accepts_master_schema_sized_values(self) -> None:
        form = DoctorRecordForm(
            data={
                "first_name": "Aarav",
                "last_name": "Menon",
                "email": "doctor.demo@pedsedu.local",
                "whatsapp_no": "919876543210",
                "clinic_name": "L" * 150,
                "clinic_phone": "02041234567",
                "clinic_appointment_number": "02041234567",
                "clinic_address": "123 Demo Street",
                "postal_code": "411001",
                "state": "Maharashtra",
                "district": "Pune",
                "receptionist_whatsapp_number": "919980011223",
                "imc_registration_number": "123456789012345678901234567890",
                "field_rep_id": "FR-DEMO-001",
                "recruited_via": "FIELD_REP_IMPORTER",
                "clinic_user1_name": "Front Desk",
                "clinic_user1_email": "frontdesk.demo@pedsedu.local",
                "clinic_user2_name": "",
                "clinic_user2_email": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)


class FieldRepRecordFormTests(SimpleTestCase):
    def test_accepts_master_schema_sized_values(self) -> None:
        form = FieldRepRecordForm(
            data={
                "full_name": "A" * 230,
                "phone_number": "919876543210",
                "brand_supplied_field_rep_id": "F" * 80,
                "state": "Maharashtra",
                "is_active": "on",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)


class MasterCampaignRecordFormTests(SimpleTestCase):
    def test_accepts_master_campaign_schema_values(self) -> None:
        form = MasterCampaignRecordForm(
            data={
                "name": "Asthma Care Spring 2026",
                "num_doctors_supported": 25,
                "add_to_campaign_message": "Hello doctor",
                "register_message": "Welcome to the campaign",
                "banner_small_url": "https://example.com/small.png",
                "banner_large_url": "https://example.com/large.png",
                "banner_target_url": "https://example.com/landing",
                "brand_id": 7,
                "system_pe": "on",
                "start_date": "2026-04-11",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)


@override_settings(
    STATICFILES_STORAGE="django.contrib.staticfiles.storage.StaticFilesStorage",
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
)
class PERecordsLoginFlowTests(SimpleTestCase):
    @patch("publisher.views.authenticate")
    def test_superuser_can_open_pe_records_session(self, authenticate_mock) -> None:
        mock_user = SimpleNamespace(
            pk=7,
            email="will.superuser@pedsedu.local",
            is_authenticated=True,
            is_active=True,
            is_superuser=True,
        )
        authenticate_mock.return_value = mock_user
        response = self.client.post(
            reverse("publisher:pe_records_login"),
            {"email": mock_user.email, "password": "Admin123!"},
        )

        self.assertRedirects(response, reverse("publisher:pe_records_dashboard"), fetch_redirect_response=False)
        self.assertEqual(self.client.session.get("pe_records_user_id"), mock_user.pk)

    @patch("publisher.views.authenticate")
    def test_regular_user_is_rejected_from_pe_records_login(self, authenticate_mock) -> None:
        mock_user = SimpleNamespace(
            pk=8,
            email="publisher.user@pedsedu.local",
            is_authenticated=True,
            is_active=True,
            is_superuser=False,
        )
        authenticate_mock.return_value = mock_user
        response = self.client.post(
            reverse("publisher:pe_records_login"),
            {"email": mock_user.email, "password": "Publisher123!"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Only a system superuser can access the PE records dashboard.")
        self.assertIsNone(self.client.session.get("pe_records_user_id"))
