from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from accounts import master_db
from publisher.forms import DoctorRecordForm, FieldRepRecordForm, MasterCampaignRecordForm
from publisher.views import _build_pe_records_context


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


class PEDoctorMatchingTests(SimpleTestCase):
    def test_pe_activity_matching_prefers_field_rep_aware_match(self) -> None:
        doctor_indexes = master_db._build_doctor_candidate_indexes(
            [
                {
                    "doctor_id": "DR-PE-1",
                    "first_name": "Aarav",
                    "last_name": "Dsouza",
                    "email": "doctor@example.com",
                    "whatsapp_no": "9876543210",
                    "clinic_phone": "",
                    "clinic_appointment_number": "",
                    "receptionist_whatsapp_number": "",
                    "field_rep_id": "FR-PE-1",
                },
                {
                    "doctor_id": "DR-NONPE-1",
                    "first_name": "Aarav",
                    "last_name": "Dsouza",
                    "email": "doctor@example.com",
                    "whatsapp_no": "9876543210",
                    "clinic_phone": "",
                    "clinic_appointment_number": "",
                    "receptionist_whatsapp_number": "",
                    "field_rep_id": "FR-NONPE-1",
                },
            ]
        )

        matched_doctor_id = master_db._match_pe_activity_row_to_doctor(
            {
                "doctor_id": "",
                "email": "doctor@example.com",
                "phone": "9876543210",
                "full_name": "Aarav Dsouza",
                "rep_brand_id": "FR-PE-1",
            },
            doctor_indexes,
        )

        self.assertEqual(matched_doctor_id, "DR-PE-1")

    def test_named_support_phone_match_excludes_unrelated_doctors(self) -> None:
        doctor_indexes = master_db._build_doctor_candidate_indexes(
            [
                {
                    "doctor_id": "DR-PE-1",
                    "first_name": "Aarav",
                    "last_name": "Dsouza",
                    "email": "",
                    "whatsapp_no": "",
                    "clinic_phone": "02041234567",
                    "clinic_appointment_number": "",
                    "receptionist_whatsapp_number": "",
                },
                {
                    "doctor_id": "DR-NONPE-1",
                    "first_name": "Neha",
                    "last_name": "Kapoor",
                    "email": "",
                    "whatsapp_no": "",
                    "clinic_phone": "02041234567",
                    "clinic_appointment_number": "",
                    "receptionist_whatsapp_number": "",
                },
            ]
        )

        matched_doctor_id = master_db._match_campaign_doctor_row_to_master_doctor(
            {
                "email": "",
                "phone": "02041234567",
                "full_name": "Aarav Dsouza",
            },
            doctor_indexes,
        )

        self.assertEqual(matched_doctor_id, "DR-PE-1")

    def test_ambiguous_phone_only_match_is_rejected(self) -> None:
        doctor_indexes = master_db._build_doctor_candidate_indexes(
            [
                {
                    "doctor_id": "DR-PE-1",
                    "first_name": "Aarav",
                    "last_name": "Dsouza",
                    "email": "",
                    "whatsapp_no": "9876543210",
                    "clinic_phone": "",
                    "clinic_appointment_number": "",
                    "receptionist_whatsapp_number": "",
                },
                {
                    "doctor_id": "DR-NONPE-1",
                    "first_name": "Neha",
                    "last_name": "Kapoor",
                    "email": "",
                    "whatsapp_no": "9876543210",
                    "clinic_phone": "",
                    "clinic_appointment_number": "",
                    "receptionist_whatsapp_number": "",
                },
            ]
        )

        matched_doctor_id = master_db._match_campaign_doctor_row_to_master_doctor(
            {
                "email": "",
                "phone": "9876543210",
                "full_name": "",
            },
            doctor_indexes,
        )

        self.assertIsNone(matched_doctor_id)


class PERecordsContextTests(SimpleTestCase):
    @patch("publisher.views.DoctorProfile.objects")
    @patch("publisher.views.master_db.list_pe_doctor_records")
    @patch("publisher.views.master_db.list_pe_field_rep_records")
    @patch("publisher.views._build_local_campaign_map")
    @patch("publisher.views._get_pe_master_campaign_records")
    def test_people_queries_are_scoped_to_pe_campaign_ids(
        self,
        get_pe_campaigns_mock,
        build_local_campaign_map_mock,
        list_field_reps_mock,
        list_doctors_mock,
        doctor_profile_objects_mock,
    ) -> None:
        get_pe_campaigns_mock.return_value = [
            SimpleNamespace(
                campaign_id="PE001",
                name="PE Campaign",
                num_doctors_supported=10,
                enrolled_doctor_count=3,
                field_rep_count=2,
                start_date="2026-04-11",
            )
        ]
        build_local_campaign_map_mock.return_value = {}
        list_field_reps_mock.return_value = []
        list_doctors_mock.return_value = []
        doctor_profile_objects_mock.select_related.return_value.filter.return_value = []

        context = _build_pe_records_context()

        list_field_reps_mock.assert_called_once_with("", campaign_ids=["PE001"])
        list_doctors_mock.assert_called_once_with("", campaign_ids=["PE001"])
        self.assertEqual(context["stats"]["master_campaigns"], 1)
        self.assertEqual(context["stats"]["field_reps"], 0)
        self.assertEqual(context["stats"]["doctors"], 0)


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
