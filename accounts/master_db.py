from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import quote

from django.conf import settings
from django.db import connections, IntegrityError


class MasterDBNotConfigured(RuntimeError):
    pass


def master_alias() -> str:
    return getattr(settings, "MASTER_DB_ALIAS", "master")


def get_master_connection():
    alias = master_alias()
    if alias not in connections.databases:
        raise MasterDBNotConfigured(
            f"MASTER DB alias '{alias}' is not configured in settings.DATABASES."
        )
    return connections[alias]


def qn(name: str) -> str:
    """
    Quote identifiers safely per backend.
    Supports schema-qualified names like: schema.table
    """
    conn = get_master_connection()
    parts = [p for p in (name or "").split(".") if p]
    if len(parts) > 1:
        return ".".join(conn.ops.quote_name(p) for p in parts)
    return conn.ops.quote_name(name)


# -------------------------------
# WhatsApp helpers
# -------------------------------

def normalize_wa_for_lookup(raw: str) -> str:
    s = re.sub(r"\D", "", str(raw or ""))
    if len(s) == 12 and s.startswith("91"):
        return s[2:]
    return s


def wa_link_number(raw: str, default_country_code: str = "91") -> str:
    s = re.sub(r"\D", "", str(raw or ""))
    if len(s) == 10:
        return f"{default_country_code}{s}"
    if s.startswith("0") and len(s) == 11:
        return f"{default_country_code}{s[1:]}"
    return s


def build_whatsapp_deeplink(raw_phone: str, message: str) -> str:
    phone = wa_link_number(raw_phone)
    return f"https://wa.me/{phone}?text={quote(message or '')}"


# -------------------------------
# MASTER: AuthorizedPublisher
# -------------------------------

def authorized_publisher_exists(email: str) -> bool:
    """
    Checks AuthorizedPublisher in MASTER DB.
    """
    e = (email or "").strip().lower()
    if not e:
        return False

    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_AUTH_PUBLISHER_TABLE", "publisher_authorizedpublisher")
    email_col = getattr(settings, "MASTER_DB_AUTH_PUBLISHER_EMAIL_COLUMN", "email")

    sql = f"SELECT 1 FROM {qn(table)} WHERE LOWER({qn(email_col)}) = LOWER(%s) LIMIT 1"
    with conn.cursor() as cur:
        cur.execute(sql, [e])
        return cur.fetchone() is not None


# -------------------------------
# MASTER: FieldRep
# -------------------------------

@dataclass(frozen=True)
class MasterFieldRep:
    id: str
    full_name: str
    phone_number: str
    brand_supplied_field_rep_id: str
    is_active: bool


def get_field_rep(field_rep_id: str) -> Optional[MasterFieldRep]:
    """
    Looks up FieldRep by:
      - brand_supplied_field_rep_id == field_rep_id
      - OR primary key == field_rep_id (if numeric)
    """
    fid = (field_rep_id or "").strip()
    if not fid:
        return None

    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_FIELD_REP_TABLE", "publisher_fieldrep")
    pk_col = getattr(settings, "MASTER_DB_FIELD_REP_PK_COLUMN", "id")
    ext_col = getattr(settings, "MASTER_DB_FIELD_REP_EXTERNAL_ID_COLUMN", "brand_supplied_field_rep_id")
    active_col = getattr(settings, "MASTER_DB_FIELD_REP_ACTIVE_COLUMN", "is_active")
    name_col = getattr(settings, "MASTER_DB_FIELD_REP_FULL_NAME_COLUMN", "full_name")
    phone_col = getattr(settings, "MASTER_DB_FIELD_REP_PHONE_COLUMN", "phone_number")

    where = f"{qn(ext_col)} = %s"
    params = [fid]

    # If it is numeric, also try PK match (common if PK is integer)
    if fid.isdigit():
        where = f"({qn(ext_col)} = %s OR {qn(pk_col)} = %s)"
        params = [fid, int(fid)]

    sql = (
        f"SELECT {qn(pk_col)}, {qn(name_col)}, {qn(phone_col)}, {qn(ext_col)}, {qn(active_col)} "
        f"FROM {qn(table)} WHERE {where} LIMIT 1"
    )
    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()

    if not row:
        return None

    return MasterFieldRep(
        id=str(row[0]),
        full_name=str(row[1] or "").strip(),
        phone_number=str(row[2] or "").strip(),
        brand_supplied_field_rep_id=str(row[3] or "").strip(),
        is_active=bool(row[4]),
    )


def field_rep_is_active(field_rep_id: str) -> bool:
    fr = get_field_rep(field_rep_id)
    return bool(fr and fr.is_active)


# -------------------------------
# MASTER: Campaign
# -------------------------------

@dataclass(frozen=True)
class MasterCampaign:
    campaign_id: str
    doctors_supported: int
    wa_addition: str
    new_video_cluster_name: str
    email_registration: str


def get_campaign(campaign_id: str) -> Optional[MasterCampaign]:
    cid = (campaign_id or "").strip()
    if not cid:
        return None

    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_CAMPAIGN_TABLE", "publisher_campaign")

    id_col = getattr(settings, "MASTER_DB_CAMPAIGN_ID_COLUMN", "campaign_id")
    ds_col = getattr(settings, "MASTER_DB_CAMPAIGN_DOCTORS_SUPPORTED_COLUMN", "doctors_supported")
    wa_col = getattr(settings, "MASTER_DB_CAMPAIGN_WA_ADDITION_COLUMN", "wa_addition")
    vc_col = getattr(settings, "MASTER_DB_CAMPAIGN_VIDEO_CLUSTER_COLUMN", "new_video_cluster_name")
    er_col = getattr(settings, "MASTER_DB_CAMPAIGN_EMAIL_REGISTRATION_COLUMN", "email_registration")

    sql = (
        f"SELECT {qn(id_col)}, {qn(ds_col)}, {qn(wa_col)}, {qn(vc_col)}, {qn(er_col)} "
        f"FROM {qn(table)} WHERE {qn(id_col)} = %s LIMIT 1"
    )
    with conn.cursor() as cur:
        cur.execute(sql, [cid])
        row = cur.fetchone()

    if not row:
        return None

    try:
        doctors_supported = int(row[1] or 0)
    except Exception:
        doctors_supported = 0

    return MasterCampaign(
        campaign_id=str(row[0]),
        doctors_supported=doctors_supported,
        wa_addition=str(row[2] or ""),
        new_video_cluster_name=str(row[3] or ""),
        email_registration=str(row[4] or ""),
    )


# -------------------------------
# MASTER: Doctor & Enrollment (as before)
# -------------------------------

@dataclass(frozen=True)
class MasterDoctor:
    doctor_id: str
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    whatsapp_no: str = ""

    @property
    def full_name(self) -> str:
        return (f"{self.first_name} {self.last_name}").strip()


def doctor_id_exists(doctor_id: str) -> bool:
    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_DOCTOR_TABLE", "Doctor")
    id_col = getattr(settings, "MASTER_DB_DOCTOR_ID_COLUMN", "doctor_id")

    sql = f"SELECT 1 FROM {qn(table)} WHERE {qn(id_col)} = %s LIMIT 1"
    with conn.cursor() as cur:
        cur.execute(sql, [doctor_id])
        return cur.fetchone() is not None


def get_doctor_by_whatsapp(whatsapp_no: str) -> Optional[MasterDoctor]:
    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_DOCTOR_TABLE", "Doctor")
    id_col = getattr(settings, "MASTER_DB_DOCTOR_ID_COLUMN", "doctor_id")
    wa_col = getattr(settings, "MASTER_DB_DOCTOR_WHATSAPP_COLUMN", "whatsapp_no")

    wa = normalize_wa_for_lookup(whatsapp_no)
    if not wa:
        return None

    candidates = [wa]
    if len(wa) == 10:
        candidates.append(f"91{wa}")

    placeholders = " OR ".join([f"{qn(wa_col)} = %s"] * len(candidates))
    sql = (
        f"SELECT {qn(id_col)}, {qn('first_name')}, {qn('last_name')}, {qn('email')}, {qn(wa_col)} "
        f"FROM {qn(table)} WHERE {placeholders} LIMIT 1"
    )

    with conn.cursor() as cur:
        cur.execute(sql, candidates)
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


def count_campaign_enrollments(campaign_id: str) -> int:
    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_ENROLLMENT_TABLE", "DoctorCampaignEnrollment")
    campaign_col = getattr(settings, "MASTER_DB_ENROLLMENT_CAMPAIGN_COLUMN", "campaign_id")

    cid = str(campaign_id or "").strip()
    if not cid:
        return 0

    sql = f"SELECT COUNT(*) FROM {qn(table)} WHERE {qn(campaign_col)} = %s"
    with conn.cursor() as cur:
        cur.execute(sql, [cid])
        row = cur.fetchone()

    try:
        return int(row[0])
    except Exception:
        return 0


def insert_doctor_row(
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
    field_rep_id: str = "",
    recruited_via: str = "FIELD_REP",
) -> None:
    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_DOCTOR_TABLE", "Doctor")

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
        email,
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


def ensure_enrollment(*, doctor_id: str, campaign_id: str, registered_by: str) -> None:
    if not (doctor_id and campaign_id):
        return

    conn = get_master_connection()
    table = getattr(settings, "MASTER_DB_ENROLLMENT_TABLE", "DoctorCampaignEnrollment")

    doctor_col = getattr(settings, "MASTER_DB_ENROLLMENT_DOCTOR_COLUMN", "doctor_id")
    campaign_col = getattr(settings, "MASTER_DB_ENROLLMENT_CAMPAIGN_COLUMN", "campaign_id")
    registered_by_col = getattr(settings, "MASTER_DB_ENROLLMENT_REGISTERED_BY_COLUMN", "registered_by_id")

    sql = (
        f"INSERT INTO {qn(table)} ({qn(doctor_col)}, {qn(campaign_col)}, {qn(registered_by_col)}) "
        f"VALUES (%s, %s, %s)"
    )
    try:
        with conn.cursor() as cur:
            cur.execute(sql, [doctor_id, campaign_id, registered_by or ""])
    except IntegrityError:
        return
