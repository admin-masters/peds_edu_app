from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict


class JWTError(ValueError):
    pass


class JWTInvalid(JWTError):
    pass


class JWTExpired(JWTError):
    pass


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + pad).encode("ascii"))


def decode_and_verify_hs256_jwt(
    token: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
    leeway_seconds: int = 30,
) -> Dict[str, Any]:
    """
    Verifies:
      - HS256 signature
      - iss == issuer
      - aud == audience
      - exp not expired (with leeway)
    Returns payload dict.
    """
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise JWTInvalid("Malformed JWT")

    # header
    try:
        header = json.loads(_b64url_decode(header_b64).decode("utf-8"))
    except Exception:
        raise JWTInvalid("Invalid JWT header")

    if header.get("alg") != "HS256":
        raise JWTInvalid("Unsupported alg")

    # signature
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception:
        raise JWTInvalid("Invalid signature encoding")

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise JWTInvalid("Invalid signature")

    # payload
    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise JWTInvalid("Invalid JWT payload")

    if not isinstance(payload, dict):
        raise JWTInvalid("Invalid payload type")

    if payload.get("iss") != issuer:
        raise JWTInvalid("Invalid issuer")

    if payload.get("aud") != audience:
        raise JWTInvalid("Invalid audience")

    now = int(time.time())
    exp = int(payload.get("exp") or 0)
    if exp <= 0:
        raise JWTInvalid("Missing exp")
    if now > exp + int(leeway_seconds or 0):
        raise JWTExpired("Token expired")

    iat = int(payload.get("iat") or 0)
    if iat and iat > now + 60:
        raise JWTInvalid("iat is in the future")

    return payload
