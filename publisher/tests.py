from __future__ import annotations

from django.test import SimpleTestCase

from publisher.forms import DoctorRecordForm, FieldRepRecordForm


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
