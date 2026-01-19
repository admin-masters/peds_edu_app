from __future__ import annotations

import uuid

from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from .jwt import decode_and_verify_hs256_jwt, JWTError


@require_http_methods(["GET"])
def consume(request):
    """
    SSO endpoint:
      GET /sso/consume/?token=...&campaign_id=...&next=/some/path

    Validates token and then creates Project2 session.
    """
    token = (request.GET.get("token") or "").strip()
    campaign_id_raw = (request.GET.get("campaign_id") or request.GET.get("campaign-id") or "").strip()
    next_url = (request.GET.get("next") or "/").strip() or "/"

    if not token or not campaign_id_raw:
        messages.error(request, "Missing token or campaign_id.")
        return redirect("/")

    if not getattr(settings, "SSO_SHARED_SECRET", ""):
        messages.error(request, "SSO not configured.")
        return redirect("/")

    try:
        payload = decode_and_verify_hs256_jwt(
            token,
            secret=settings.SSO_SHARED_SECRET,
            issuer=settings.SSO_EXPECTED_ISSUER,
            audience=settings.SSO_EXPECTED_AUDIENCE,
        )
    except JWTError:
        messages.error(
            request,
            "SSO link is invalid or expired. Please reopen it from the publisher portal."
        )
        return redirect("/")

    # Required claim checks (per your specified format)
    sub = (payload.get("sub") or "").strip()
    username = (payload.get("username") or "").strip()
    roles = payload.get("roles") or []

    if not sub or not username or not isinstance(roles, list):
        messages.error(request, "SSO token missing required claims.")
        return redirect("/")

    # Optional hardening:
    # If Project1 includes campaign_id inside JWT, validate queryparam vs claim.
    token_campaign = (payload.get("campaign_id") or "").strip()
    if token_campaign and token_campaign != campaign_id_raw:
        messages.error(request, "Invalid campaign_id.")
        return redirect("/")

    # Normalize campaign_id if it is a UUID; otherwise keep as string.
    campaign_id_value = campaign_id_raw
    try:
        campaign_id_value = str(uuid.UUID(campaign_id_raw))
    except Exception:
        pass

    # Create destination session (Project2’s own session)
    request.session[getattr(settings, "SSO_SESSION_KEY_IDENTITY", "sso_identity")] = {
        "sub": sub,
        "username": username,
        "roles": roles,
        "iss": payload.get("iss"),
        "aud": payload.get("aud"),
    }
    request.session[getattr(settings, "SSO_SESSION_KEY_CAMPAIGN", "campaign_id")] = str(campaign_id_value)

    # Session length on destination side:
    request.session.set_expiry(getattr(settings, "SSO_SESSION_AGE_SECONDS", 3600))
    request.session.modified = True

    # Safe redirect
    if not url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        next_url = "/"

    return redirect(next_url)
