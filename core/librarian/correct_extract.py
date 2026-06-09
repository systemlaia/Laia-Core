import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from librarian.catalog import catalog_path, load_catalog_records
    from librarian.summarize import load_json, optional_json
except ModuleNotFoundError:
    from core.librarian.catalog import catalog_path, load_catalog_records
    from core.librarian.summarize import load_json, optional_json


FIELD_ARGS = {
    "merchant": "merchant",
    "transaction_date": "transaction_date",
    "transaction_time": "transaction_time",
    "subtotal": "subtotal",
    "tax": "tax",
    "tip": "tip",
    "total": "total",
    "payment_method": "payment_method",
    "last_four": "last_four",
    "currency": "currency",
}


def find_catalog_record(packet_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    for record in records:
        if record.get("packet_id") == packet_id:
            return record
    raise SystemExit("Packet ID not found in catalog.")


def correction_values(args) -> tuple[dict[str, str], list[str]]:
    corrections = {}
    for attr, field in FIELD_ARGS.items():
        value = getattr(args, attr, None)
        if value is not None:
            corrections[field] = str(value)
    note = getattr(args, "note", None)
    notes = [str(note)] if note else []
    if not corrections and not notes:
        raise SystemExit("At least one correction field or note is required.")
    if "last_four" in corrections and not re.fullmatch(r"\d{4}", corrections["last_four"]):
        raise SystemExit("last_four must be exactly 4 digits.")
    return corrections, notes


def require_extraction(packet_dir: Path) -> Path:
    extract_path = packet_dir / "extract" / "extract.json"
    if not extract_path.exists():
        raise SystemExit("No extraction sidecar found for packet.")
    return extract_path


def build_correction(record: dict[str, Any], corrections: dict[str, str], notes: list[str]) -> dict[str, Any]:
    packet_dir = Path(str(record.get("source_packet_dir") or "")).expanduser()
    extraction = load_json(require_extraction(packet_dir))
    original_fields = extraction.get("fields") or {}
    existing = optional_json(packet_dir / "extract" / "correction.json") or {}
    merged = existing.get("corrections") or {}
    changed = []

    for field, value in corrections.items():
        prior = merged.get(field, {}).get("corrected") if isinstance(merged.get(field), dict) else None
        if prior != value:
            changed.append(field)
        merged[field] = {
            "original": original_fields.get(field),
            "corrected": value,
        }

    merged_notes = list(existing.get("notes") or [])
    merged_notes.extend(notes)

    return {
        "packet_id": record.get("packet_id"),
        "packet_dir": str(packet_dir),
        "corrected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "corrector": "human",
        "corrections": merged,
        "changed_fields": changed,
        "notes": merged_notes,
    }


def markdown_correction(correction: dict[str, Any]) -> str:
    lines = [
        "# LAIA Extraction Correction",
        "",
        f"Packet ID: {correction.get('packet_id')}",
        f"Corrected At: {correction.get('corrected_at')}",
        "",
        "Corrections:",
    ]
    corrections = correction.get("corrections") or {}
    if corrections:
        for field, values in corrections.items():
            lines.append(
                f"- {field}: original={values.get('original')} corrected={values.get('corrected')}"
            )
    else:
        lines.append("- none")
    lines.extend(["", "Notes:"])
    notes = correction.get("notes") or []
    if notes:
        for note in notes:
            lines.append(f"- {note}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_correction(record: dict[str, Any], correction: dict[str, Any]) -> tuple[Path, Path]:
    packet_dir = Path(str(record.get("source_packet_dir") or "")).expanduser()
    extract_dir = packet_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)
    correction_json = extract_dir / "correction.json"
    correction_md = extract_dir / "correction.md"
    correction_json.write_text(json.dumps(correction, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    correction_md.write_text(markdown_correction(correction), encoding="utf-8")
    return correction_json, correction_md


def print_summary(correction: dict[str, Any], correction_json: Path, correction_md: Path) -> None:
    print("\nLAIA Librarian Extract Correction Complete\n")
    print(f"Packet: {correction.get('packet_dir')}")
    print(f"Packet ID: {correction.get('packet_id')}")
    print("Corrections:")
    for field in correction.get("changed_fields") or []:
        values = correction["corrections"][field]
        print(f"  {field}: {values.get('original')} -> {values.get('corrected')}")
    print("\nWrote:")
    packet_dir = Path(str(correction.get("packet_dir")))
    print(f"  {correction_json.relative_to(packet_dir)}")
    print(f"  {correction_md.relative_to(packet_dir)}")
    print("")


def command_correct_extract(args) -> None:
    packet_id = getattr(args, "packet", "")
    record = find_catalog_record(packet_id, load_catalog_records(catalog_path()))
    corrections, notes = correction_values(args)
    correction = build_correction(record, corrections, notes)
    correction_json, correction_md = write_correction(record, correction)
    print_summary(correction, correction_json, correction_md)
