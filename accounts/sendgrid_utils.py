from __future__ import annotations

import json
import os
import smtplib
import ssl
import traceback
from email.message import EmailMessage
from pathlib import Path
from typing import Optional, Tuple

from django.conf import settings

from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail, Email, To, Content

from .email_log import EmailLog


# Try these locations in order (keeps your old hardcoded path as last fallback)
_ENV_CANDIDATES = [
    Path(os.getenv("ENV_PATH", "")).expanduser() if os.getenv("ENV_PATH") else None,
    Path(__file__).resolve().parent.parent / ".env",           # project-root/.env
    Path("/home/ubuntu/peds_edu_app/.env"),                    # your current server path
]


def _first_env_path() -> Optional[Path]:
    for p in _ENV_CANDIDATES:
        if p and p.exists():
            return p
    return None


def _read_env_var(key: str) -> str:
    """
    Minimal .env reader (only used if the process env is not set properly).
    Supports:
      KEY=value
      KEY="value"
      KEY=value # comment
    """
    env_path = _first_env_path()
    if not env_path:
        return ""

    try:
        txt = env_path.read_text(encoding="utf-8")
    except Exception:
        return ""

    for line in txt.splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        if k.strip() != key:
            continue

        v = v.strip()

        # Strip inline comments if not quoted
        if v and v[0] not in ('"', "'") and " #" in v:
            v = v.split(" #", 1)[0].strip()

        # Strip quotes
        if len(v) >= 2 and ((v[0] == '"' and v[-1] == '"') or (v[0] == "'" and v[-1] == "'")):
            v = v[1:-1]

        return v.strip()

    return ""


def _sanitize_secret(s: str) -> str:
    s = (s or "").strip()
    # Common mistake: putting "Bearer <key>" in env
    if s.lower().startswith("bearer "):
        s = s.split(None, 1)[1].strip()
    return s


def _fingerprint(secret: str) -> str:
    secret = secret or ""
    if len(secret) <= 6:
        return secret
    return f"{secret[:2]}…{secret[-6:]}"


def _smtp_enabled() -> bool:
    mode = getattr(settings, "EMAIL_BACKEND_MODE", "") or os.getenv("EMAIL_BACKEND", "")
    return str(mode).strip().lower() == "smtp"


class CapturingSMTP_SSL(smtplib.SMTP_SSL):
    """
    Capture smtplib debug output into an in-memory transcript so we can store it in EmailLog.debug_trace.
    """
    def __init__(self, *args, **kwargs):
        self.transcript = []
        super().__init__(*args, **kwargs)

    def _print_debug(self, *args):
        try:
            self.transcript.append(" ".join(str(a) for a in args))
        except Exception:
            pass


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
    transcript_parts = []
    last_err = ""

    password = _sanitize_secret(password)

    for attempt in range(1, max_retries + 1):
        try:
            msg = EmailMessage()
            msg["From"] = from_email
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.set_content(text)

            ctx = ssl.create_default_context()

            if use_ssl:
                smtp = CapturingSMTP_SSL(host=host, port=port, timeout=20, context=ctx)
            else:
                smtp = smtplib.SMTP(host=host, port=port, timeout=20)
                smtp.set_debuglevel(1)

            # Enable debug capture
            if hasattr(smtp, "set_debuglevel"):
                smtp.set_debuglevel(1)

            smtp.ehlo()

            if use_tls and not use_ssl:
                smtp.starttls(context=ctx)
                smtp.ehlo()

            if user and password:
                smtp.login(user, password)

            smtp.send_message(msg)
            smtp.quit()

            transcript = ""
            if isinstance(smtp, CapturingSMTP_SSL):
                transcript = "\n".join(smtp.transcript)

            transcript_parts.append(f"--- attempt {attempt} ok ---\n{transcript}".strip())
            return True, "\n\n".join(tp for tp in transcript_parts if tp), ""

        except Exception as e:
            last_err = str(e)
            tb = traceback.format_exc()
            transcript_parts.append(f"--- attempt {attempt} failed ---\n{last_err}\n{tb}".strip())

    return False, "\n\n".join(tp for tp in transcript_parts if tp), last_err


def _smtp_send_raw(to_email: str, subject: str, text: str) -> Tuple[bool, str, str]:
    host = getattr(settings, "EMAIL_HOST", "smtp.sendgrid.net")
    port = int(getattr(settings, "EMAIL_PORT", 587) or 587)

    use_tls = bool(getattr(settings, "EMAIL_USE_TLS", True))
    use_ssl = bool(getattr(settings, "EMAIL_USE_SSL", False))

    user = getattr(settings, "EMAIL_HOST_USER", "apikey") or "apikey"
    password = getattr(settings, "EMAIL_HOST_PASSWORD", "") or ""

    # If not set, fall back to SENDGRID_API_KEY
    if not password:
        password = getattr(settings, "SENDGRID_API_KEY", "") or _read_env_var("SENDGRID_API_KEY")

    from_email = (
        getattr(settings, "DEFAULT_FROM_EMAIL", "")
        or getattr(settings, "SENDGRID_FROM_EMAIL", "")
        or _read_env_var("SENDGRID_FROM_EMAIL")
        or "no-reply@example.com"
    )

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

    # Fallback: if 465 SSL is flaky, retry via 587 STARTTLS once
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
        trace = (trace + "\n\n" + "--- fallback to 587 STARTTLS ---\n" + trace2).strip()
        ok = ok2
        err = err2 or err

    return ok, trace, err


def _sendgrid_send_raw(to_email: str, subject: str, text: str) -> Tuple[bool, int, str]:
    api_key = _sanitize_secret(getattr(settings, "SENDGRID_API_KEY", "") or "")
    if not api_key:
        api_key = _sanitize_secret(_read_env_var("SENDGRID_API_KEY"))

    from_email = (
        getattr(settings, "SENDGRID_FROM_EMAIL", "")
        or getattr(settings, "DEFAULT_FROM_EMAIL", "")
        or _read_env_var("SENDGRID_FROM_EMAIL")
        or "no-reply@example.com"
    )

    if not api_key:
        return False, 0, "SENDGRID_API_KEY missing"

    mail = Mail(
        from_email=Email(from_email),
        to_emails=To(to_email),
        subject=subject,
        plain_text_content=Content("text/plain", text),
    )

    try:
        sg = SendGridAPIClient(api_key)
        resp = sg.client.mail.send.post(request_body=mail.get())
        body = ""
        try:
            body = resp.body.decode("utf-8", errors="ignore") if hasattr(resp.body, "decode") else str(resp.body)
        except Exception:
            body = str(resp.body)

        return (200 <= int(resp.status_code) < 300), int(resp.status_code), body

    except Exception as e:
        # sendgrid-python typically raises HTTPError; include body if available
        msg = str(e)
        return False, getattr(e, "code", 0) or 0, msg


def send_email_via_sendgrid(to_email: str, subject: str, text: str) -> bool:
    """
    Backwards-compatible: returns True/False and logs into EmailLog.
    Provider order:
      - If EMAIL_BACKEND_MODE == smtp => SMTP first, then SendGrid API
      - Else => SendGrid API first, then SMTP
    """
    to_email = (to_email or "").strip()
    subject = (subject or "").strip()

    # choose provider order
    providers = ["smtp", "sendgrid"] if _smtp_enabled() else ["sendgrid", "smtp"]

    for provider in providers:
        try:
            if provider == "smtp":
                ok, trace, err = _smtp_send_raw(to_email, subject, text)
                EmailLog.objects.create(
                    to_email=to_email,
                    subject=subject,
                    provider="smtp",
                    success=ok,
                    status_code=0 if ok else 0,
                    response_body="" if ok else err,
                    error_detail="" if ok else err,
                    debug_trace=trace,
                )
                if ok:
                    return True

            else:
                ok, status_code, body = _sendgrid_send_raw(to_email, subject, text)
                EmailLog.objects.create(
                    to_email=to_email,
                    subject=subject,
                    provider="sendgrid",
                    success=ok,
                    status_code=status_code,
                    response_body=body or "",
                    error_detail="" if ok else (body or ""),
                    debug_trace=f"api_key_fp={_fingerprint(getattr(settings,'SENDGRID_API_KEY','') or _read_env_var('SENDGRID_API_KEY'))}",
                )
                if ok:
                    return True

        except Exception as e:
            EmailLog.objects.create(
                to_email=to_email,
                subject=subject,
                provider=provider,
                success=False,
                status_code=0,
                response_body=str(e),
                error_detail=str(e),
                debug_trace=traceback.format_exc(),
            )

    return False
