from __future__ import annotations

from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve

from .support_widget import get_support_page, get_support_widget_for_request


class SupportWidgetConfigTests(SimpleTestCase):
    def setUp(self) -> None:
        self.factory = RequestFactory()

    def _request(self, path: str):
        request = self.factory.get(path)
        request.resolver_match = resolve(path)
        return request

    def test_login_page_uses_doctor_login_widget(self) -> None:
        config = get_support_widget_for_request(self._request("/accounts/login/"))

        self.assertIsNotNone(config)
        self.assertEqual(config["page_slug"], "patient-education-flow1-doctor-doctor-login-page")
        self.assertIn("embed=1", config["embed_url"])

    def test_doctor_share_uses_sharing_widget(self) -> None:
        config = get_support_widget_for_request(self._request("/clinic/DOC123/share/"))

        self.assertIsNotNone(config)
        self.assertEqual(config["page_slug"], "patient-education-flow1-doctor-doctor-clinic-sharing-page")

    def test_patient_routes_share_the_patient_support_widget(self) -> None:
        video_config = get_support_widget_for_request(self._request("/p/DOC123/v/VID123/"))
        cluster_config = get_support_widget_for_request(self._request("/p/DOC123/c/CLUSTER123/"))

        self.assertEqual(video_config["page_slug"], "patient-education-flow2-patient-patient-page")
        self.assertEqual(cluster_config["page_slug"], "patient-education-flow2-patient-patient-page")

    def test_doctor_credentials_email_support_link_is_available(self) -> None:
        config = get_support_page("doctor_credentials_email")

        self.assertIsNotNone(config)
        self.assertTrue(config["widget_url"].endswith("Flow1+%2F+Doctor"))
