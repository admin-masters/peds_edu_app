from __future__ import annotations

from functools import wraps
from typing import Any, Dict, Optional, Sequence
from urllib.parse import urlencode

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect

# Part-C session keys (Project2)
SESSION_KEY = getattr(settings, "SSO_SESSION_KEY_IDENTITY", "sso_identity")
SESSION_CAMPAIGN_KEY = getattr(settings, "SSO_SESSION_KEY_CAMPAIGN", "campaign_id")

# Legacy compatibility (if any old sessions exist)
LEGACY_SESSION_KEY = "publisher_jwt_claims"
LEGACY_CAMPAIGN_KEY = "publisher_current_campaign_id"


def unauthorized_response() -> HttpResponse:
    return HttpResponse("unauthorised access", status=401, content_type="text/plain")


def _normalize_roles(value: Any) -> Sequence[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def _extract_token(request: HttpRequest) -> Optional[str]:
    token = (
        request.GET.get("token")
        or request.GET.get("jwt")
        or request.GET.get("access_token")
    )
    if token:
        return token.strip()

    auth = (request.META.get("HTTP_AUTHORIZATION") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    return None


import time
from accounts import master_db

SESSION_PUBLISHER_MASTER_VALIDATION = "publisher_master_validation"
PUBLISHER_MASTER_VALIDATION_TTL_SECONDS = getattr(settings, "PUBLISHER_MASTER_VALIDATION_TTL_SECONDS", 300)


def _extract_email_from_claims(ident: Dict[str, Any]) -> str:
    """
    We must map JWT claims to the AuthorizedPublisher.email in master DB.
    Prefer ident['email'] if present, else fallback to ident['username'] if it looks like an email.
    """
    email = (ident.get("email") or "").strip().lower()
    if email and "@" in email:
        return email

    username = (ident.get("username") or "").strip().lower()
    if username and "@" in username:
        return username

    # If your tokens carry publisher email in a different claim, add it here:
    # e.g. ident.get("publisher_email")
    other = (ident.get("publisher_email") or "").strip().lower()
    if other and "@" in other:
        return other

    return ""


def _is_publisher_authorized_in_master(request: HttpRequest, email: str) -> bool:
    """
    Cached check (session cache for 5 minutes default).
    """
    if not email:
        return False

    cache = request.session.get(SESSION_PUBLISHER_MASTER_VALIDATION) or {}
    now = int(time.time())

    if (
        isinstance(cache, dict)
        and cache.get("email") == email
        and cache.get("ok") is True
        and isinstance(cache.get("ts"), int)
        and now - cache["ts"] <= int(PUBLISHER_MASTER_VALIDATION_TTL_SECONDS)
    ):
        return True

    ok = master_db.authorized_publisher_exists(email)
    request.session[SESSION_PUBLISHER_MASTER_VALIDATION] = {"email": email, "ok": bool(ok), "ts": now}
    request.session.modified = True
    return bool(ok)


def get_publisher_claims(request: HttpRequest) -> Optional[Dict[str, Any]]:
    ident = request.session.get(SESSION_KEY)
    if isinstance(ident, dict):
        roles = _normalize_roles(ident.get("roles"))
        if "publisher" in [r.lower() for r in roles]:
            email = _extract_email_from_claims(ident)
            if _is_publisher_authorized_in_master(request, email):
                return ident

            # Not authorized anymore -> wipe session identity
            request.session.pop(SESSION_KEY, None)
            request.session.pop(SESSION_CAMPAIGN_KEY, None)
            request.session.pop(SESSION_PUBLISHER_MASTER_VALIDATION, None)
            request.session.modified = True
            return None

    legacy = request.session.get(LEGACY_SESSION_KEY)
    if isinstance(legacy, dict):
        roles = _normalize_roles(legacy.get("roles"))
        if "publisher" in [r.lower() for r in roles]:
            email = _extract_email_from_claims(legacy)
            if _is_publisher_authorized_in_master(request, email):
                return legacy

            request.session.pop(LEGACY_SESSION_KEY, None)
            request.session.pop(LEGACY_CAMPAIGN_KEY, None)
            request.session.pop(SESSION_PUBLISHER_MASTER_VALIDATION, None)
            request.session.modified = True
            return None

    return None



def _redirect_to_sso_consume(request: HttpRequest, token: str) -> HttpResponse:
    campaign_id = (
        request.GET.get("campaign_id")
        or request.GET.get("campaign-id")
        or request.session.get(SESSION_CAMPAIGN_KEY)
        or request.session.get(LEGACY_CAMPAIGN_KEY)
        or ""
    )
    if not campaign_id:
        return unauthorized_response()

    # next URL without token params
    params = request.GET.copy()
    for k in ("token", "jwt", "access_token"):
        if k in params:
            params.pop(k)

    next_url = request.path
    if params:
        next_url = f"{next_url}?{params.urlencode()}"

    consume_url = "/sso/consume/?" + urlencode(
        {"token": token, "campaign_id": campaign_id, "next": next_url}
    )
    return redirect(consume_url)


def publisher_required(view_func):
    """
    Part-C destination behavior:
    - If valid SSO session exists -> allow
    - Else if token present -> route via /sso/consume/
    - Else -> 401 unauthorised access

    Adds print logs (JSON lines) without leaking tokens.
    """
    import json
    import time
    import uuid

    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        req_id = request.META.get("HTTP_X_REQUEST_ID") or uuid.uuid4().hex[:12]

        def _plog(event: str, **data) -> None:
            payload = {
                "ts": int(time.time()),
                "req_id": req_id,
                "event": event,
                "path": request.path,
                "method": request.method,
                "view": getattr(view_func, "__name__", "unknown"),
            }
            payload.update(data)
            try:
                print(json.dumps(payload, default=str))
            except Exception:
                print(f"[req_id={req_id}] {event} {data}")

        _plog("publisher_required.start")

        try:
            claims = get_publisher_claims(request)
        except Exception as e:
            _plog("publisher_required.claims_error", error=str(e))
            return unauthorized_response()

        if claims:
            roles = claims.get("roles")
            # Do not print sensitive fields; best-effort identify
            username = (claims.get("email") or claims.get("username") or claims.get("sub") or "")
            if isinstance(username, str) and "@" in username:
                u_masked = username.split("@", 1)[0][:2] + "***@" + username.split("@", 1)[1]
            else:
                u_masked = str(username)[:6] + "***" if username else ""
            _plog("publisher_required.authorized", user=u_masked, roles=roles)
            return view_func(request, *args, **kwargs)

        token = _extract_token(request)
        if token:
            _plog("publisher_required.token_present.redirect_to_consume", token_len=len(token))
            return _redirect_to_sso_consume(request, token)

        _plog("publisher_required.unauthorized.no_claims_no_token")
        return unauthorized_response()

    return _wrapped
