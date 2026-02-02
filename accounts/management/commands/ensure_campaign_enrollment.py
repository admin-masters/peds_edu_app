from __future__ import annotations

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.conf import settings

from accounts import master_db


class Command(BaseCommand):
    help = "Ensure MASTER campaign enrollment exists for a doctor and campaign (creates campaign_doctor + enrollment if needed)."

    def add_arguments(self, parser):
        parser.add_argument("--doctor-id", dest="doctor_id", default="", help="MASTER redflags_doctor.doctor_id (e.g. DR061755)")
        parser.add_argument("--email", dest="email", default="", help="Doctor email to resolve doctor_id in MASTER redflags_doctor")
        parser.add_argument("--campaign-id", dest="campaign_id", required=True, help="Campaign UUID (with or without dashes)")
        parser.add_argument("--registered-by", dest="registered_by", default="", help="Optional fieldrep id (string/int)")

    def handle(self, *args, **opts):
        doctor_id = (opts.get("doctor_id") or "").strip()
        email = (opts.get("email") or "").strip().lower()
        campaign_id = (opts.get("campaign_id") or "").strip()
        registered_by = (opts.get("registered_by") or "").strip()

        if not doctor_id and not email:
            raise CommandError("Provide --doctor-id or --email")

        if not campaign_id:
            raise CommandError("--campaign-id is required")

        if not doctor_id:
            # resolve doctor_id from MASTER redflags_doctor by email
            alias = getattr(settings, "MASTER_DB_ALIAS", "MASTER_DB_ALIAS")
            conn = connections[alias]
            table = getattr(settings, "MASTER_DOCTOR_TABLE", "redflags_doctor")
            email_col = "email"
            id_col = "doctor_id"

            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT {id_col} FROM {table} WHERE LOWER({email_col}) = %s LIMIT 1",
                    [email],
                )
                row = cur.fetchone()

            if not row or not row[0]:
                raise CommandError(f"No doctor found in MASTER redflags_doctor for email={email!r}")

            doctor_id = str(row[0]).strip()

        # Ensure enrollment (idempotent)
        master_db.ensure_enrollment(
            doctor_id=doctor_id,
            campaign_id=campaign_id,
            registered_by=registered_by,
        )

        self.stdout.write(self.style.SUCCESS(
            f"Enrollment ensured: doctor_id={doctor_id}, campaign_id={campaign_id.replace('-','')}"
        ))
