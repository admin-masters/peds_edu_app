from __future__ import annotations

import os
import smtplib
import ssl as ssl_lib
import socket
import time
import traceback
from email.message import EmailMessage
from pathlib import Path
from typing import Tuple, Optional

from django.conf import settings

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

from .email_log import EmailLog


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _sanitize_secret(s: str) -> str:
    """
    Remove common accidental prefixes/quotes/whitespace:
      - 'Bearer <key>'
      - surrounding quotes
      - trailing newlines/spaces
    """
    s = (s or "").strip().strip('"').strip("'")
    if s.lower().startswith("bearer "):
        s = s.split(None, 1)[1].strip()
    return s


def _fingerprint(secret: str) -> str:
    """Short, non-sensitive fingerprint for logs."""
    secret = secret or ""
    if len(secret) <= 8:
        return f"len={len(secret)}"
    return f"len={len(secret)} tail={secret[-6:]}"


def _read_env_var(key: str) -> str:
    """
    Best effort read of key from common .env locations if not in process env.
    """
    val = os.getenv(key)
    if val is not None and str(val).strip() != "":
        return str(val)

    candidates = [
        Path(os.getenv("ENV_PATH", "")).expanduser() if os.getenv("ENV_PATH") else None,
        Path("/home/ubuntu/peds_edu_app/.env"),
        Path(__file__).resolve().parent.parent / ".env",  # /workspaces/peds_edu_app/.env
    ]
    for p in candidates:
        if not p or not p.exists():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == key:
                    return v.strip()
        except Exception:
            continue
    return ""


def _smtp_enabled() -> bool:
    """
    Your settings.py uses EMAIL_BACKEND_MODE derived from env('EMAIL_BACKEND', ...).
    """
    mode = getattr(settings, "EMAIL_BACKEND_MODE", "") or os.getenv("EMAIL_BACKEND", "")
    if str(mode).strip().lower() == "smtp":
        return True

    backend = getattr(settings, "EMAIL_BACKEND", "") or ""
    return "smtp" in backend.lower()


def _probe_outbound(host: str, port: int, use_ssl: bool) -> str:
    """
    Quick network probe used only for diagnostics in EmailLog.
    """
    try:
        with socket.create_connection((host, port), timeout=5) as sock:
            if use_ssl:
                ctx = ssl_lib.create_default_context()
                with ctx.wrap_socket(sock, server_hostname=host):
                    return "tcp_ok_ssl_ok"
            return "tcp_ok"
    except Exception as e:
        return f"tcp_fail:{type(e).__name__}"


class _CapturingSMTPMixin:
    def __init__(self, *args, **kwargs):
        self._debug_lines = []
        super().__init__(*args, **kwargs)

    def _print_debug(self, *args):
        try:
            self._debug_lines.append(" ".join(str(a) for a in args))
        except Exception:
            pass

    def get_transcript(self) -> str:
        return "\n".join(self._debug_lines)


class CapturingSMTP(_CapturingSMTPMixin, smtplib.SMTP):
    pass


class CapturingSMTP_SSL(_CapturingSMTPMixin, smtplib.SMTP_SSL):
    pass


# ---------------------------------------------------------------------
# SMTP sender
# ---------------------------------------------------------------------

def _smtp_send_raw_with_config(
    *,
    host: str,
    port: int,
    use_tls: bool,
    use_ssl: bool,
    user: str,
    password: str,
    from_email: str,
    to_email: str,
    subject: str,
    text: str,
    max_retries: int = 2,
) -> Tuple[bool, str, str]:
    """
    Returns: (ok, transcript, error_message)
    """
    transcript_parts = []
    last_err = ""

    password = _sanitize_secret(password)

    for attempt in range(1, max_retries + 1):
        smtp = None
        try:
            msg = EmailMessage()
            msg["From"] = from_email
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.set_content(text)

            if use_ssl:
                ctx = ssl_lib.create_default_context()
                smtp = CapturingSMTP_SSL(host=host, port=port, timeout=20, context=ctx)
            else:
                smtp = CapturingSMTP(host=host, port=port, timeout=20)

            smtp.set_debuglevel(1)
            smtp.ehlo()

            if use_tls and not use_ssl:
                ctx = ssl_lib.create_default_context()
                smtp.starttls(context=ctx)
                smtp.ehlo()

            if user and password:
                smtp.login(user, password)

            smtp.send_message(msg)

            try:
                smtp.quit()
            except Exception:
                try:
                    smtp.close()
                except Exception:
                    pass

            return True, smtp.get_transcript(), ""

        except smtplib.SMTPServerDisconnected as e:
            last_err = f"SMTPServerDisconnected: {e}"
            t = smtp.get_transcript() if smtp else ""
            transcript_parts.append(f"--- attempt {attempt} disconnected ---\n{t}".strip())
            if attempt < max_retries:
                time.sleep(1.25 * attempt)
                continue

        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            t = smtp.get_transcript() if smtp else ""
            transcript_parts.append(
                f"--- attempt {attempt} failed ---\n{t}\n{traceback.format_exc()}".strip()
            )

        finally:
            try:
                if smtp:
                    smtp.close()
            except Exception:
                pass

    return False, "\n\n".join(tp for tp in transcript_parts if tp).strip(), last_err


def _smtp_send_raw(to_email: str, subject: str, text: str) -> Tuple[bool, str, str, str]:
    """
    Returns: (ok, transcript, error_message, password_fingerprint)
    """
    host = getattr(settings, "EMAIL_HOST", "smtp.sendgrid.net")
    port = int(getattr(settings, "EMAIL_PORT", 587) or 587)

    use_tls = bool(getattr(settings, "EMAIL_USE_TLS", True))
    use_ssl = bool(getattr(settings, "EMAIL_USE_SSL", False))

    user = getattr(settings, "EMAIL_HOST_USER", "apikey") or "apikey"

    # Password preference:
    #  1) EMAIL_HOST_PASSWORD (if valid)
    #  2) SENDGRID_API_KEY (settings or .env)
    password = _sanitize_secret(getattr(settings, "EMAIL_HOST_PASSWORD", "") or "")
    sg_key = _sanitize_secret(getattr(settings, "SENDGRID_API_KEY", "") or "") or _sanitize_secret(_read_env_var("SENDGRID_API_KEY"))

    # If EMAIL_HOST_PASSWORD is missing or clearly wrong (too short), fallback to SENDGRID_API_KEY.
    if (not password) or (password.lower().startswith("sg.") and len(password) < 20):
        password = sg_key

    from_email = (
        getattr(settings, "DEFAULT_FROM_EMAIL", "")
        or getattr(settings, "SENDGRID_FROM_EMAIL", "")
        or _read_env_var("SENDGRID_FROM_EMAIL")
        or "no-reply@example.com"
    )

    if not password:
        return False, "", "Missing SMTP password (EMAIL_HOST_PASSWORD or SENDGRID_API_KEY).", _fingerprint(password)

    ok, trace, err = _smtp_send_raw_with_config(
        host=host,
        port=port,
        use_tls=use_tls,
        use_ssl=use_ssl,
        user=user,
        password=password,
        from_email=from_email,
        to_email=to_email,
        subject=subject,
        text=text,
        max_retries=2,
    )

    # Fallback: if 465/SSL configured and disconnects, try 587/STARTTLS
    if (not ok) and use_ssl and port == 465:
        ok2, trace2, err2 = _smtp_send_raw_with_config(
            host=host,
            port=587,
            use_tls=True,
            use_ssl=False,
            user=user,
            password=password,
            from_email=from_email,
            to_email=to_email,
            subject=subject,
            text=text,
            max_retries=1,
        )
        trace = (trace + "\n\n--- fallback to 587 STARTTLS ---\n" + trace2).strip()
        ok = ok2
        err = err2 or err

    return ok, trace, err, _fingerprint(password)


# ---------------------------------------------------------------------
# SendGrid API sender
# ---------------------------------------------------------------------

def _sendgrid_send_raw(to_email: str, subject: str, text: str) -> Tuple[bool, int, str, str]:
    """
    Returns: (ok, status_code, response_body, api_key_fingerprint)
    """
    api_key = _sanitize_secret(getattr(settings, "SENDGRID_API_KEY", "") or "")
    if not api_key:
        api_key = _sanitize_secret(_read_env_var("SENDGRID_API_KEY"))

    from_email = (
        getattr(settings, "SENDGRID_FROM_EMAIL", "")
        or getattr(settings, "DEFAULT_FROM_EMAIL", "")
        or _read_env_var("SENDGRID_FROM_EMAIL")
        or "no-reply@example.com"
    )

    fp = _fingerprint(api_key)

    if not api_key:
        return False, 0, "SENDGRID_API_KEY missing", fp

    try:
        message = Mail(
            from_email=from_email,
            to_emails=to_email,
            subject=subject,
            plain_text_content=text,
        )
        sg = SendGridAPIClient(api_key)
        resp = sg.send(message)

        body = ""
        try:
            body = (resp.body or b"").decode("utf-8", errors="ignore")
        except Exception:
            body = str(resp.body)

        ok = 200 <= int(resp.status_code) < 300
        return ok, int(resp.status_code), body, fp

    except Exception as e:
        status_code = int(getattr(e, "status_code", 0) or getattr(e, "code", 0) or 0)

        body = ""
        try:
            raw_body = getattr(e, "body", None)
            if raw_body is not None:
                if isinstance(raw_body, (bytes, bytearray)):
                    body = raw_body.decode("utf-8", errors="ignore")
                else:
                    body = str(raw_body)
        except Exception:
            body = ""

        if not body:
            body = str(e)

        return False, status_code, body, fp


# ---------------------------------------------------------------------
# Public API used by accounts/views.py
# ---------------------------------------------------------------------

def send_email_via_sendgrid(to_email: str, subject: str, text: str) -> bool:
    """
    Returns True/False and logs into EmailLog.

    Provider order:
      - If EMAIL_BACKEND_MODE == smtp => SMTP first, then SendGrid API
      - Else => SendGrid API first, then SMTP
    """
    to_email = (to_email or "").strip()
    subject = (subject or "").strip()

    providers = ["smtp", "sendgrid"] if _smtp_enabled() else ["sendgrid", "smtp"]

    for provider in providers:
        if provider == "smtp":
            host = getattr(settings, "EMAIL_HOST", "smtp.sendgrid.net")
            port = int(getattr(settings, "EMAIL_PORT", 587) or 587)
            use_ssl = bool(getattr(settings, "EMAIL_USE_SSL", False))
            probe = _probe_outbound(host, port, use_ssl)

            ok, trace, err, pw_fp = _smtp_send_raw(to_email, subject, text)
            EmailLog.objects.create(
                to_email=to_email,
                subject=subject,
                provider="smtp",
                success=ok,
                status_code=202 if ok else None,
                response_body=trace or "",
                error="" if ok else f"{err} | host={host} port={port} ssl={use_ssl} probe={probe} pw_fp={pw_fp}",
            )
            if ok:
                return True

        else:
            ok, status_code, body, key_fp = _sendgrid_send_raw(to_email, subject, text)
            EmailLog.objects.create(
                to_email=to_email,
                subject=subject,
                provider="sendgrid",
                success=ok,
                status_code=status_code or None,
                response_body=body or "",
                error="" if ok else f"SendGrid failed | status={status_code} api_key_fp={key_fp}",
            )
            if ok:
                return True

    return False
