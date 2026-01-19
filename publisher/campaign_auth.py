from __future__ import annotations

import os
import time
from functools import wraps
from typing import Any, Dict, Optional, Sequence, Tuple

import jwt
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpRequest, HttpResponse

SESSION_KEY = "publisher_jwt_claims"
SESSION_CAMPAIGN_KEY = "publisher_current_campaign_id"


def unauthorized_response() -> HttpResponse:
    return HttpResponse("unauthorised access", status=401, content_type="text/plain")


def _extract_token(request: HttpRequest) -> Optional[str]:
    # Query params supported (most common for “link-based access”)
    token = (
        request.GET.get("jwt")
        or request.GET.get("token")
        or request.GET.get("access_token")
    )
    if token:
        return token.strip()

    # Header supported as well (optional)
    auth = (request.META.get("HTTP_AUTHORIZATION") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()

    return None


def _jwt_config() -> Tuple[str, str, str, str]:
    """
    Returns (algorithm, key, issuer, audience)
    """
    algorithm = os.getenv("PUBLISHER_JWT_ALGORITHM", "HS256").strip()
    issuer = os.getenv("PUBLISHER_JWT_ISSUER", "project1").strip()
    audience = os.getenv("PUBLISHER_JWT_AUDIENCE", "project2").strip()

    if algorithm.upper().startswith("RS"):
        key = os.getenv("PUBLISHER_JWT_PUBLIC_KEY", "").strip()
        if not key:
            raise ImproperlyConfigured(
                "Missing PUBLISHER_JWT_PUBLIC_KEY for RS* JWT validation."
            )
    else:
        key = os.getenv("PUBLISHER_JWT_SECRET", "").strip()
        if not key:
            raise ImproperlyConfigured(
                "Missing PUBLISHER_JWT_SECRET for HS* JWT validation."
            )

    return algorithm, key, issuer, audience


def _normalize_roles(value: Any) -> Sequence[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value]
    return [str(value)]


def validate_publisher_jwt(token: str) -> Dict[str, Any]:
    algorithm, key, issuer, audience = _jwt_config()

    claims = jwt.decode(
        token,
        key=key,
        algorithms=[algorithm],
        issuer=issuer,
        audience=audience,
        options={
            "require": ["exp", "iat", "iss", "aud", "sub"],
        },
        leeway=30,  # allow small clock skew
    )

    roles = _normalize_roles(claims.get("roles"))
    if "publisher" not in [r.lower() for r in roles]:
        raise jwt.InvalidTokenError("JWT does not contain required role: publisher")

    return claims


def establish_publisher_session(request: HttpRequest, claims: Dict[str, Any]) -> None:
    roles = _normalize_roles(claims.get("roles"))
    normalized_roles = [r for r in roles]

    exp = int(claims.get("exp") or 0)
    now = int(time.time())
    if exp <= now:
        raise jwt.ExpiredSignatureError("Token already expired")

    # Prevent session fixation
    try:
        request.session.cycle_key()
    except Exception:
        pass

    request.session[SESSION_KEY] = {
        "iss": claims.get("iss"),
        "aud": claims.get("aud"),
        "sub": claims.get("sub"),
        "username": claims.get("username"),
        "roles": normalized_roles,
        "iat": claims.get("iat"),
        "exp": exp,
    }

    # Align Django session expiry to JWT expiry
    request.session.set_expiry(max(1, exp - now))


def get_publisher_claims(request: HttpRequest) -> Optional[Dict[str, Any]]:
    data = request.session.get(SESSION_KEY)
    if not data:
        return None

    exp = int(data.get("exp") or 0)
    if exp and exp <= int(time.time()):
        try:
            del request.session[SESSION_KEY]
        except Exception:
            pass
        return None

    roles = _normalize_roles(data.get("roles"))
    if "publisher" not in [r.lower() for r in roles]:
        return None

    return dict(data)


def publisher_required(view_func):
    """
    Decorator:
    - If JWT is provided (query/header), validate it and create a session.
    - Otherwise require an existing valid publisher session.
    - If not valid -> 401 "unauthorised access"
    """

    @wraps(view_func)
    def _wrapped(request: HttpRequest, *args, **kwargs):
        token = _extract_token(request)
        if token:
            try:
                claims = validate_publisher_jwt(token)
                establish_publisher_session(request, claims)
            except Exception:
                return unauthorized_response()

        if not get_publisher_claims(request):
            return unauthorized_response()

        return view_func(request, *args, **kwargs)

    return _wrapped
