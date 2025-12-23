from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import INDIA_STATES_AND_UTS


CANON_STATE_BY_LOWER = {s.lower(): s for s in INDIA_STATES_AND_UTS}

# Optional synonyms (extend if your source data uses other variants)
STATE_SYNONYMS = {
    "orissa": "Odisha",
    "pondicherry": "Puducherry",
    "nct of delhi": "Delhi",
    "delhi ncr": "Delhi",
    "jammu & kashmir": "Jammu and Kashmir",
    "andaman & nicobar islands": "Andaman and Nicobar Islands",
    "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
    "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
}


def canon_state(raw: str) -> str:
    s = (raw or "").strip()
    if not s:
        return ""

    # normalize whitespace and "&"
    s_norm = re.sub(r"\s+", " ", s.replace("&", "and")).strip()
    key = s_norm.lower()

    if key in STATE_SYNONYMS:
        s_norm = STATE_SYNONYMS[key]
        key = s_norm.lower()

    return CANON_STATE_BY_LOWER.get(key, s_norm)


def clean_pin(raw: str) -> str:
    digits = re.sub(r"\D", "", str(raw or ""))
    if len(digits) != 6:
        return ""
    return digits


class Command(BaseCommand):
    help = (
        "Build accounts/data/india_pincode_directory.json (PIN -> State mapping) from a CSV file.\n"
        "Default input: accounts/data/india_pincode_directory.csv\n"
        "Default output: accounts/data/india_pincode_directory.json"
    )

    def add_arguments(self, parser):
        base_dir = Path(getattr(settings, "BASE_DIR", Path.cwd()))
        default_csv = base_dir / "accounts" / "data" / "india_pincode_directory.csv"
        default_json = base_dir / "accounts" / "data" / "india_pincode_directory.json"

        parser.add_argument(
            "--input",
            required=False,
            default=str(default_csv),
            help=f"Path to source CSV (default: {default_csv})",
        )
        parser.add_argument(
            "--output",
            required=False,
            default=str(default_json),
            help=f"Output JSON path (default: {default_json})",
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"]).expanduser().resolve()
        output_path = Path(options["output"]).expanduser().resolve()

        if not input_path.exists():
            raise CommandError(f"Input CSV not found: {input_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)

        with input_path.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                raise CommandError("CSV appears to have no header row.")

            fn_lower = {name.lower(): name for name in reader.fieldnames}

            # Column detection (your file is typically: pincode,state)
            pin_col = fn_lower.get("pincode") or fn_lower.get("pin_code") or fn_lower.get("pin") or fn_lower.get("postal_code")
            state_col = fn_lower.get("state") or fn_lower.get("state_name") or fn_lower.get("statename") or fn_lower.get("state/ut")

            if not pin_col or not state_col:
                raise CommandError(
                    "Could not auto-detect PIN/State columns.\n"
                    f"Headers found: {reader.fieldnames}\n"
                    "Expected headers like: pincode,state"
                )

            mapping: dict[str, str] = {}
            invalid_pin = 0
            empty_state = 0
            conflicts = 0

            for row in reader:
                pin = clean_pin(row.get(pin_col) or "")
                if not pin:
                    invalid_pin += 1
                    continue

                state = canon_state(row.get(state_col) or "")
                if not state:
                    empty_state += 1
                    continue

                if pin in mapping and mapping[pin] != state:
                    conflicts += 1
                mapping[pin] = state

        if len(mapping) < 1000:
            # Fail loud: prevents silently writing "{}" or a tiny file.
            raise CommandError(
                f"Generated mapping is too small ({len(mapping)} entries). "
                f"Check your CSV headers and contents. "
                f"Invalid PIN rows: {invalid_pin}, empty state rows: {empty_state}."
            )

        with output_path.open("w", encoding="utf-8") as out:
            json.dump(mapping, out, ensure_ascii=False, indent=2, sort_keys=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(mapping):,} unique PIN entries to {output_path} "
                f"(invalid_pin_rows={invalid_pin}, empty_state_rows={empty_state}, state_conflicts={conflicts})"
            )
        )
