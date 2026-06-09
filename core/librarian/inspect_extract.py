import json
from pathlib import Path
from typing import Any

try:
    from librarian.catalog import catalog_path, load_catalog_records
    from librarian.summarize import load_json, optional_json
except ModuleNotFoundError:
    from core.librarian.catalog import catalog_path, load_catalog_records
    from core.librarian.summarize import load_json, optional_json


FIELD_ORDER = [
    "merchant",
    "transaction_date",
    "transaction_time",
    "subtotal",
    "tax",
    "tip",
    "total",
    "payment_method",
    "last_four",
    "currency",
]


def find_catalog_record(packet_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
    for record in records:
        if record.get("packet_id") == packet_id:
            return record
    raise SystemExit("Packet ID not found in catalog.")


def read_ocr_preview(packet_dir: Path, lines: int) -> str:
    text_path = packet_dir / "output" / "scan.txt"
    if not text_path.exists():
        return ""
    text = text_path.read_text(encoding="utf-8", errors="replace")
    preview = "\n".join(text.splitlines()[:max(lines, 0)])
    if len(preview) > 3000:
        preview = preview[:3000]
    return preview


def load_inspection(packet_id: str, *, lines: int = 80) -> dict[str, Any]:
    record = find_catalog_record(packet_id, load_catalog_records(catalog_path()))
    packet_dir = Path(str(record.get("source_packet_dir") or "")).expanduser()
    packet_path = packet_dir / "packet.json"
    extract_path = packet_dir / "extract" / "extract.json"
    if not extract_path.exists():
        raise SystemExit("No extraction sidecar found for packet.")

    packet = load_json(packet_path) if packet_path.exists() else {}
    extraction = load_json(extract_path)
    correction = optional_json(packet_dir / "extract" / "correction.json") or {}
    return {
        "packet_id": record.get("packet_id"),
        "catalog_record": record,
        "packet": packet,
        "fields": extraction.get("fields") or {},
        "corrections": correction.get("corrections") or {},
        "warnings": extraction.get("warnings") or [],
        "ocr_preview": read_ocr_preview(packet_dir, lines),
    }


def print_inspection(inspection: dict[str, Any]) -> None:
    record = inspection.get("catalog_record") or {}
    fields = inspection.get("fields") or {}
    corrections = inspection.get("corrections") or {}
    print("\nLAIA Librarian Extract Inspect\n")
    print(f"Packet ID: {inspection.get('packet_id')}")
    print(f"Project: {record.get('project')}")
    print(f"Category: {record.get('approved_category') or record.get('category')}")
    print(f"Source: {record.get('source_packet_dir')}")

    print("\nExtracted Fields:")
    for field in FIELD_ORDER:
        print(f"  {field}: {fields.get(field)}")

    print("\nCorrections:")
    if corrections:
        for field, change in corrections.items():
            if isinstance(change, dict):
                print(f"  {field}: {change.get('original')} -> {change.get('corrected')}")
            else:
                print(f"  {field}: {change}")
    else:
        print("  No corrections found.")

    print("\nWarnings:")
    warnings = inspection.get("warnings") or []
    if warnings:
        for warning in warnings:
            print(f"  {warning}")
    else:
        print("  none")

    print("\nOCR Preview:")
    preview = inspection.get("ocr_preview") or ""
    if preview:
        for line in preview.splitlines():
            print(f"  {line}")
    else:
        print("  no OCR text found")

    packet_id = inspection.get("packet_id")
    print("\nUseful commands:")
    print(f"  bin/laia librarian correct-extract --packet {packet_id} --transaction-date YYYY-MM-DD")
    print(f"  bin/laia librarian correct-extract --packet {packet_id} --total 0.00")
    print("")


def command_inspect_extract(args) -> None:
    inspection = load_inspection(
        getattr(args, "packet", ""),
        lines=int(getattr(args, "lines", 80) or 80),
    )
    if getattr(args, "json", False):
        print(json.dumps(inspection, indent=2, sort_keys=False) + "\n")
        return
    print_inspection(inspection)
