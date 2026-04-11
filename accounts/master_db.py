
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from django.conf import settings
from django.db import connections, IntegrityError

import secrets

from django.contrib.auth.hashers import make_password
from django.utils import timezone

from .models import RedflagsDoctor
from django.db import transaction
from django.db.models import Q

from .models import RedflagsDoctor


import logging

_master_logger = logging.getLogger("accounts.master_db")
_MASTER_CONN_LOGGED = False

def _mask_email_for_log(email: str) -> str:
    e = (email or "").strip()
    if not e or "@" not in e:
        return (e[:2] + "…") if e else ""
    local, domain = e.split("@", 1)
    return (local[:2] + "…@" + domain) if local else ("…@" + domain)


def authorized_publisher_exists(email: str) -> bool:
    """
    Checks AuthorizedPublisher in MASTER DB.

    - Never raises (missing table/column previously caused 401).
    - Tries configured table first, then a small list of common fallback table names.
    """
    e = (email or "").strip().lower()
    if not e:
        return False

    conn = get_master_connection()

    cfg_table = getattr(settings, "MASTER_DB_AUTH_PUBLISHER_TABLE", "publisher_authorizedpublisher")
    cfg_col = getattr(settings, "MASTER_DB_AUTH_PUBLISHER_EMAIL_COLUMN", "email")

    candidates = [
        (cfg_table, cfg_col),
        ("campaign_authorizedpublisher", "email"),
        ("publisher_authorizedpublisher", "email"),
        ("authorized_publisher", "email"),
        ("authorizedpublisher", "email"),
    ]

    masked = _mask_email_for_log(e)

    last_err = None
    for table, col in candidates:
        try:
            sql = f"SELECT 1 FROM {qn(table)} WHERE LOWER({qn(col)}) = LOWER(%s) LIMIT 1"
            with conn.cursor() as cur:
                cur.execute(sql, [e])
                ok = cur.fetchone() is not None
            if ok:
                return True
        except Exception as ex:
            last_err = f"{type(ex).__name__}: {ex}"
            continue

    return False



# def authorized_publisher_exists(email: str) -> bool:
#     """
#     Checks AuthorizedPublisher in MASTER DB.

#     Tries configured table first, then a few fallback table names.
#     Never raises (returns False on errors), but logs diagnostics.
#     """
#     e = (email or "").strip().lower()
#     if not e:
#         _log_db("publisher_auth.empty_email")
#         return False

#     conn = get_master_connection()

#     cfg_table = getattr(settings, "MASTER_DB_AUTH_PUBLISHER_TABLE", "publisher_authorizedpublisher")
#     cfg_col = getattr(settings, "MASTER_DB_AUTH_PUBLISHER_EMAIL_COLUMN", "email")

#     candidates = [
#         (cfg_table, cfg_col),
#         ("campaign_authorizedpublisher", "email"),
#         ("publisher_authorizedpublisher", "email"),
#         ("authorized_publisher", "email"),
#         ("authorizedpublisher", "email"),
#     ]

#     last_err = None
#     for table, col in candidates:
#         try:
#             sql = f"SELECT 1 FROM {qn(table)} WHERE LOWER({qn(col)}) = LOWER(%s) LIMIT 1"
#             with conn.cursor() as cur:
#                 cur.execute(sql, [e])
#                 if cur.fetchone() is not None:
#                     _log_db("publisher_auth.ok", table=table, col=col)
#                     return True

#             _log_db("publisher_auth.no_match", table=table, col=col)

#         except Exception as ex:
#             last_err = f"{type(ex).__name__}: {ex}"
#             _log_db("publisher_auth.check_error", table=table, col=col, error=last_err)
#             continue

#     _log_db("publisher_auth.not_found", configured_table=cfg_table, configured_col=cfg_col, last_error=last_err or "")
#     return False

#def master_alias() -> str:
 #   return getattr(settings, "MASTER_DB_ALIAS", "master")

def master_alias() -> str:
    return getattr(settings, "MASTER_DB_ALIAS", "master")


def get_master_connection():
    global _MASTER_CONN_LOGGED
    alias = master_alias()
    conn = connections[alias]

    # lightweight one-time log (helps ops confirm which alias is used)
    if not _MASTER_CONN_LOGGED:
        _master_logger.info("MASTER DB connection alias=%s vendor=%s", alias, getattr(conn, "vendor", None))
        _MASTER_CONN_LOGGED = True

    return conn


def _log_db(event: str, **kwargs):
    try:
        _master_logger.info("%s %s", event, json.dumps(kwargs, default=str))
    except Exception:
        _master_logger.info("%s %s", event, kwargs)


def _log_db_exc(event: str, **kwargs):
    try:
        _master_logger.exception("%s %s", event, json.dumps(kwargs, default=str))
    except Exception:
        _master_logger.exception("%s %s", event, kwargs)


def qn(name: str) -> str:
    """Quote names for the current master connection."""
    conn = get_master_connection()
    return conn.ops.quote_name(name)


def qcol(alias: str, name: str) -> str:
    return f"{qn(alias)}.{qn(name)}"


def normalize_wa_for_lookup(raw: str) -> str:
    if raw is None:
        return ""
    digits = re.sub(r"\D", "", str(raw))
    # Keep last 10 digits for Indian numbers
    if len(digits) > 10:
        digits = digits[-10:]
    return digits




def build_whatsapp_deeplink(phone_number: str, message: str) -> str:
    """Build a WhatsApp deep-link (wa.me) for a given phone number and message.

    - Accepts phone number in many common formats (spaces, +91, 0-prefix, etc.)
    - If a 10-digit number is provided, assumes India and prefixes country code 91.
    - Message is URL-encoded; newlines become %0A.

    Returns a URL suitable for redirecting a browser (mobile will open WhatsApp app when available).
    """
    digits = re.sub(r"\D", "", str(phone_number or ""))
    if digits:
        # Drop leading zeros (common when people enter 0XXXXXXXXXX)
        while digits.startswith("0") and len(digits) > 10:
            digits = digits[1:]

        # If it looks like an Indian 10-digit mobile number, prefix country code.
        if len(digits) == 10:
            digits = "91" + digits

    text = quote(str(message or ""), safe="")

    if digits:
        return f"https://wa.me/{digits}?text={text}"
    return f"https://wa.me/?text={text}"
def _normalize_uuid_for_mysql(value: str) -> str:
    """UUID -> 32hex without hyphens."""
    return (value or "").strip().replace("-", "")


# -----------------------------------------------------------------------------
# MASTER enrollment table discovery (legacy)
# -----------------------------------------------------------------------------

_ENROLLMENT_META_CACHE: Optional[dict] = None
_TABLE_COLUMNS_CACHE: dict[tuple[str, str], list[str]] = {}


def _db_schema_name(conn) -> str:
    """
    Determine current DB/schema name for INFORMATION_SCHEMA queries.
    """
    try:
        # MySQL
        return conn.settings_dict.get("NAME") or ""
    except Exception:
        return ""


def _table_exists(conn, table: str) -> bool:
    schema = _db_schema_name(conn)
    if not schema:
        return False
    sql = """
        SELECT 1
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        LIMIT 1
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [schema, table])
            return cur.fetchone() is not None
    except Exception:
        return False


def _get_table_columns(conn, table: str) -> list[str]:
    schema = _db_schema_name(conn)
    if not schema:
        return []
    cache_key = (schema, str(table or "").lower())
    if cache_key in _TABLE_COLUMNS_CACHE:
        return list(_TABLE_COLUMNS_CACHE[cache_key])
    sql = """
        SELECT COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s
        ORDER BY ORDINAL_POSITION
    """
    with conn.cursor() as cur:
        cur.execute(sql, [schema, table])
        rows = cur.fetchall() or []
    cols = [r[0] for r in rows if r and r[0]]
    _TABLE_COLUMNS_CACHE[cache_key] = cols
    return list(cols)


def _pick_first_column(cols: list[str], candidates: list[str]) -> str:
    """
    Return first candidate that exists in cols (case-insensitive).
    """
    low = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in low:
            return low[cand.lower()]
    return ""


def _get_enrollment_meta() -> dict:
    """
    Legacy discovery path (kept for compatibility).
    This is NOT sufficient for campaign_doctorcampaignenrollment schema,
    but we keep it as a fallback if campaign_* tables are absent.
    """
    global _ENROLLMENT_META_CACHE
    if _ENROLLMENT_META_CACHE is not None:
        return _ENROLLMENT_META_CACHE

    conn = get_master_connection()

    # Default to the known Django table name if present
    candidate_tables = [
        getattr(settings, "MASTER_DB_ENROLLMENT_TABLE", ""),
        "campaign_doctorcampaignenrollment",
        "campaign_doctor_campaigns",
    ]
    candidate_tables = [t for t in candidate_tables if t]

    table = ""
    for t in candidate_tables:
        if _table_exists(conn, t):
            table = t
            break

    if not table:
        # As a last resort, keep old behavior: assume it exists
        table = getattr(settings, "MASTER_DB_ENROLLMENT_TABLE", "campaign_doctorcampaignenrollment")

    cols = _get_table_columns(conn, table)

    # Heuristics
    doctor_col = _pick_first_column(cols, ["doctor_id", "doctor", "redflags_doctor_id", "doctor_code"])
    campaign_col = _pick_first_column(cols, ["campaign_id", "campaign"])
    registered_by_col = _pick_first_column(cols, ["registered_by_id", "registered_by", "field_rep_id"])

    if not doctor_col:
        doctor_col = "doctor_id"
    if not campaign_col:
        campaign_col = "campaign_id"

    _ENROLLMENT_META_CACHE = {
        "table": table,
        "doctor_col": doctor_col,
        "campaign_col": campaign_col,
        "registered_by_col": registered_by_col,
    }
    return _ENROLLMENT_META_CACHE


# -----------------------------------------------------------------------------
# Doctor lookup helpers
# -----------------------------------------------------------------------------

@dataclass
class MasterDoctor:
    doctor_id: str
    email: str
    whatsapp_no: str


def find_doctor_by_email_or_whatsapp(*, email: str, whatsapp_no: str) -> Optional[MasterDoctor]:
    alias = master_alias()
    email = (email or "").strip().lower()
    wa = normalize_wa_for_lookup(whatsapp_no)

    if not email and not wa:
        return None

    qs = RedflagsDoctor.objects.using(alias).all()

    q = Q()
    if email:
        q |= Q(email__iexact=email)
    if wa:
        q |= Q(whatsapp_no__endswith=wa)

    row = qs.filter(q).only("doctor_id", "email", "whatsapp_no").first()
    if not row:
        return None

    return MasterDoctor(
        doctor_id=str(row.doctor_id),
        email=str(row.email or ""),
        whatsapp_no=str(row.whatsapp_no or ""),
    )


# -----------------------------------------------------------------------------
# Doctor create/update in MASTER redflags_doctor
# -----------------------------------------------------------------------------

def create_master_doctor_id() -> str:
    # DR + 6 digits (simple)
    return f"DR{secrets.randbelow(900000) + 100000}"


def insert_redflags_doctor(
    *,
    doctor_id: str,
    first_name: str,
    last_name: str,
    email: str,
    clinic_name: str,
    imc_registration_number: str,
    clinic_phone: str,
    clinic_appointment_number: str,
    clinic_address: str,
    postal_code: str,
    state: str,
    district: str,
    whatsapp_no: str,
    receptionist_whatsapp_number: str,
    photo_path: str,
    field_rep_id: str,
    recruited_via: str,
) -> None:
    conn = get_master_connection()
    table = "redflags_doctor"

    cols = (
        "doctor_id",
        "first_name",
        "last_name",
        "email",
        "clinic_name",
        "imc_registration_number",
        "clinic_phone",
        "clinic_appointment_number",
        "clinic_address",
        "postal_code",
        "state",
        "district",
        "whatsapp_no",
        "receptionist_whatsapp_number",
        "photo",
        "field_rep_id",
        "recruited_via",
    )

    vals = [
        doctor_id,
        first_name,
        last_name,
        email.lower(),
        clinic_name,
        imc_registration_number,
        clinic_phone,
        clinic_appointment_number,
        clinic_address,
        postal_code,
        state,
        district,
        normalize_wa_for_lookup(whatsapp_no) or whatsapp_no,
        normalize_wa_for_lookup(receptionist_whatsapp_number) or receptionist_whatsapp_number,
        photo_path or "",
        field_rep_id or "",
        recruited_via or "FIELD_REP",
    ]

    placeholders = ", ".join(["%s"] * len(cols))
    sql = f"INSERT INTO {qn(table)} ({', '.join(qn(c) for c in cols)}) VALUES ({placeholders})"
    with conn.cursor() as cur:
        cur.execute(sql, vals)
        _log_db("master_db.doctor.insert.ok", doctor_id=doctor_id, rowcount=getattr(cur, "rowcount", None))


# -----------------------------------------------------------------------------
# Campaign enrollment (FIXED)
# -----------------------------------------------------------------------------

def _campaign_exists(conn, campaign_id_norm: str) -> bool:
    """Returns True if campaign exists in MASTER campaign_campaign."""
    cid = (campaign_id_norm or "").strip()
    if not cid:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM {qn('campaign_campaign')} WHERE {qn('id')}=%s LIMIT 1",
                [cid],
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _row_exists_by_id(conn, table: str, row_id: int, *, id_col: str = "id") -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT 1 FROM {qn(table)} WHERE {qn(id_col)}=%s LIMIT 1",
                [int(row_id)],
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def normalize_campaign_id(campaign_id: str) -> str:
    """
    MASTER join tables store campaign_id WITHOUT hyphens:
      7ea0883d97914703b569c1f9f8d25705
    but URLs pass UUID with hyphens:
      7ea0883d-9791-4703-b569-c1f9f8d25705

    Normalize by removing hyphens and trimming.
    """
    return (campaign_id or "").strip().replace("-", "")


def get_campaign_fieldrep_link_fieldrep_id(*, campaign_id: str, link_pk: int) -> Optional[int]:
    """
    Treat `field_rep_id` URL as join-table primary key and resolve to actual field_rep_id.
    """
    conn = get_master_connection()

    table = getattr(settings, "MASTER_DB_CAMPAIGN_FIELD_REP_TABLE", "campaign_campaignfieldrep")
    pk_col = getattr(settings, "MASTER_DB_CAMPAIGN_FIELD_REP_PK_COLUMN", "id")
    campaign_col = getattr(settings, "MASTER_DB_CAMPAIGN_FIELD_REP_CAMPAIGN_COLUMN", "campaign_id")
    fr_col = getattr(settings, "MASTER_DB_CAMPAIGN_FIELD_REP_FIELD_REP_COLUMN", "field_rep_id")

    cid = normalize_campaign_id(campaign_id)
    sql = (
        f"SELECT {qn(fr_col)} "
        f"FROM {qn(table)} "
        f"WHERE {qn(pk_col)} = %s AND {qn(campaign_col)} = %s "
        f"LIMIT 1"
    )

    with conn.cursor() as cur:
        cur.execute(sql, [int(link_pk), cid])
        row = cur.fetchone()

    if not row:
        return None

    try:
        return int(row[0])
    except Exception:
        return None


def _resolve_registered_by_fieldrep_id(conn, *, campaign_id_norm: str, registered_by: str) -> Optional[int]:
    """
    Resolve `registered_by` (from URL/form) to MASTER campaign_fieldrep.id if possible.

    Supported real-world inputs:
      - "15" (fieldrep id OR join-table pk)
      - "fieldrep_15" (token style)
      - "FR09" (brand_supplied_field_rep_id)
    """
    raw = (registered_by or "").strip()
    if not raw:
        return None

    # 0) Direct lookup in campaign_fieldrep (pk or external brand-supplied id)
    try:
        fr = get_field_rep(raw)  # supports pk id, token ids, and brand_supplied_field_rep_id (FR09)
        if fr:
            return int(fr.id)
    except Exception:
        pass

    # Extract trailing digits (handles "fieldrep_15")
    m = re.search(r"(\d+)$", raw)
    if not m:
        return None

    try:
        cand = int(m.group(1))
    except Exception:
        return None

    # 1) direct campaign_fieldrep.id
    if _row_exists_by_id(conn, "campaign_fieldrep", cand, id_col="id"):
        return cand

    # 2) treat as join-table pk in campaign_campaignfieldrep => resolve to field_rep_id
    try:
        fr_id = get_campaign_fieldrep_link_fieldrep_id(campaign_id=campaign_id_norm, link_pk=cand)
    except Exception:
        fr_id = None

    if fr_id and _row_exists_by_id(conn, "campaign_fieldrep", int(fr_id), id_col="id"):
        return int(fr_id)

    return None

    # Extract trailing digits (handles "fieldrep_15")
    m = re.search(r"(\d+)$", raw)
    if not m:
        return None

    try:
        cand = int(m.group(1))
    except Exception:
        return None

    # 1) direct campaign_fieldrep.id
    if _row_exists_by_id(conn, "campaign_fieldrep", cand, id_col="id"):
        return cand

    # 2) treat as join-table pk in campaign_campaignfieldrep => resolve to field_rep_id
    try:
        fr_id = get_campaign_fieldrep_link_fieldrep_id(campaign_id=campaign_id_norm, link_pk=cand)
    except Exception:
        fr_id = None

    if fr_id and _row_exists_by_id(conn, "campaign_fieldrep", int(fr_id), id_col="id"):
        return int(fr_id)

    return None


def _get_or_create_campaign_doctor_id(
    conn,
    *,
    full_name: str,
    email: str,
    phone: str,
    city: str = "",
    state: str = "",
) -> Optional[int]:
    """
    Ensure a row exists in MASTER campaign_doctor and return its numeric id.

    Matching:
      - LOWER(email) exact OR RIGHT(phone, 10) match (handles +91 / 91 prefixes)
    """
    email_l = (email or "").strip().lower()
    phone_digits = re.sub(r"\D", "", str(phone or ""))
    phone_last10 = phone_digits[-10:] if len(phone_digits) > 10 else phone_digits

    if not email_l and not phone_last10:
        return None

    where_parts = []
    params = []

    if email_l:
        where_parts.append(f"LOWER({qn('email')})=%s")
        params.append(email_l)

    if phone_last10:
        where_parts.append(f"RIGHT({qn('phone')}, 10)=%s")
        params.append(phone_last10)

    where_sql = " OR ".join(where_parts)

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {qn('id')} FROM {qn('campaign_doctor')} WHERE {where_sql} ORDER BY {qn('id')} DESC LIMIT 1",
                params,
            )
            row = cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])
    except Exception:
        # fall through to create
        pass

    # Create (best-effort)
    full_name_n = (full_name or "").strip() or (email_l or phone_last10 or "")
    city_n = (city or "").strip()
    state_n = (state or "").strip()

    phone_store = phone_digits or (phone or "").strip()

    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {qn('campaign_doctor')}
                    ({qn('full_name')}, {qn('email')}, {qn('phone')}, {qn('city')}, {qn('state')}, {qn('created_at')})
                VALUES
                    (%s, %s, %s, %s, %s, NOW(6))
                """,
                [full_name_n, email_l, phone_store, city_n, state_n],
            )
            return int(getattr(cur, "lastrowid", 0) or 0) or None
    except Exception:
        return None


def ensure_enrollment(*, doctor_id: str, campaign_id: str, registered_by: str) -> None:
    """
    Ensure a doctor is enrolled into a campaign in MASTER DB.

    MASTER uses:
      1) `redflags_doctor` (login/profile) keyed by string doctor_id (e.g. DR061755)
      2) `campaign_doctor` + `campaign_doctorcampaignenrollment` for campaign membership (doctor_id is BIGINT FK)

    This function:
      - Normalizes campaign_id (UUID -> 32-hex without hyphens)
      - Creates/gets `campaign_doctor` row using redflags doctor email/phone
      - Inserts into `campaign_doctorcampaignenrollment` with required NOT NULL columns
      - Idempotent (won’t create duplicates)

    Fallback:
      - If campaign tables aren't present, uses legacy discovery path (_get_enrollment_meta).
    """
    _log_db("master_db.enrollment.ensure.start", doctor_id=doctor_id, campaign_id=campaign_id)

    if not (doctor_id and campaign_id):
        return

    conn = get_master_connection()
    cid_norm = normalize_campaign_id(campaign_id) or _normalize_uuid_for_mysql(campaign_id)

    # Preferred path: campaign_* tables exist
    try:
        if _table_exists(conn, "campaign_doctor") and _table_exists(conn, "campaign_doctorcampaignenrollment") and _table_exists(conn, "campaign_campaign"):
            if not _campaign_exists(conn, cid_norm):
                _log_db("master_db.enrollment.skip.campaign_missing", doctor_id=doctor_id, campaign_id=cid_norm)
                return

            # Resolve numeric campaign_doctor.id
            campaign_doctor_id: Optional[int] = None

            if str(doctor_id).strip().isdigit():
                campaign_doctor_id = int(str(doctor_id).strip())
                if not _row_exists_by_id(conn, "campaign_doctor", campaign_doctor_id, id_col="id"):
                    campaign_doctor_id = None
            else:
                alias = master_alias()
                doc = (
                    RedflagsDoctor.objects.using(alias)
                    .filter(doctor_id=str(doctor_id).strip())
                    .only("first_name", "last_name", "email", "whatsapp_no", "district", "state")
                    .first()
                )
                if not doc:
                    _log_db("master_db.enrollment.skip.redflags_doctor_missing", doctor_id=doctor_id, campaign_id=cid_norm)
                    return

                full_name = (f"{(doc.first_name or '').strip()} {(doc.last_name or '').strip()}").strip()
                email = (doc.email or "").strip()
                phone = (doc.whatsapp_no or "").strip()
                city = (getattr(doc, "district", "") or "").strip()
                state = (getattr(doc, "state", "") or "").strip()

                campaign_doctor_id = _get_or_create_campaign_doctor_id(
                    conn,
                    full_name=full_name,
                    email=email,
                    phone=phone,
                    city=city,
                    state=state,
                )

            if not campaign_doctor_id:
                _log_db("master_db.enrollment.skip.campaign_doctor_unresolved", doctor_id=doctor_id, campaign_id=cid_norm)
                return

            # Idempotency check
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT 1 FROM {qn('campaign_doctorcampaignenrollment')} WHERE {qn('campaign_id')}=%s AND {qn('doctor_id')}=%s LIMIT 1",
                    [cid_norm, campaign_doctor_id],
                )
                if cur.fetchone() is not None:
                    _log_db("master_db.enrollment.exists", doctor_id=doctor_id, campaign_id=cid_norm)
                    return

            # Insert enrollment row (schema: campaign_doctorcampaignenrollment).
            # We intentionally avoid INFORMATION_SCHEMA dependency here because some DB users
            # do not have permissions for it, but do have INSERT/SELECT permissions.
            fr_id = _resolve_registered_by_fieldrep_id(
                conn, campaign_id_norm=cid_norm, registered_by=registered_by
            )

            try:
                # Full schema (includes registered_by_id)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT IGNORE INTO {qn('campaign_doctorcampaignenrollment')}
                            ({qn('whitelabel_enabled')}, {qn('whitelabel_subdomain')}, {qn('registered_at')},
                             {qn('campaign_id')}, {qn('doctor_id')}, {qn('registered_by_id')})
                        VALUES
                            (%s, %s, NOW(6), %s, %s, %s)
                        """,
                        [1, "", cid_norm, campaign_doctor_id, fr_id],
                    )
            except Exception:
                # Older schema without registered_by_id (still must satisfy NOT NULL columns)
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        INSERT IGNORE INTO {qn('campaign_doctorcampaignenrollment')}
                            ({qn('whitelabel_enabled')}, {qn('whitelabel_subdomain')}, {qn('registered_at')},
                             {qn('campaign_id')}, {qn('doctor_id')})
                        VALUES
                            (%s, %s, NOW(6), %s, %s)
                        """,
                        [1, "", cid_norm, campaign_doctor_id],
                    )

            _log_db(
                "master_db.enrollment.ensure.done",
                doctor_id=doctor_id,
                campaign_id=cid_norm,
                campaign_doctor_id=campaign_doctor_id,
            )
            return
    except Exception:
        _log_db_exc("master_db.enrollment.ensure.error", doctor_id=doctor_id, campaign_id=campaign_id)

    # Fallback path: legacy meta-driven insert
    try:
        meta = _get_enrollment_meta()
        table = meta["table"]
        doctor_col = meta["doctor_col"]
        campaign_col = meta["campaign_col"]
        registered_by_col = meta.get("registered_by_col") or ""

        cid_raw = (campaign_id or "").strip()
        cid_norm = _normalize_uuid_for_mysql(cid_raw)

        cols = [doctor_col, campaign_col]
        vals = [doctor_id, cid_norm]

        if registered_by_col:
            cols.append(registered_by_col)
            vals.append(registered_by or "")

        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"INSERT IGNORE INTO {qn(table)} ({', '.join(qn(c) for c in cols)}) VALUES ({placeholders})"

        with conn.cursor() as cur:
            cur.execute(sql, vals)

        _log_db("master_db.enrollment.ensure.fallback_done", doctor_id=doctor_id, campaign_id=cid_norm)
    except Exception:
        _log_db_exc("master_db.enrollment.ensure.fallback_error", doctor_id=doctor_id, campaign_id=campaign_id)


# -----------------------------------------------------------------------------
# Doctor create with enrollment
# -----------------------------------------------------------------------------

def create_doctor_with_enrollment(
    *,
    doctor_id: str = "",
    first_name: str,
    last_name: str,
    email: str,
    whatsapp_no: str,
    clinic_name: str,
    imc_registration_number: str,
    clinic_phone: str,
    clinic_appointment_number: str,
    clinic_address: str,
    postal_code: str,
    state: str,
    district: str,
    receptionist_whatsapp_number: str,
    photo_path: str,
    campaign_id: str = "",
    registered_by: str = "",
    recruited_via: str = "",
    initial_password_raw: Optional[str] = None,
) -> str:
    """
    Creates doctor in MASTER redflags_doctor and enrolls into campaign tables.
    Returns created doctor_id (e.g. DR123456).

    IMPORTANT (MASTER DB schema alignment):
      - redflags_doctor has several NOT NULL columns without defaults (clinic_password_hash,
        clinic_user1_*, clinic_user2_*). Django model fields allow NULL, so we MUST supply
        values explicitly to avoid IntegrityError.
      - Portal login uses clinic_password_hash; we store a Django hash when
        initial_password_raw is provided.
    """

    alias = master_alias()

    # ------------------------------------------------------------------
    # doctor_id (optional pre-generated) — avoid collisions
    # ------------------------------------------------------------------
    did = (doctor_id or "").strip()
    if not did:
        for _ in range(15):
            cand = create_master_doctor_id()
            try:
                if not RedflagsDoctor.objects.using(alias).filter(doctor_id=cand).exists():
                    did = cand
                    break
            except Exception:
                # If the existence check fails (rare), fall back to the candidate
                did = cand
                break
        if not did:
            did = create_master_doctor_id()

    # ------------------------------------------------------------------
    # Normalize inputs and guarantee NOT NULL columns get non-NULL values
    # ------------------------------------------------------------------
    email_l = (email or "").strip().lower()

    wa = normalize_wa_for_lookup(whatsapp_no) or (whatsapp_no or "").strip()
    rec_wa = normalize_wa_for_lookup(receptionist_whatsapp_number) or (receptionist_whatsapp_number or "").strip()

    campaign_id_s = (campaign_id or "").strip()
    registered_by_s = (registered_by or "").strip()

    recruited_via_s = (recruited_via or "").strip()
    if not recruited_via_s:
        recruited_via_s = "FIELD_REP" if registered_by_s else "SELF"

    # Password handling (MASTER stores clinic_password_hash)
    pwd_hash = ""
    pwd_set_at = None
    if initial_password_raw:
        pwd_hash = make_password(initial_password_raw)
        try:
            pwd_set_at = timezone.now()
        except Exception:
            pwd_set_at = None

    # MASTER schema requires these NOT NULL (empty string is OK)
    user1_name = ""
    user1_email = ""
    user1_pwd = ""
    user2_name = ""
    user2_email = ""
    user2_pwd = ""

    with transaction.atomic(using=alias):
        doc = RedflagsDoctor(
            doctor_id=did,
            first_name=(first_name or "").strip(),
            last_name=(last_name or "").strip(),
            email=email_l,
            whatsapp_no=wa,
            clinic_name=(clinic_name or "").strip(),
            clinic_phone=(clinic_phone or "").strip(),
            clinic_appointment_number=(clinic_appointment_number or "").strip(),
            clinic_address=(clinic_address or "").strip(),
            imc_registration_number=(imc_registration_number or "").strip(),
            photo=(photo_path or "").strip() or None,
            postal_code=(postal_code or "").strip(),
            state=(state or "").strip(),
            district=(district or "").strip(),
            receptionist_whatsapp_number=rec_wa,
            field_rep_id=registered_by_s or "",
            recruited_via=recruited_via_s,
            clinic_password_hash=pwd_hash,
            clinic_password_set_at=pwd_set_at,
            clinic_user1_name=user1_name,
            clinic_user1_email=user1_email,
            clinic_user1_password_hash=user1_pwd,
            clinic_user2_name=user2_name,
            clinic_user2_email=user2_email,
            clinic_user2_password_hash=user2_pwd,
        )
        doc.save(using=alias)

        # Enroll into campaign tables (best-effort; ensure_enrollment never raises by design)
        if campaign_id_s:
            ensure_enrollment(doctor_id=did, campaign_id=campaign_id_s, registered_by=registered_by_s or "")

    return did



# =============================================================================
# Campaign fetch (MASTER DB) — robust + includes banners
# DO NOT MOVE ABOVE: kept at end so it safely overrides any older get_campaign()
# =============================================================================

@dataclass(frozen=True)
class MasterCampaign:
    campaign_id: str
    doctors_supported: int
    wa_addition: str
    new_video_cluster_name: str
    email_registration: str

    # NEW: banner URLs stored in MASTER campaign_campaign
    banner_small_url: str = ""
    banner_large_url: str = ""
    banner_target_url: str = ""


def get_campaign(campaign_id: str) -> Optional[MasterCampaign]:
    """
    Fetch campaign details from MASTER DB (campaign_campaign).

    Must support:
      - UUID with hyphens (9ca882cf-13da-...)
      - 32-hex without hyphens (9ca882cf13da...)

    Must return banner_small_url / banner_large_url / banner_target_url.
    """
    cid_raw = (campaign_id or "").strip()
    if not cid_raw:
        return None

    cid_norm = cid_raw.replace("-", "")

    conn = get_master_connection()

    table = getattr(settings, "MASTER_DB_CAMPAIGN_TABLE", "campaign_campaign")
    id_col = getattr(settings, "MASTER_DB_CAMPAIGN_ID_COLUMN", "id")

    ds_col = getattr(settings, "MASTER_DB_CAMPAIGN_DOCTORS_SUPPORTED_COLUMN", "num_doctors_supported")
    wa_col = getattr(settings, "MASTER_DB_CAMPAIGN_WA_ADDITION_COLUMN", "add_to_campaign_message")
    vc_col = getattr(settings, "MASTER_DB_CAMPAIGN_VIDEO_CLUSTER_COLUMN", "name")
    er_col = getattr(settings, "MASTER_DB_CAMPAIGN_EMAIL_REGISTRATION_COLUMN", "register_message")

    # banner cols are fixed in your schema; allow override via settings if ever needed
    bs_col = getattr(settings, "MASTER_DB_CAMPAIGN_BANNER_SMALL_URL_COLUMN", "banner_small_url")
    bl_col = getattr(settings, "MASTER_DB_CAMPAIGN_BANNER_LARGE_URL_COLUMN", "banner_large_url")
    bt_col = getattr(settings, "MASTER_DB_CAMPAIGN_BANNER_TARGET_URL_COLUMN", "banner_target_url")

    # Some DBs store id as CHAR(32) (no hyphens). We query both.
    sql = (
        f"SELECT {qn(id_col)}, {qn(ds_col)}, {qn(wa_col)}, {qn(vc_col)}, {qn(er_col)}, "
        f"{qn(bs_col)}, {qn(bl_col)}, {qn(bt_col)} "
        f"FROM {qn(table)} "
        f"WHERE {qn(id_col)} = %s OR {qn(id_col)} = %s "
        f"LIMIT 1"
    )

    try:
        with conn.cursor() as cur:
            cur.execute(sql, [cid_norm, cid_raw])
            row = cur.fetchone()
    except Exception as ex:
        _log_db_exc(
            "master_db.get_campaign.error",
            campaign_id=cid_raw,
            campaign_id_norm=cid_norm,
            table=table,
            id_col=id_col,
            error=f"{type(ex).__name__}: {ex}",
        )
        return None

    if not row:
        _log_db(
            "master_db.get_campaign.not_found",
            campaign_id=cid_raw,
            campaign_id_norm=cid_norm,
            table=table,
            id_col=id_col,
        )
        return None

    # row layout matches SELECT order
    try:
        ds_val = int(row[1] or 0)
    except Exception:
        ds_val = 0

    return MasterCampaign(
        campaign_id=str(row[0] or "").strip(),
        doctors_supported=ds_val,
        wa_addition=str(row[2] or ""),
        new_video_cluster_name=str(row[3] or ""),
        email_registration=str(row[4] or ""),
        banner_small_url=str(row[5] or ""),
        banner_large_url=str(row[6] or ""),
        banner_target_url=str(row[7] or ""),
    )



# =============================================================================
# FieldRep fetch (MASTER DB) — robust override
# Appended at end intentionally (does not remove any existing code).
# =============================================================================

@dataclass(frozen=True)
class MasterFieldRep:
    id: int
    full_name: str
    phone_number: str
    is_active: bool
    brand_supplied_field_rep_id: str = ""


def get_field_rep(field_rep_id: str) -> Optional[MasterFieldRep]:
    """
    Robust FieldRep lookup against MASTER DB.

    Supports:
      - numeric pk id (e.g. "12")
      - brand_supplied_field_rep_id (e.g. "FR09")
      - token-style ids (e.g. "fieldrep_12")

    Reads from settings:
      MASTER_DB_FIELD_REP_TABLE (default campaign_fieldrep)
      MASTER_DB_FIELD_REP_PK_COLUMN (default id)
      MASTER_DB_FIELD_REP_ACTIVE_COLUMN (default is_active)
      MASTER_DB_FIELD_REP_FULL_NAME_COLUMN (default full_name)
      MASTER_DB_FIELD_REP_PHONE_COLUMN (default phone_number)
      MASTER_DB_FIELD_REP_EXTERNAL_ID_COLUMN (default brand_supplied_field_rep_id)
    """
    raw = (field_rep_id or "").strip()
    if not raw:
        return None

    # Extract trailing digits from token-style inputs like "fieldrep_12"
    m = re.search(r"(\d+)$", raw)
    numeric_candidate = m.group(1) if m else ""
    is_numeric = raw.isdigit() or bool(numeric_candidate)

    conn = get_master_connection()

    table = getattr(settings, "MASTER_DB_FIELD_REP_TABLE", "campaign_fieldrep")
    pk_col = getattr(settings, "MASTER_DB_FIELD_REP_PK_COLUMN", "id")
    active_col = getattr(settings, "MASTER_DB_FIELD_REP_ACTIVE_COLUMN", "is_active")
    name_col = getattr(settings, "MASTER_DB_FIELD_REP_FULL_NAME_COLUMN", "full_name")
    phone_col = getattr(settings, "MASTER_DB_FIELD_REP_PHONE_COLUMN", "phone_number")
    ext_col = getattr(settings, "MASTER_DB_FIELD_REP_EXTERNAL_ID_COLUMN", "brand_supplied_field_rep_id")

    # 1) Try primary key lookup if numeric
    if is_numeric:
        try:
            pk = int(raw) if raw.isdigit() else int(numeric_candidate)
        except Exception:
            pk = None

        if pk is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        f"""
                        SELECT {qn(pk_col)}, {qn(name_col)}, {qn(phone_col)}, {qn(active_col)}, {qn(ext_col)}
                        FROM {qn(table)}
                        WHERE {qn(pk_col)} = %s
                        LIMIT 1
                        """,
                        [pk],
                    )
                    row = cur.fetchone()
                if row:
                    return MasterFieldRep(
                        id=int(row[0]),
                        full_name=str(row[1] or "").strip(),
                        phone_number=str(row[2] or "").strip(),
                        is_active=bool(int(row[3] or 0)) if str(row[3] or "").isdigit() else bool(row[3]),
                        brand_supplied_field_rep_id=str(row[4] or "").strip(),
                    )
            except Exception as ex:
                _log_db_exc("master_db.get_field_rep.pk_lookup_error", field_rep_id=raw, error=f"{type(ex).__name__}: {ex}")

    # 2) Try external brand-supplied id lookup (FR09 etc)
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {qn(pk_col)}, {qn(name_col)}, {qn(phone_col)}, {qn(active_col)}, {qn(ext_col)}
                FROM {qn(table)}
                WHERE {qn(ext_col)} = %s
                LIMIT 1
                """,
                [raw],
            )
            row = cur.fetchone()
        if row:
            return MasterFieldRep(
                id=int(row[0]),
                full_name=str(row[1] or "").strip(),
                phone_number=str(row[2] or "").strip(),
                is_active=bool(int(row[3] or 0)) if str(row[3] or "").isdigit() else bool(row[3]),
                brand_supplied_field_rep_id=str(row[4] or "").strip(),
            )
    except Exception as ex:
        _log_db_exc("master_db.get_field_rep.external_lookup_error", field_rep_id=raw, error=f"{type(ex).__name__}: {ex}")

    return None

# =============================================================================
# Enrollment count (MASTER DB) — robust override
# Appended at end intentionally (does not remove any existing code).
# =============================================================================

def count_campaign_enrollments(campaign_id: str) -> int:
    """
    Counts enrolled doctors for a campaign in MASTER DB.

    Supports both possible schemas:

    A) New campaigns schema:
       - table: campaign_doctorcampaignenrollment
       - columns: campaign_id (CHAR32), doctor_id (BIGINT FK -> campaign_doctor.id)
       - may optionally have: active

    B) Legacy schema (older admin DB):
       - table: DoctorCampaignEnrollment (or settings.MASTER_DB_ENROLLMENT_TABLE)
       - columns commonly: campaign_id, doctor_id
       - may optionally have: active

    Always returns int, never raises.
    """
    cid_raw = (campaign_id or "").strip()
    if not cid_raw:
        return 0

    # Normalize to 32-char (no hyphens) for campaign tables that store char32 IDs
    cid_norm = cid_raw.replace("-", "")

    conn = get_master_connection()

    # Prefer the actual campaign enrollment table if present
    preferred = "campaign_doctorcampaignenrollment"
    configured = getattr(settings, "MASTER_DB_ENROLLMENT_TABLE", "") or ""
    candidates = [preferred]
    if configured and configured not in candidates:
        candidates.append(configured)

    # Fallbacks you might have in older DBs
    for t in ("DoctorCampaignEnrollment", "campaign_doctor_campaigns"):
        if t not in candidates:
            candidates.append(t)

    table = None
    for t in candidates:
        try:
            if _table_exists(conn, t):
                table = t
                break
        except Exception:
            continue

    if not table:
        _log_db("master_db.count_campaign_enrollments.no_table", campaign_id=cid_raw)
        return 0

    # Identify columns safely (case-insensitive)
    try:
        cols = _get_table_columns(conn, table)
        cols_l = {c.lower(): c for c in cols}
    except Exception:
        cols = []
        cols_l = {}

    campaign_col = cols_l.get("campaign_id") or getattr(settings, "MASTER_DB_ENROLLMENT_CAMPAIGN_COLUMN", "campaign_id")
    doctor_col = cols_l.get("doctor_id") or getattr(settings, "MASTER_DB_ENROLLMENT_DOCTOR_COLUMN", "doctor_id")

    # Optional active column
    active_col = cols_l.get("active")

    # Build WHERE: try both cid_norm and cid_raw because some tables store hyphenated UUIDs
    where = f"{qn(campaign_col)} = %s OR {qn(campaign_col)} = %s"
    params = [cid_norm, cid_raw]

    if active_col:
        where = f"({where}) AND {qn(active_col)} = 1"

    # Count distinct doctors
    sql = f"""
        SELECT COUNT(DISTINCT {qn(doctor_col)})
        FROM {qn(table)}
        WHERE {where}
    """

    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return int(row[0] or 0) if row else 0
    except Exception as ex:
        _log_db_exc(
            "master_db.count_campaign_enrollments.error",
            table=table,
            campaign_id=cid_raw,
            campaign_id_norm=cid_norm,
            error=f"{type(ex).__name__}: {ex}",
        )
        return 0

# =============================================================================
# Doctor lookup by WhatsApp (MASTER DB) — robust override
# Appended at end intentionally (does not remove any existing code).
# =============================================================================

@dataclass(frozen=True)
class MasterDoctorLite:
    doctor_id: str
    email: str
    full_name: str
    whatsapp_no: str


def get_doctor_by_whatsapp(whatsapp_number: str) -> Optional[MasterDoctorLite]:
    """
    Looks up doctor in MASTER redflags_doctor by WhatsApp number.

    - Normalizes to digits and matches by last-10 digits (handles +91/91 prefix).
    - Uses settings MASTER_DB_DOCTOR_TABLE + column names if provided, else defaults to redflags_doctor schema.
    - Never raises; returns None on not found.
    """
    raw = (whatsapp_number or "").strip()
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    last10 = digits[-10:] if len(digits) > 10 else digits

    conn = get_master_connection()

    # Your live schema is redflags_doctor (as per your settings bottom block)
    table = getattr(settings, "MASTER_DB_DOCTOR_TABLE", "redflags_doctor")
    id_col = getattr(settings, "MASTER_DB_DOCTOR_ID_COLUMN", "doctor_id")
    fn_col = getattr(settings, "MASTER_DB_DOCTOR_FIRST_NAME_COLUMN", "first_name")
    ln_col = getattr(settings, "MASTER_DB_DOCTOR_LAST_NAME_COLUMN", "last_name")
    email_col = getattr(settings, "MASTER_DB_DOCTOR_EMAIL_COLUMN", "email")
    wa_col = getattr(settings, "MASTER_DB_DOCTOR_WHATSAPP_COLUMN", "whatsapp_no")

    # We match on RIGHT(whatsapp_no,10) to tolerate stored +91/91 prefixes or longer numbers.
    sql = f"""
        SELECT {qn(id_col)}, {qn(fn_col)}, {qn(ln_col)}, {qn(email_col)}, {qn(wa_col)}
        FROM {qn(table)}
        WHERE RIGHT({qn(wa_col)}, 10) = %s
           OR {qn(wa_col)} = %s
        LIMIT 1
    """

    try:
        with conn.cursor() as cur:
            cur.execute(sql, [last10, digits])
            row = cur.fetchone()
    except Exception as ex:
        _log_db_exc(
            "master_db.get_doctor_by_whatsapp.error",
            table=table,
            whatsapp_last10=last10,
            error=f"{type(ex).__name__}: {ex}",
        )
        return None

    if not row:
        return None

    doctor_id = str(row[0] or "").strip()
    first = str(row[1] or "").strip()
    last = str(row[2] or "").strip()
    email = str(row[3] or "").strip()
    wa = str(row[4] or "").strip()

    full_name = (f"{first} {last}").strip() or doctor_id or "Doctor"

    return MasterDoctorLite(
        doctor_id=doctor_id,
        email=email,
        full_name=full_name,
        whatsapp_no=wa,
    )


def _split_grouped_values(raw_value: str) -> tuple[str, ...]:
    if not raw_value:
        return ()
    items = []
    seen = set()
    for chunk in str(raw_value).split(","):
        value = chunk.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        items.append(value)
    return tuple(items)


@dataclass(frozen=True)
class MasterFieldRepRecord:
    id: int
    full_name: str
    phone_number: str
    brand_supplied_field_rep_id: str
    is_active: bool
    state: str
    brand_id: Optional[int]
    user_id: Optional[int]
    created_at: object
    updated_at: object
    linked_campaign_ids: tuple[str, ...] = ()


def list_field_rep_records(search: str = "") -> list[MasterFieldRepRecord]:
    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_FIELD_REP_TABLE", "campaign_fieldrep")
    join_table = getattr(settings, "MASTER_DB_CAMPAIGN_FIELD_REP_TABLE", "campaign_campaignfieldrep")
    cols = _get_table_columns(conn, table)
    join_cols = _get_table_columns(conn, join_table)
    id_col = _pick_first_column(cols, ["id"])
    name_col = _pick_first_column(cols, ["full_name", "name"])
    phone_col = _pick_first_column(cols, ["phone_number", "phone"])
    external_id_col = _pick_first_column(cols, ["brand_supplied_field_rep_id", "external_id", "field_rep_id"])
    active_col = _pick_first_column(cols, ["is_active", "active"])
    state_col = _pick_first_column(cols, ["state"])
    brand_col = _pick_first_column(cols, ["brand_id"])
    user_col = _pick_first_column(cols, ["user_id"])
    created_col = _pick_first_column(cols, ["created_at"])
    updated_col = _pick_first_column(cols, ["updated_at"])
    join_field_rep_col = _pick_first_column(join_cols, ["field_rep_id"])
    join_campaign_col = _pick_first_column(join_cols, ["campaign_id"])

    if not id_col:
        return []

    state_expr = qcol("fr", state_col) if state_col else "''"
    brand_expr = qcol("fr", brand_col) if brand_col else "NULL"
    user_expr = qcol("fr", user_col) if user_col else "NULL"
    created_expr = qcol("fr", created_col) if created_col else "NULL"
    updated_expr = qcol("fr", updated_col) if updated_col else created_expr
    name_expr = qcol("fr", name_col) if name_col else "''"
    phone_expr = qcol("fr", phone_col) if phone_col else "''"
    external_id_expr = qcol("fr", external_id_col) if external_id_col else "''"
    active_expr = qcol("fr", active_col) if active_col else "1"
    linked_campaign_expr = (
        f"GROUP_CONCAT(DISTINCT {qcol('cfr', join_campaign_col)} ORDER BY {qcol('cfr', join_campaign_col)} SEPARATOR ',')"
        if join_campaign_col
        else "NULL"
    )

    where_sql = ""
    params: list[object] = []
    term = (search or "").strip().lower()
    if term:
        like = f"%{term}%"
        search_parts = []
        if name_col:
            search_parts.append("LOWER(COALESCE({0}, '')) LIKE %s".format(name_expr))
            params.append(like)
        if phone_col:
            search_parts.append("LOWER(COALESCE({0}, '')) LIKE %s".format(phone_expr))
            params.append(like)
        if external_id_col:
            search_parts.append("LOWER(COALESCE({0}, '')) LIKE %s".format(external_id_expr))
            params.append(like)
        if join_campaign_col:
            search_parts.append("LOWER(COALESCE({0}, '')) LIKE %s".format(qcol("cfr", join_campaign_col)))
            params.append(like)
        if state_col:
            search_parts.append("LOWER(COALESCE({0}, '')) LIKE %s".format(state_expr))
            params.append(like)
        if search_parts:
            where_sql = f"""
                WHERE (
                    {" OR ".join(search_parts)}
                )
            """

    sql = f"""
        SELECT
            {qcol('fr', id_col)},
            {name_expr},
            {phone_expr},
            {external_id_expr},
            {active_expr},
            {state_expr},
            {brand_expr},
            {user_expr},
            {created_expr},
            {updated_expr},
            {linked_campaign_expr} AS linked_campaign_ids
        FROM {qn(table)} fr
        {"LEFT JOIN " + qn(join_table) + " cfr ON " + qcol('cfr', join_field_rep_col) + " = " + qcol('fr', id_col) if join_field_rep_col and join_campaign_col else ""}
        {where_sql}
        GROUP BY
            {qcol('fr', id_col)},
            {name_expr},
            {phone_expr},
            {external_id_expr},
            {active_expr},
            {state_expr},
            {brand_expr},
            {user_expr},
            {created_expr},
            {updated_expr}
        ORDER BY {updated_expr} DESC, {qcol('fr', id_col)} DESC
    """

    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall() or []

    records: list[MasterFieldRepRecord] = []
    for row in rows:
        records.append(
            MasterFieldRepRecord(
                id=int(row[0]),
                full_name=str(row[1] or "").strip(),
                phone_number=str(row[2] or "").strip(),
                brand_supplied_field_rep_id=str(row[3] or "").strip(),
                is_active=bool(int(row[4] or 0)) if str(row[4] or "").isdigit() else bool(row[4]),
                state=str(row[5] or "").strip(),
                brand_id=int(row[6]) if row[6] is not None else None,
                user_id=int(row[7]) if row[7] is not None else None,
                created_at=row[8],
                updated_at=row[9],
                linked_campaign_ids=_split_grouped_values(row[10]),
            )
        )
    return records


def get_field_rep_record(field_rep_id) -> Optional[MasterFieldRepRecord]:
    raw = str(field_rep_id or "").strip()
    if not raw.isdigit():
        return None
    target = int(raw)
    for record in list_field_rep_records():
        if record.id == target:
            return record
    return None


def update_field_rep_record(field_rep_id, *, full_name: str, phone_number: str, brand_supplied_field_rep_id: str, state: str, is_active: bool) -> None:
    raw = str(field_rep_id or "").strip()
    if not raw.isdigit():
        raise ValueError("Invalid field rep id.")

    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_FIELD_REP_TABLE", "campaign_fieldrep")
    cols = _get_table_columns(conn, table)
    id_col = _pick_first_column(cols, ["id"])
    name_col = _pick_first_column(cols, ["full_name", "name"])
    phone_col = _pick_first_column(cols, ["phone_number", "phone"])
    external_id_col = _pick_first_column(cols, ["brand_supplied_field_rep_id", "external_id", "field_rep_id"])
    active_col = _pick_first_column(cols, ["is_active", "active"])
    state_col = _pick_first_column(cols, ["state"])
    updated_col = _pick_first_column(cols, ["updated_at"])
    now = timezone.now()
    if not id_col:
        raise ValueError("Field rep table is missing its primary key column.")

    assignments = []
    if name_col:
        assignments.append((qn(name_col), str(full_name or "").strip()))
    if phone_col:
        assignments.append((qn(phone_col), str(phone_number or "").strip()))
    if external_id_col:
        assignments.append((qn(external_id_col), str(brand_supplied_field_rep_id or "").strip()))
    if active_col:
        assignments.append((qn(active_col), 1 if is_active else 0))
    if state_col:
        assignments.append((qn(state_col), str(state or "").strip()))
    if updated_col:
        assignments.append((qn(updated_col), now))
    if not assignments:
        return

    set_sql = ", ".join([f"{col} = %s" for col, _ in assignments])
    params = [value for _, value in assignments] + [int(raw)]

    with transaction.atomic(using=master_alias()):
        with conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {qn(table)}
                SET
                    {set_sql}
                WHERE {qn(id_col)} = %s
                """,
                params,
            )


def delete_field_rep_record(field_rep_id) -> None:
    raw = str(field_rep_id or "").strip()
    if not raw.isdigit():
        raise ValueError("Invalid field rep id.")

    conn = get_master_connection()
    field_rep_table = getattr(settings, "MASTER_DB_FIELD_REP_TABLE", "campaign_fieldrep")
    join_table = getattr(settings, "MASTER_DB_CAMPAIGN_FIELD_REP_TABLE", "campaign_campaignfieldrep")
    enrollment_table = "campaign_doctorcampaignenrollment"
    field_rep_cols = _get_table_columns(conn, field_rep_table)
    join_cols = _get_table_columns(conn, join_table)
    enrollment_cols = _get_table_columns(conn, enrollment_table)
    field_rep_id_col = _pick_first_column(field_rep_cols, ["id"])
    join_field_rep_col = _pick_first_column(join_cols, ["field_rep_id"])
    enrollment_registered_by_col = _pick_first_column(enrollment_cols, ["registered_by_id", "registered_by", "field_rep_id"])

    with transaction.atomic(using=master_alias()):
        with conn.cursor() as cur:
            if enrollment_registered_by_col:
                cur.execute(
                    f"""
                    UPDATE {qn(enrollment_table)}
                    SET {qn(enrollment_registered_by_col)} = NULL
                    WHERE {qn(enrollment_registered_by_col)} = %s
                    """,
                    [int(raw)],
                )
            if join_field_rep_col:
                cur.execute(
                    f"DELETE FROM {qn(join_table)} WHERE {qn(join_field_rep_col)} = %s",
                    [int(raw)],
                )
            if field_rep_id_col:
                cur.execute(
                    f"DELETE FROM {qn(field_rep_table)} WHERE {qn(field_rep_id_col)} = %s",
                    [int(raw)],
                )


@dataclass(frozen=True)
class MasterDoctorRecord:
    doctor_id: str
    first_name: str
    last_name: str
    email: str
    whatsapp_no: str
    clinic_name: str
    clinic_phone: str
    clinic_appointment_number: str
    clinic_address: str
    postal_code: str
    state: str
    district: str
    receptionist_whatsapp_number: str
    imc_registration_number: str
    field_rep_id: str
    recruited_via: str
    clinic_user1_name: str
    clinic_user1_email: str
    clinic_user2_name: str
    clinic_user2_email: str
    created_at: object
    linked_campaign_ids: tuple[str, ...] = ()

    @property
    def full_name(self) -> str:
        return (f"{self.first_name} {self.last_name}").strip() or self.doctor_id


def _phone_lookup_tokens(*values: str) -> set[str]:
    tokens: set[str] = set()
    for raw in values:
        text = str(raw or "").strip()
        if text:
            tokens.add(text)

        digits = re.sub(r"\D", "", text)
        if not digits:
            continue
        tokens.add(digits)
        if len(digits) > 10:
            tokens.add(digits[-10:])
    return tokens


def _fetch_master_doctor_rows(conn) -> list[dict[str, object]]:
    doctor_table = getattr(settings, "MASTER_DB_DOCTOR_TABLE", "redflags_doctor")
    cols = _get_table_columns(conn, doctor_table)

    field_candidates = [
        ("doctor_id", ["doctor_id"], "''"),
        ("first_name", ["first_name"], "''"),
        ("last_name", ["last_name"], "''"),
        ("email", ["email"], "''"),
        ("whatsapp_no", ["whatsapp_no"], "''"),
        ("clinic_name", ["clinic_name"], "''"),
        ("clinic_phone", ["clinic_phone"], "''"),
        ("clinic_appointment_number", ["clinic_appointment_number"], "''"),
        ("clinic_address", ["clinic_address"], "''"),
        ("postal_code", ["postal_code"], "''"),
        ("state", ["state"], "''"),
        ("district", ["district"], "''"),
        ("receptionist_whatsapp_number", ["receptionist_whatsapp_number"], "''"),
        ("imc_registration_number", ["imc_registration_number"], "''"),
        ("field_rep_id", ["field_rep_id"], "''"),
        ("recruited_via", ["recruited_via"], "''"),
        ("clinic_user1_name", ["clinic_user1_name"], "''"),
        ("clinic_user1_email", ["clinic_user1_email"], "''"),
        ("clinic_user2_name", ["clinic_user2_name"], "''"),
        ("clinic_user2_email", ["clinic_user2_email"], "''"),
        ("created_at", ["created_at"], "NULL"),
    ]

    select_parts: list[str] = []
    row_keys: list[str] = []
    for key, candidates, default_sql in field_candidates:
        col = _pick_first_column(cols, candidates)
        expr = qcol("rd", col) if col else default_sql
        select_parts.append(f"{expr} AS {qn(key)}")
        row_keys.append(key)

    order_col = _pick_first_column(cols, ["created_at"]) or _pick_first_column(cols, ["doctor_id"])
    order_expr = qcol("rd", order_col) if order_col else "1"

    sql = f"""
        SELECT
            {", ".join(select_parts)}
        FROM {qn(doctor_table)} rd
        ORDER BY {order_expr} DESC
    """

    with conn.cursor() as cur:
        cur.execute(sql)
        rows = cur.fetchall() or []

    return [dict(zip(row_keys, row)) for row in rows]


def _resolve_campaign_doctor_ids_for_doctor_rows(conn, doctor_rows: list[dict[str, object]]) -> dict[str, list[int]]:
    mapping: dict[str, list[int]] = {}
    if not doctor_rows:
        return mapping

    table = "campaign_doctor"
    cols = _get_table_columns(conn, table)
    id_col = _pick_first_column(cols, ["id"])
    doctor_id_col = _pick_first_column(cols, ["doctor_id"])
    email_col = _pick_first_column(cols, ["email"])
    phone_col = _pick_first_column(cols, ["phone"])

    if not id_col:
        return mapping

    if doctor_id_col:
        doctor_ids = [str(row.get("doctor_id") or "").strip() for row in doctor_rows if str(row.get("doctor_id") or "").strip()]
        if not doctor_ids:
            return mapping

        placeholders = ", ".join(["%s"] * len(doctor_ids))
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {qn(id_col)}, {qn(doctor_id_col)}
                FROM {qn(table)}
                WHERE {qn(doctor_id_col)} IN ({placeholders})
                """,
                doctor_ids,
            )
            rows = cur.fetchall() or []

        for row in rows:
            doctor_id = str(row[1] or "").strip()
            if not doctor_id:
                continue
            mapping.setdefault(doctor_id, []).append(int(row[0]))
        return mapping

    select_parts = [qn(id_col)]
    if email_col:
        select_parts.append(qn(email_col))
    else:
        select_parts.append("''")
    if phone_col:
        select_parts.append(qn(phone_col))
    else:
        select_parts.append("''")

    with conn.cursor() as cur:
        cur.execute(f"SELECT {', '.join(select_parts)} FROM {qn(table)}")
        campaign_rows = cur.fetchall() or []

    email_to_doctor_ids: dict[str, set[str]] = {}
    phone_to_doctor_ids: dict[str, set[str]] = {}
    for row in doctor_rows:
        doctor_id = str(row.get("doctor_id") or "").strip()
        if not doctor_id:
            continue

        email = str(row.get("email") or "").strip().lower()
        if email:
            email_to_doctor_ids.setdefault(email, set()).add(doctor_id)

        for token in _phone_lookup_tokens(
            str(row.get("whatsapp_no") or ""),
            str(row.get("receptionist_whatsapp_number") or ""),
            str(row.get("clinic_appointment_number") or ""),
            str(row.get("clinic_phone") or ""),
        ):
            phone_to_doctor_ids.setdefault(token, set()).add(doctor_id)

    for row in campaign_rows:
        campaign_doctor_id = int(row[0])
        matched_doctor_ids: set[str] = set()

        email = str(row[1] or "").strip().lower()
        if email and email in email_to_doctor_ids:
            matched_doctor_ids.update(email_to_doctor_ids[email])

        for token in _phone_lookup_tokens(str(row[2] or "")):
            if token in phone_to_doctor_ids:
                matched_doctor_ids.update(phone_to_doctor_ids[token])

        for doctor_id in matched_doctor_ids:
            mapping.setdefault(doctor_id, []).append(campaign_doctor_id)

    return mapping


def _fetch_enrollment_map(conn, campaign_doctor_ids: list[int]) -> dict[int, tuple[str, ...]]:
    if not campaign_doctor_ids:
        return {}

    table = "campaign_doctorcampaignenrollment"
    cols = _get_table_columns(conn, table)
    doctor_id_col = _pick_first_column(cols, ["doctor_id"])
    campaign_id_col = _pick_first_column(cols, ["campaign_id"])
    if not doctor_id_col or not campaign_id_col:
        return {}

    placeholders = ", ".join(["%s"] * len(campaign_doctor_ids))
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {qn(doctor_id_col)}, {qn(campaign_id_col)}
            FROM {qn(table)}
            WHERE {qn(doctor_id_col)} IN ({placeholders})
            ORDER BY {qn(doctor_id_col)}, {qn(campaign_id_col)}
            """,
            campaign_doctor_ids,
        )
        rows = cur.fetchall() or []

    mapping: dict[int, list[str]] = {}
    for row in rows:
        campaign_doctor_id = int(row[0])
        campaign_id = str(row[1] or "").strip()
        if not campaign_id:
            continue
        mapping.setdefault(campaign_doctor_id, [])
        if campaign_id not in mapping[campaign_doctor_id]:
            mapping[campaign_doctor_id].append(campaign_id)

    return {key: tuple(value) for key, value in mapping.items()}


def _doctor_record_matches_search(record: MasterDoctorRecord, term: str) -> bool:
    haystacks = [
        record.doctor_id,
        record.first_name,
        record.last_name,
        record.full_name,
        record.email,
        record.whatsapp_no,
        record.clinic_name,
        record.clinic_phone,
        record.clinic_appointment_number,
        record.clinic_address,
        record.postal_code,
        record.state,
        record.district,
        record.receptionist_whatsapp_number,
        record.imc_registration_number,
        record.field_rep_id,
        record.recruited_via,
        record.clinic_user1_name,
        record.clinic_user1_email,
        record.clinic_user2_name,
        record.clinic_user2_email,
    ]
    haystacks.extend(list(record.linked_campaign_ids))
    lowered = term.lower()
    return any(lowered in str(value or "").lower() for value in haystacks)


def _doctor_record_to_lookup_row(record: MasterDoctorRecord) -> dict[str, object]:
    return {
        "doctor_id": record.doctor_id,
        "email": record.email,
        "whatsapp_no": record.whatsapp_no,
        "receptionist_whatsapp_number": record.receptionist_whatsapp_number,
        "clinic_appointment_number": record.clinic_appointment_number,
        "clinic_phone": record.clinic_phone,
    }


def list_doctor_records(search: str = "") -> list[MasterDoctorRecord]:
    conn = get_master_connection()
    doctor_rows = _fetch_master_doctor_rows(conn)
    campaign_doctor_ids_by_doctor = _resolve_campaign_doctor_ids_for_doctor_rows(conn, doctor_rows)
    enrollment_map = _fetch_enrollment_map(
        conn,
        sorted({campaign_doctor_id for values in campaign_doctor_ids_by_doctor.values() for campaign_doctor_id in values}),
    )

    records: list[MasterDoctorRecord] = []
    for row in doctor_rows:
        doctor_id = str(row.get("doctor_id") or "").strip()
        linked_campaign_ids: list[str] = []
        for campaign_doctor_id in campaign_doctor_ids_by_doctor.get(doctor_id, []):
            for campaign_id in enrollment_map.get(campaign_doctor_id, ()):
                if campaign_id not in linked_campaign_ids:
                    linked_campaign_ids.append(campaign_id)

        record = MasterDoctorRecord(
            doctor_id=doctor_id,
            first_name=str(row.get("first_name") or "").strip(),
            last_name=str(row.get("last_name") or "").strip(),
            email=str(row.get("email") or "").strip().lower(),
            whatsapp_no=str(row.get("whatsapp_no") or "").strip(),
            clinic_name=str(row.get("clinic_name") or "").strip(),
            clinic_phone=str(row.get("clinic_phone") or "").strip(),
            clinic_appointment_number=str(row.get("clinic_appointment_number") or "").strip(),
            clinic_address=str(row.get("clinic_address") or "").strip(),
            postal_code=str(row.get("postal_code") or "").strip(),
            state=str(row.get("state") or "").strip(),
            district=str(row.get("district") or "").strip(),
            receptionist_whatsapp_number=str(row.get("receptionist_whatsapp_number") or "").strip(),
            imc_registration_number=str(row.get("imc_registration_number") or "").strip(),
            field_rep_id=str(row.get("field_rep_id") or "").strip(),
            recruited_via=str(row.get("recruited_via") or "").strip(),
            clinic_user1_name=str(row.get("clinic_user1_name") or "").strip(),
            clinic_user1_email=str(row.get("clinic_user1_email") or "").strip().lower(),
            clinic_user2_name=str(row.get("clinic_user2_name") or "").strip(),
            clinic_user2_email=str(row.get("clinic_user2_email") or "").strip().lower(),
            created_at=row.get("created_at"),
            linked_campaign_ids=tuple(linked_campaign_ids),
        )
        records.append(record)

    term = (search or "").strip().lower()
    if term:
        records = [record for record in records if _doctor_record_matches_search(record, term)]

    return records


def get_doctor_record(doctor_id: str) -> Optional[MasterDoctorRecord]:
    target = str(doctor_id or "").strip()
    if not target:
        return None
    for record in list_doctor_records():
        if record.doctor_id == target:
            return record
    return None


def update_doctor_record(
    doctor_id: str,
    *,
    first_name: str,
    last_name: str,
    email: str,
    whatsapp_no: str,
    clinic_name: str,
    clinic_phone: str,
    clinic_appointment_number: str,
    clinic_address: str,
    postal_code: str,
    state: str,
    district: str,
    receptionist_whatsapp_number: str,
    imc_registration_number: str,
    field_rep_id: str,
    recruited_via: str,
    clinic_user1_name: str,
    clinic_user1_email: str,
    clinic_user2_name: str,
    clinic_user2_email: str,
) -> None:
    target = str(doctor_id or "").strip()
    if not target:
        raise ValueError("Invalid doctor id.")

    conn = get_master_connection()
    doctor_table = getattr(settings, "MASTER_DB_DOCTOR_TABLE", "redflags_doctor")
    campaign_doctor_table = "campaign_doctor"
    doctor_cols = _get_table_columns(conn, doctor_table)
    campaign_doctor_cols = _get_table_columns(conn, campaign_doctor_table)
    doctor_id_col = _pick_first_column(doctor_cols, ["doctor_id"])
    campaign_doctor_id_col = _pick_first_column(campaign_doctor_cols, ["id"])
    existing_record = get_doctor_record(target)
    full_name = (f"{first_name} {last_name}").strip() or target
    campaign_phone = (
        str(whatsapp_no or "").strip()
        or str(receptionist_whatsapp_number or "").strip()
        or str(clinic_appointment_number or "").strip()
    )
    campaign_doctor_ids: list[int] = []
    if existing_record is not None:
        campaign_doctor_ids = _resolve_campaign_doctor_ids_for_doctor_rows(
            conn,
            [_doctor_record_to_lookup_row(existing_record)],
        ).get(target, [])

    doctor_assignments = []
    for col_name, value in [
        ("first_name", str(first_name or "").strip()),
        ("last_name", str(last_name or "").strip()),
        ("email", str(email or "").strip().lower()),
        ("whatsapp_no", str(whatsapp_no or "").strip()),
        ("clinic_name", str(clinic_name or "").strip()),
        ("clinic_phone", str(clinic_phone or "").strip()),
        ("clinic_appointment_number", str(clinic_appointment_number or "").strip()),
        ("clinic_address", str(clinic_address or "").strip()),
        ("postal_code", str(postal_code or "").strip()),
        ("state", str(state or "").strip()),
        ("district", str(district or "").strip()),
        ("receptionist_whatsapp_number", str(receptionist_whatsapp_number or "").strip()),
        ("imc_registration_number", str(imc_registration_number or "").strip()),
        ("field_rep_id", str(field_rep_id or "").strip()),
        ("recruited_via", str(recruited_via or "").strip()),
        ("clinic_user1_name", str(clinic_user1_name or "").strip()),
        ("clinic_user1_email", str(clinic_user1_email or "").strip().lower()),
        ("clinic_user2_name", str(clinic_user2_name or "").strip()),
        ("clinic_user2_email", str(clinic_user2_email or "").strip().lower()),
    ]:
        actual_col = _pick_first_column(doctor_cols, [col_name])
        if actual_col:
            doctor_assignments.append((actual_col, value))

    with transaction.atomic(using=master_alias()):
        with conn.cursor() as cur:
            if doctor_assignments and doctor_id_col:
                set_sql = ", ".join([f"{qn(col)} = %s" for col, _ in doctor_assignments])
                cur.execute(
                    f"""
                    UPDATE {qn(doctor_table)}
                    SET {set_sql}
                    WHERE {qn(doctor_id_col)} = %s
                    """,
                    [value for _, value in doctor_assignments] + [target],
                )

            if not campaign_doctor_ids:
                campaign_doctor_ids = _resolve_campaign_doctor_ids_for_doctor_rows(
                    conn,
                    [
                        {
                            "doctor_id": target,
                            "email": str(email or "").strip().lower(),
                            "whatsapp_no": str(whatsapp_no or "").strip(),
                            "receptionist_whatsapp_number": str(receptionist_whatsapp_number or "").strip(),
                            "clinic_appointment_number": str(clinic_appointment_number or "").strip(),
                            "clinic_phone": str(clinic_phone or "").strip(),
                        }
                    ],
                ).get(target, [])

            campaign_assignments = []
            for col_name, value in [
                ("full_name", full_name),
                ("email", str(email or "").strip().lower()),
                ("phone", campaign_phone),
                ("city", str(district or "").strip()),
                ("state", str(state or "").strip()),
            ]:
                actual_col = _pick_first_column(campaign_doctor_cols, [col_name])
                if actual_col:
                    campaign_assignments.append((actual_col, value))

            if campaign_doctor_ids and campaign_assignments and campaign_doctor_id_col:
                placeholders = ", ".join(["%s"] * len(campaign_doctor_ids))
                set_sql = ", ".join([f"{qn(col)} = %s" for col, _ in campaign_assignments])
                cur.execute(
                    f"""
                    UPDATE {qn(campaign_doctor_table)}
                    SET {set_sql}
                    WHERE {qn(campaign_doctor_id_col)} IN ({placeholders})
                    """,
                    [value for _, value in campaign_assignments] + campaign_doctor_ids,
                )


def delete_doctor_record(doctor_id: str) -> None:
    target = str(doctor_id or "").strip()
    if not target:
        raise ValueError("Invalid doctor id.")

    conn = get_master_connection()
    doctor_table = getattr(settings, "MASTER_DB_DOCTOR_TABLE", "redflags_doctor")
    campaign_doctor_table = "campaign_doctor"
    enrollment_table = "campaign_doctorcampaignenrollment"
    doctor_cols = _get_table_columns(conn, doctor_table)
    campaign_doctor_cols = _get_table_columns(conn, campaign_doctor_table)
    enrollment_cols = _get_table_columns(conn, enrollment_table)
    doctor_id_col = _pick_first_column(doctor_cols, ["doctor_id"])
    campaign_doctor_id_col = _pick_first_column(campaign_doctor_cols, ["id"])
    enrollment_doctor_col = _pick_first_column(enrollment_cols, ["doctor_id"])
    existing_record = get_doctor_record(target)
    campaign_doctor_ids: list[int] = []
    if existing_record is not None:
        campaign_doctor_ids = _resolve_campaign_doctor_ids_for_doctor_rows(
            conn,
            [_doctor_record_to_lookup_row(existing_record)],
        ).get(target, [])

    with transaction.atomic(using=master_alias()):
        with conn.cursor() as cur:
            if campaign_doctor_ids and campaign_doctor_id_col:
                placeholders = ", ".join(["%s"] * len(campaign_doctor_ids))
                if enrollment_doctor_col:
                    cur.execute(
                        f"DELETE FROM {qn(enrollment_table)} WHERE {qn(enrollment_doctor_col)} IN ({placeholders})",
                        campaign_doctor_ids,
                    )
                cur.execute(
                    f"DELETE FROM {qn(campaign_doctor_table)} WHERE {qn(campaign_doctor_id_col)} IN ({placeholders})",
                    campaign_doctor_ids,
                )

            if doctor_id_col:
                cur.execute(
                    f"DELETE FROM {qn(doctor_table)} WHERE {qn(doctor_id_col)} = %s",
                    [target],
                )

# -----------------------------------------------------------------------------
# Compatibility aliases (do NOT remove)
# -----------------------------------------------------------------------------

# Keep a local fallback generator so registration never fails because of an import issue.
try:
    from peds_edu.master_db import generate_temporary_password as _gen_tmp_pwd  # type: ignore
except Exception:
    _gen_tmp_pwd = None


def generate_temporary_password(length: int = 10) -> str:
    if _gen_tmp_pwd:
        try:
            return _gen_tmp_pwd(length=length)
        except Exception:
            pass

    # Fallback: excludes ambiguous characters for phone dictation.
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    try:
        n = max(8, int(length))
    except Exception:
        n = 10
    return "".join(secrets.choice(alphabet) for _ in range(n))


def generate_doctor_id() -> str:
    return create_master_doctor_id()


# Preserve the core implementation before overriding the public name below.
_create_doctor_with_enrollment_impl = create_doctor_with_enrollment


def create_doctor_with_enrollment_compat(**kwargs) -> str:
    """Backwards/forwards compatible wrapper for create_doctor_with_enrollment()."""
    rec_wa = (
        (kwargs.get("receptionist_whatsapp_number") or "").strip()
        or (kwargs.get("clinic_whatsapp_number") or "").strip()
        or (kwargs.get("clinic_whatsapp") or "").strip()
    )

    mapped = {
        "doctor_id": (kwargs.get("doctor_id") or "").strip(),
        "first_name": (kwargs.get("first_name") or "").strip(),
        "last_name": (kwargs.get("last_name") or "").strip(),
        "email": (kwargs.get("email") or "").strip(),
        # Some legacy call sites used "whatsapp" instead of "whatsapp_no"
        "whatsapp_no": (kwargs.get("whatsapp_no") or kwargs.get("whatsapp") or "").strip(),
        "clinic_name": (kwargs.get("clinic_name") or "").strip(),
        # Legacy call sites used "imc_number"
        "imc_registration_number": (kwargs.get("imc_registration_number") or kwargs.get("imc_number") or "").strip(),
        "clinic_phone": (kwargs.get("clinic_phone") or "").strip(),
        "clinic_appointment_number": (kwargs.get("clinic_appointment_number") or "").strip(),
        "clinic_address": (kwargs.get("clinic_address") or "").strip(),
        "postal_code": (kwargs.get("postal_code") or "").strip(),
        "state": (kwargs.get("state") or "").strip(),
        "district": (kwargs.get("district") or "").strip(),
        "receptionist_whatsapp_number": rec_wa,
        "photo_path": (kwargs.get("photo_path") or "").strip(),
        "campaign_id": (kwargs.get("campaign_id") or "").strip(),
        "registered_by": (kwargs.get("registered_by") or "").strip(),
        "recruited_via": (kwargs.get("recruited_via") or "").strip(),
        "initial_password_raw": kwargs.get("initial_password_raw"),
    }

    return _create_doctor_with_enrollment_impl(**mapped)


# Alias to preserve the name used across the project.
create_doctor_with_enrollment = create_doctor_with_enrollment_compat
