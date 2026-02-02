from __future__ import annotations

import json
import os
import random
import re
import string
from dataclasses import dataclass
from typing import Optional

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.db import connections
from django.utils import timezone

from .models import RedflagsDoctor

# --------------------------------------------------------------------------------------
# Logging helpers (kept lightweight; safe even if LOG_DB disabled)
# --------------------------------------------------------------------------------------

def _mask_email_for_log(email: str) -> str:
    e = (email or "").strip()
    if not e:
        return ""
    if "@" not in e:
        return e[:2] + "…"
    local, domain = e.split("@", 1)
    if len(local) <= 2:
        return local + "…@" + domain
    return local[:2] + "…@" + domain


def _mask_phone_for_log(phone: str) -> str:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) <= 4:
        return digits
    return "…" + digits[-4:]


def _log_db(event: str, **kwargs) -> None:
    if getattr(settings, "LOG_DB", False):
        try:
            payload = {"event": event, **kwargs}
            print(json.dumps(payload, ensure_ascii=False))
        except Exception:
            # don't break app flow
            pass


# --------------------------------------------------------------------------------------
# Master DB connection helpers
# --------------------------------------------------------------------------------------

def master_alias() -> str:
    return getattr(settings, "MASTER_DB_ALIAS", "MASTER_DB_ALIAS")


def get_master_connection():
    return connections[master_alias()]


def qn(name: str) -> str:
    """
    Quote a MySQL identifier with backticks.
    """
    if not name:
        return "``"
    return f"`{name.replace('`', '')}`"


# --------------------------------------------------------------------------------------
# MASTER doctor lookup (legacy compatibility)
# --------------------------------------------------------------------------------------

@dataclass(frozen=True)
class MasterDoctor:
    doctor_id: str
    first_name: str
    last_name: str
    email: str
    whatsapp_no: str


def find_doctor_by_email_or_whatsapp(*, email: str, whatsapp: str) -> Optional[MasterDoctor]:
    """
    Find doctor row in MASTER DB redflags_doctor using either email or whatsapp_no.
    """
    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_DOCTOR_TABLE", "redflags_doctor")

    id_col = getattr(settings, "MASTER_DB_DOCTOR_ID_COLUMN", "doctor_id")
    fn_col = getattr(settings, "MASTER_DB_DOCTOR_FIRST_NAME_COLUMN", "first_name")
    ln_col = getattr(settings, "MASTER_DB_DOCTOR_LAST_NAME_COLUMN", "last_name")
    email_col = getattr(settings, "MASTER_DB_DOCTOR_EMAIL_COLUMN", "email")
    wa_col = getattr(settings, "MASTER_DB_DOCTOR_WHATSAPP_COLUMN", "whatsapp_no")

    email_n = (email or "").strip().lower()
    wa_n = re.sub(r"\D", "", str(whatsapp or "")).strip()

    candidates = []
    if wa_n:
        candidates.append(wa_n)
    if email_n:
        candidates.append(email_n)

    if not candidates:
        return None

    # We want either (whatsapp_no == x) OR (email == y)
    where_parts = []
    params = []
    if wa_n:
        where_parts.append(f"{qn(wa_col)} = %s")
        params.append(wa_n)
    if email_n:
        where_parts.append(f"LOWER({qn(email_col)}) = %s")
        params.append(email_n)

    where = " OR ".join(where_parts) if where_parts else "1=0"
    sql = (
        f"SELECT {qn(id_col)}, {qn(fn_col)}, {qn(ln_col)}, {qn(email_col)}, {qn(wa_col)} "
        f"FROM {qn(table)} "
        f"WHERE {where} "
        f"LIMIT 1"
    )

    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

    if not row:
        return None

    return MasterDoctor(
        doctor_id=str(row[0] or "").strip(),
        first_name=str(row[1] or "").strip(),
        last_name=str(row[2] or "").strip(),
        email=str(row[3] or "").strip(),
        whatsapp_no=str(row[4] or "").strip(),
    )


# --------------------------------------------------------------------------------------
# Enrollment table discovery + schema helpers
# --------------------------------------------------------------------------------------

from typing import Dict, List, Tuple  # noqa: E402

_ENROLLMENT_META_CACHE: Optional[Dict[str, str]] = None


def _db_schema_name(conn) -> str:
    return (conn.settings_dict.get("NAME") or "").strip()


def _table_exists(conn, table_name: str) -> bool:
    schema = _db_schema_name(conn)
    if not schema or not table_name:
        return False
    sql = """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s AND table_name = %s
        LIMIT 1
    """
    with conn.cursor() as cur:
        cur.execute(sql, [schema, table_name])
        return cur.fetchone() is not None


def _find_table_by_patterns(conn, patterns: List[str]) -> Optional[str]:
    """
    Find the first table whose name matches any of the LIKE patterns (case-insensitive).
    """
    schema = _db_schema_name(conn)
    if not schema:
        return None

    sql = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = %s AND LOWER(table_name) LIKE %s
        ORDER BY LENGTH(table_name) ASC, table_name ASC
        LIMIT 1
    """

    for pat in patterns:
        with conn.cursor() as cur:
            cur.execute(sql, [schema, pat.lower()])
            row = cur.fetchone()
        if row and row[0]:
            return str(row[0])
    return None


def _get_table_columns(conn, table_name: str) -> List[str]:
    schema = _db_schema_name(conn)
    sql = """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
    """
    with conn.cursor() as cur:
        cur.execute(sql, [schema, table_name])
        rows = cur.fetchall()
    return [str(r[0]) for r in (rows or []) if r and r[0]]


def _get_column_data_type(conn, table_name: str, column_name: str) -> str:
    """
    Returns MySQL information_schema.columns.DATA_TYPE (lowercase), e.g. 'bigint', 'varchar', 'datetime'.
    Empty string if not found / on error.
    """
    schema = _db_schema_name(conn)
    if not (schema and table_name and column_name):
        return ""
    sql = """
        SELECT LOWER(data_type)
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        LIMIT 1
    """
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [schema, table_name, column_name])
            row = cur.fetchone()
        return str(row[0] or "").strip().lower() if row else ""
    except Exception:
        return ""


def _is_numeric_mysql_type(data_type: str) -> bool:
    dt = (data_type or "").strip().lower()
    return dt in {
        "tinyint",
        "smallint",
        "mediumint",
        "int",
        "integer",
        "bigint",
        "decimal",
        "numeric",
        "float",
        "double",
    }


def _pick_first_column(cols: List[str], candidates: List[str]) -> Optional[str]:
    cols_l = {c.lower(): c for c in cols}
    for cand in candidates:
        if cand.lower() in cols_l:
            return cols_l[cand.lower()]
    return None


def _normalize_uuid_for_mysql(raw: str) -> str:
    """
    MySQL Django UUIDField commonly stored as CHAR(32) without hyphens.
    """
    return (raw or "").strip().replace("-", "")


def _get_enrollment_meta() -> Dict[str, str]:
    """
    Discover enrollment table + columns once per process and cache.

    Returns dict:
      {
        "table": <table_name>,
        "campaign_col": <campaign_column_name>,
        "doctor_col": <doctor_column_name>,
        "registered_by_col": <optional column name or "">,
      }
    """
    global _ENROLLMENT_META_CACHE
    if _ENROLLMENT_META_CACHE is not None:
        return _ENROLLMENT_META_CACHE

    conn = get_master_connection()

    explicit_table = (getattr(settings, "MASTER_DB_ENROLLMENT_TABLE", "") or "").strip()
    if explicit_table and _table_exists(conn, explicit_table):
        table = explicit_table
    else:
        patterns = [
            "%doctorcampaignenrollment%",
            "%doctor_campaign_enrollment%",
            "%campaignenrollment%",
            "%enrolment%",
        ]
        table = _find_table_by_patterns(conn, patterns)

    if not table:
        raise RuntimeError(
            "Enrollment table not found in master DB. "
            "Create/migrate the enrollment model or set settings.MASTER_DB_ENROLLMENT_TABLE explicitly."
        )

    cols = _get_table_columns(conn, table)
    if not cols:
        raise RuntimeError(f"Could not read columns for enrollment table '{table}' in master DB.")

    campaign_col = _pick_first_column(cols, ["campaign_id", "campaign", "campaign_uuid"])
    doctor_col = _pick_first_column(cols, ["doctor_id", "doctor", "doctor_uuid"])

    registered_by_col = _pick_first_column(
        cols,
        ["registered_by_id", "registered_by", "field_rep_id", "fieldrep_id"],
    )

    if not campaign_col or not doctor_col:
        raise RuntimeError(
            f"Enrollment table '{table}' does not have expected columns. "
            f"Found columns: {cols}"
        )

    _ENROLLMENT_META_CACHE = {
        "table": table,
        "campaign_col": campaign_col,
        "doctor_col": doctor_col,
        "registered_by_col": registered_by_col or "",
    }

    return _ENROLLMENT_META_CACHE


def _ensure_campaign_doctor_id(
    *,
    conn,
    full_name: str,
    email: str,
    phone: str,
    city: str,
    state: str,
) -> Optional[int]:
    """
    Ensure a row exists in MASTER DB table `campaign_doctor` and return its bigint id.

    MASTER schema (from your export):
      campaign_doctor(id, full_name, email, phone, city, state, created_at)

    - We treat email + last-10-digits phone as identity keys (best-effort).
    - If both are missing, returns None.
    """
    email_n = (email or "").strip().lower()
    phone_n = re.sub(r"\D", "", str(phone or ""))
    phone_last10 = phone_n[-10:] if len(phone_n) > 10 else phone_n

    if not email_n and not phone_last10:
        return None

    where_parts = []
    params: List[str] = []
    if email_n:
        where_parts.append("LOWER(email) = %s")
        params.append(email_n)
    if phone_last10:
        where_parts.append("RIGHT(phone, 10) = %s")
        params.append(phone_last10)

    where_sql = " OR ".join(where_parts) if where_parts else "1=0"

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {qn('campaign_doctor')} WHERE ({where_sql}) ORDER BY id DESC LIMIT 1",
            params,
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])

    full_name_v = (full_name or "").strip() or email_n or "Doctor"
    city_v = (city or "").strip() or ""
    state_v = (state or "").strip() or ""

    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO {qn('campaign_doctor')} (full_name, email, phone, city, state, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
            """,
            [
                full_name_v,
                email_n or "",
                phone_last10 or "",
                city_v,
                state_v,
            ],
        )

    with conn.cursor() as cur:
        cur.execute(
            f"SELECT id FROM {qn('campaign_doctor')} WHERE ({where_sql}) ORDER BY id DESC LIMIT 1",
            params,
        )
        row = cur.fetchone()
        if row and row[0] is not None:
            return int(row[0])

    return None


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------

def normalize_campaign_id(raw_campaign_id: str) -> str:
    return _normalize_uuid_for_mysql((raw_campaign_id or "").strip())


def generate_temporary_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(random.choice(alphabet) for _ in range(max(6, int(length or 10))))


def create_doctor_with_enrollment(
    *,
    doctor_id: str,
    first_name: str,
    last_name: str,
    email: str,
    whatsapp: str,
    clinic_name: str,
    clinic_phone: str,
    clinic_appointment_number: str,
    clinic_address: str,
    imc_number: str,
    postal_code: str,
    state: str,
    district: str,
    photo_path: str,
    campaign_id: Optional[str] = None,
    recruited_via: str = "FIELD_REP",
    registered_by: Optional[str] = None,
    initial_password_raw: Optional[str] = None,
) -> None:
    """
    Create doctor in MASTER redflags_doctor (ORM-managed with db_table mapping) and ensure campaign enrollment.
    """
    alias = master_alias()

    password_raw = (initial_password_raw or generate_temporary_password()).strip()
    password_hash = make_password(password_raw)

    RedflagsDoctor.objects.using(alias).create(
        doctor_id=doctor_id,
        first_name=(first_name or "").strip(),
        last_name=(last_name or "").strip(),
        email=(email or "").strip().lower(),
        whatsapp_no=re.sub(r"\D", "", str(whatsapp or "")),
        clinic_name=(clinic_name or "").strip(),
        imc_registration_number=(imc_number or "").strip(),
        clinic_phone=re.sub(r"\D", "", str(clinic_phone or "")),
        clinic_appointment_number=re.sub(r"\D", "", str(clinic_appointment_number or "")),
        clinic_address=(clinic_address or "").strip(),
        postal_code=(postal_code or "").strip(),
        state=(state or "").strip(),
        district=(district or "").strip(),
        receptionist_whatsapp_number=re.sub(r"\D", "", str(whatsapp or "")),
        photo_path=(photo_path or "").strip(),
        recruited_via=(recruited_via or "FIELD_REP").strip(),
        field_rep_id=(registered_by or "").strip(),
        password=password_hash,
    )

    if campaign_id:
        try:
            ensure_enrollment(
                doctor_id=doctor_id,
                campaign_id=campaign_id,
                registered_by=registered_by or "",
            )
        except Exception:
            _log_db("master_db.enrollment.ensure.exception", doctor_id=doctor_id, campaign_id=campaign_id)


def ensure_enrollment(*, doctor_id: str, campaign_id: str, registered_by: str) -> None:
    """
    Ensure a doctor is enrolled into a campaign in MASTER DB.

    IMPORTANT (your current MASTER schema):
      - campaign_doctorcampaignenrollment.doctor_id is a bigint FK -> campaign_doctor.id
      - campaign_doctorcampaignenrollment has NOT NULL columns: whitelabel_enabled, whitelabel_subdomain, registered_at

    Earlier versions of this function attempted to insert only (doctor_id, campaign_id),
    which fails silently in upstream flows and results in:
      - no banners on the doctor share page
      - doctors seeing campaign clusters not meant for them (because filtering cannot work)

    This implementation is schema-aware:
      - If enrollment.doctor_id is numeric, it auto-creates/looks up campaign_doctor by email/phone and uses its id.
      - It includes required NOT NULL columns when present in the enrollment table.
      - Uses INSERT IGNORE to keep idempotency under the unique constraint (campaign_id, doctor_id).
    """

    _log_db("master_db.enrollment.ensure.start", doctor_id=doctor_id, campaign_id=campaign_id)

    if not (doctor_id and campaign_id):
        return

    conn = get_master_connection()
    meta = _get_enrollment_meta()

    table = meta["table"]
    doctor_col = meta["doctor_col"]
    campaign_col = meta["campaign_col"]
    registered_by_col = (meta.get("registered_by_col") or "").strip()

    cols = _get_table_columns(conn, table)

    cid_norm = _normalize_uuid_for_mysql((campaign_id or "").strip())

    doctor_val: object = doctor_id
    doctor_type = _get_column_data_type(conn, table, doctor_col)

    if _is_numeric_mysql_type(doctor_type) and _table_exists(conn, "campaign_doctor"):
        email_v = ""
        phone_v = ""
        full_name_v = ""
        state_v = ""
        city_v = ""

        try:
            rd = (
                RedflagsDoctor.objects.using(master_alias())
                .filter(doctor_id=doctor_id)
                .values(
                    "first_name",
                    "last_name",
                    "email",
                    "whatsapp_no",
                    "clinic_phone",
                    "state",
                    "district",
                )
                .first()
            )
        except Exception:
            rd = None

        if rd:
            fn = str(rd.get("first_name") or "").strip()
            ln = str(rd.get("last_name") or "").strip()
            full_name_v = (f"{fn} {ln}").strip() or fn or ln

            email_v = str(rd.get("email") or "").strip().lower()
            phone_v = str(rd.get("whatsapp_no") or "").strip() or str(rd.get("clinic_phone") or "").strip()
            state_v = str(rd.get("state") or "").strip()
            city_v = str(rd.get("district") or "").strip()

        full_name_v = full_name_v or str(doctor_id)
        state_v = state_v or ""
        city_v = city_v or ""

        campaign_doctor_id = None
        try:
            campaign_doctor_id = _ensure_campaign_doctor_id(
                conn=conn,
                full_name=full_name_v,
                email=email_v,
                phone=phone_v,
                city=city_v,
                state=state_v,
            )
        except Exception:
            campaign_doctor_id = None

        if campaign_doctor_id is not None:
            doctor_val = campaign_doctor_id

    insert_cols: List[str] = [doctor_col, campaign_col]
    insert_vals: List[object] = [doctor_val, cid_norm]

    if "whitelabel_enabled" in cols:
        insert_cols.append("whitelabel_enabled")
        insert_vals.append(0)

    if "whitelabel_subdomain" in cols:
        insert_cols.append("whitelabel_subdomain")
        insert_vals.append("")

    if "registered_at" in cols:
        insert_cols.append("registered_at")
        ts = timezone.now()
        try:
            if timezone.is_aware(ts):
                ts = timezone.make_naive(ts)
        except Exception:
            pass
        insert_vals.append(ts)

    if "active" in cols:
        insert_cols.append("active")
        insert_vals.append(1)

    if registered_by_col and registered_by_col in cols:
        rb_raw = (registered_by or "").strip()
        rb_val = None
        if rb_raw.isdigit():
            try:
                rb_val = int(rb_raw)
            except Exception:
                rb_val = None
        if rb_val is not None:
            insert_cols.append(registered_by_col)
            insert_vals.append(rb_val)

    placeholders = ", ".join(["%s"] * len(insert_cols))
    sql = f"INSERT IGNORE INTO {qn(table)} ({', '.join(qn(c) for c in insert_cols)}) VALUES ({placeholders})"

    with conn.cursor() as cur:
        cur.execute(sql, insert_vals)
        _log_db(
            "master_db.enrollment.ensure.done",
            doctor_id=doctor_id,
            campaign_id=cid_norm,
            rowcount=getattr(cur, "rowcount", None),
            enrollment_table=table,
        )
