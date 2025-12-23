from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from accounts.pincode_directory import PINCODE_DIRECTORY_PATH, _canon_state_name


PIN_CANDIDATES = {"pincode", "pin_code", "pin", "postal_code", "postalcode", "pin code"}
STATE_CANDIDATES = {"state", "state_name", "statename", "state/ut", "state_ut", "circle", "circlename"}


def _clean_pin(value: str) -> str:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits if re.fullmatch(r"\d{6}", digits) else ""


def _is_blank_row(row: list[str]) -> bool:
    return (not row) or all((c or "").strip() == "" for c in row)


def _looks_like_header(row: list[str]) -> bool:
    """
    Treat as header if it contains obvious column names (pin/state),
    irrespective of case. This also works if there are extra columns.
    """
    lowered = {str(c or "").strip().lower() for c in row if str(c or "").strip()}
    if not lowered:
        return False
    has_pin = any(any(token in col for token in ["pin", "pincode", "postal"]) for col in lowered)
    has_state = any("state" in col or "circle" in col for col in lowered)
    return has_pin and has_state


def _detect_delimiter(sample: str) -> str:
    # Try to sniff; if it fails, default to comma.
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=[",", ";", "\t", "|"])
        return dialect.delimiter
    except Exception:
        return ","


class Command(BaseCommand):
    help = (
        "Build accounts/data/india_pincode_directory.json (PIN -> State mapping) from a CSV file.\n\n"
        "Works with:\n"
        "- CSVs WITH header row (recommended)\n"
        "- CSVs WITHOUT header row (assumes first column = PIN, second column = State)\n"
        "- CSVs with leading blank lines\n"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            required=True,
            help="Path to the source CSV containing all-India PIN directory data.",
        )
        parser.add_argument(
            "--output",
            default=str(PINCODE_DIRECTORY_PATH),
            help=f"Output JSON path (default: {PINCODE_DIRECTORY_PATH}).",
        )

    def handle(self, *args, **options):
        input_path = Path(options["input"]).expanduser().resolve()
        if not input_path.exists():
            raise CommandError(f"Input CSV not found: {input_path}")

        output_path = Path(options["output"]).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Read a small sample to sniff delimiter
        with input_path.open("r", encoding="utf-8-sig", newline="") as f:
            sample = f.read(8192)
            f.seek(0)

            delimiter = _detect_delimiter(sample)
            reader = csv.reader(f, delimiter=delimiter)

            # Find the first non-empty row (skip leading blank lines)
            first_row = None
            for row in reader:
                if not _is_blank_row(row):
                    first_row = row
                    break

            if first_row is None:
                raise CommandError("CSV is empty or contains only blank lines.")

            has_header = _looks_like_header(first_row)

            # Determine column indices
            pin_idx = None
            state_idx = None

            if has_header:
                headers = [str(c or "").strip().lower() for c in first_row]
                for i, h in enumerate(headers):
                    if any(h == cand or cand in h for cand in PIN_CANDIDATES):
                        pin_idx = i
                        break

                for i, h in enumerate(headers):
                    if any(h == cand or cand in h for cand in STATE_CANDIDATES):
                        state_idx = i
                        break

                if pin_idx is None or state_idx is None:
                    raise CommandError(
                        "Header row found but could not detect PIN/State columns.\n"
                        f"Header columns: {first_row}\n"
                        "Expected something like 'pincode' and 'state'."
                    )
            else:
                # No header: assume first column is PIN, second column is State.
                pin_idx = 0
                state_idx = 1

            mapping: dict[str, str] = {}
            invalid_pin = 0
            empty_state = 0
            short_rows = 0

            # If there was no header, first_row is data and must be processed.
            if not has_header:
                row = first_row
                if len(row) <= max(pin_idx, state_idx):
                    short_rows += 1
                else:
                    pin = _clean_pin(row[pin_idx])
                    if not pin:
                        invalid_pin += 1
                    else:
                        state = _canon_state_name(row[state_idx])
                        if not state:
                            empty_state += 1
                        else:
                            mapping[pin] = state

            # Process the rest
            for row in reader:
                if _is_blank_row(row):
                    continue
                if len(row) <= max(pin_idx, state_idx):
                    short_rows += 1
                    continue

                pin = _clean_pin(row[pin_idx])
                if not pin:
                    invalid_pin += 1
                    continue

                state = _canon_state_name(row[state_idx])
                if not state:
                    empty_state += 1
                    continue

                mapping[pin] = state

        # Fail loudly if mapping is suspiciously small
        if len(mapping) < 1000:
            raise CommandError(
                "PIN->State mapping generated is too small. "
                f"Generated={len(mapping)}. invalid_pin_rows={invalid_pin}, empty_state_rows={empty_state}, short_rows={short_rows}. "
                "This typically indicates the CSV was not parsed correctly (wrong delimiter/columns) or the file is not the expected one."
            )

        with output_path.open("w", encoding="utf-8") as out:
            json.dump(mapping, out, ensure_ascii=False, indent=2, sort_keys=True)

        self.stdout.write(
            self.style.SUCCESS(
                f"Wrote {len(mapping):,} PIN entries to {output_path} "
                f"(delimiter='{delimiter}', header={has_header}, invalid_pin_rows={invalid_pin}, empty_state_rows={empty_state}, short_rows={short_rows})"
            )
        )
