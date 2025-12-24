from __future__ import annotations

import base64
import os
from functools import lru_cache
from typing import Optional

try:
    import boto3
    from botocore.exceptions import (
        BotoCoreError,
        ClientError,
        EndpointConnectionError,
        NoCredentialsError,
        NoRegionError,
        PartialCredentialsError,
    )
except Exception as e:  # pragma: no cover
    # Keep this extremely lightweight; do not crash import-time.
    print("[DEBUG] boto3 import failed:", repr(e))
    boto3 = None  # type: ignore
    BotoCoreError = Exception  # type: ignore
    ClientError = Exception  # type: ignore
    EndpointConnectionError = Exception  # type: ignore
    NoCredentialsError = Exception  # type: ignore
    NoRegionError = Exception  # type: ignore
    PartialCredentialsError = Exception  # type: ignore


_LAST_ERROR: str = ""


def _debug_enabled() -> bool:
    # Enable with DEBUG_AWS_SECRETS=1
    return os.getenv("DEBUG_AWS_SECRETS", "0") == "1"


def get_last_error() -> str:
    """Best-effort last error string from the most recent Secrets Manager call in this process."""
    return _LAST_ERROR


@lru_cache(maxsize=32)
def get_secret_string(secret_name: str, region_name: str = "ap-south-1") -> Optional[str]:
    """
    Fetch a secret string from AWS Secrets Manager.

    Best-effort: never raises.
    """
    global _LAST_ERROR
    _LAST_ERROR = ""

    if _debug_enabled():
        print(f"[DEBUG] get_secret_string called | secret_name={secret_name} | region={region_name}")

    if boto3 is None:
        _LAST_ERROR = "boto3_unavailable"
        if _debug_enabled():
            print("[DEBUG] boto3 unavailable")
        return None

    try:
        if _debug_enabled():
            print("[DEBUG] Creating boto3 session")
        session = boto3.session.Session()

        if _debug_enabled():
            print("[DEBUG] Creating Secrets Manager client")
        client = session.client(service_name="secretsmanager", region_name=region_name)

        if _debug_enabled():
            print("[DEBUG] Calling get_secret_value")
        response = client.get_secret_value(SecretId=secret_name)

    except (
        ClientError,
        NoCredentialsError,
        PartialCredentialsError,
        NoRegionError,
        EndpointConnectionError,
        BotoCoreError,
    ) as e:
        _LAST_ERROR = f"{type(e).__name__}: {e}"
        if _debug_enabled():
            print("[DEBUG] AWS error while fetching secret")
            print("[DEBUG] Error:", _LAST_ERROR)
        return None

    except Exception as e:
        _LAST_ERROR = f"{type(e).__name__}: {e}"
        if _debug_enabled():
            print("[DEBUG] Unexpected error while fetching secret")
            print("[DEBUG] Error:", _LAST_ERROR)
        return None

    if isinstance(response, dict) and response.get("SecretString"):
        if _debug_enabled():
            print("[DEBUG] SecretString returned")
        return str(response["SecretString"]).strip()

    if isinstance(response, dict) and response.get("SecretBinary"):
        if _debug_enabled():
            print("[DEBUG] SecretBinary returned, attempting base64 decode")
        try:
            decoded = base64.b64decode(response["SecretBinary"]).decode("utf-8").strip()
            if _debug_enabled():
                print("[DEBUG] SecretBinary decoded successfully")
            return decoded
        except Exception as e:
            _LAST_ERROR = f"decode_error:{type(e).__name__}: {e}"
            if _debug_enabled():
                print("[DEBUG] Failed to decode SecretBinary")
                print("[DEBUG] Error:", _LAST_ERROR)
            return None

    if _debug_enabled():
        print("[DEBUG] No SecretString or SecretBinary found in response")
    return None
