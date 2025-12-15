from __future__ import annotations

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def send_email_via_sendgrid(to_email: str, subject: str, text_content: str, html_content: str | None = None) -> None:
    """Send an email using SendGrid Web API.

    This uses the SendGrid API key configured in settings.
    """

    if not settings.SENDGRID_API_KEY or not settings.SENDGRID_FROM_EMAIL:
        logger.warning("SENDGRID_API_KEY/SENDGRID_FROM_EMAIL not set; skipping email to %s", to_email)
        return

    try:
        from sendgrid import SendGridAPIClient
        from sendgrid.helpers.mail import Mail
    except Exception as e:
        logger.exception("SendGrid package not installed. pip install sendgrid. Error: %s", e)
        return

    message = Mail(
        from_email=settings.SENDGRID_FROM_EMAIL,
        to_emails=to_email,
        subject=subject,
        plain_text_content=text_content,
        html_content=html_content,
    )

    try:
        sg = SendGridAPIClient(settings.SENDGRID_API_KEY)
        sg.send(message)
    except Exception:
        logger.exception("Failed to send email via SendGrid to %s", to_email)
