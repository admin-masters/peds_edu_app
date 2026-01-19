from __future__ import annotations

from functools import wraps
from typing import Iterable, Optional

from django.conf import settings
from django.shortcuts import redirect


def sso_required(required_roles: Optional[Iterable[str]] = None):
    """
    Protect views so only users who came via SSO (valid token -> session created) can access.
    Optionally enforce roles like ["publisher"].
    """
    required_roles = list(required_roles or [])

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            ident = request.session.get(getattr(settings, "SSO_SESSION_KEY_IDENTITY", "sso_identity"))
            if not isinstance(ident, dict):
                return redirect("/")

            if required_roles:
                roles = ident.get("roles") or []
                if not isinstance(roles, list) or not any(r in roles for r in required_roles):
                    return redirect("/")

            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
