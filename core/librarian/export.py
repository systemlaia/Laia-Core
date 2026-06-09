import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.catalog import catalog_path, load_catalog_records
    from librarian.finalize import slugify
    from librarian.summarize import load_json
except ModuleNotFoundError:
    from core.librarian.catalog import catalog_path, load_catalog_records
    from core.librarian.finalize import slugify
    from core.librarian.summarize import load_json


DEFAULT_EXPORT_ROOT = Path.home() / "LAIA" / "Exports"
CSV_FIELDS = [
    "packet_id",
    "project",
    "category",
    "created_at",
    "finalized_at",
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
    "extraction_confidence",
    "extraction_warnings",
    "corrections_applied",
    "corrected_fields",
    "source_packet_dir",
    "archive_packet_dir",
]


def record_category(record: dict[str, Any]) -> str:
    return str(record.get("approved_category") or record.get("category") or "")


def select_export_records(
    records: list[dict[str, Any]],
    *,
    project: str = "",
    category: str = "",
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    selected = list(records)
    if project:
        selected = [
            record for record in selected
            if str(record.get("project") or "").lower() == project.lower()
        ]
    if category:
        selected = [
            record for record in selected
            if record_category(record).lower() == category.lower()
        ]

    indexed = list(enumerate(selected))
    indexed.sort(
        key=lambda item: (str(item[1].get("finalized_at") or ""), item[0]),
        reverse=True,
    )
    selected = [record for _index, record in indexed]
    if limit is not None:
        selected = selected[:limit]
    return selected


def empty_none(value: Any) -> Any:
    return "" if value is None else value


def load_correction_for_record(record: dict[str, Any]) -> dict[str, Any]:
    packet_dir = Path(str(record.get("source_packet_dir") or "")).expanduser()
    correction_path = packet_dir / "extract" / "correction.json"
    if not correction_path.exists():
        return {}
    try:
        return load_json(correction_path)
    except Exception:
        return {}


def correction_values(correction: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    corrections = correction.get("corrections") or {}
    values = {}
    fields = []
    for field, item in corrections.items():
        if not isinstance(item, dict):
            continue
        values[field] = item.get("corrected")
        fields.append(field)
    return values, fields


def row_from_record(
    record: dict[str, Any],
    extraction: dict[str, Any],
    correction: Optional[dict[str, Any]] = None,
    *,
    apply_corrections: bool = True,
) -> dict[str, Any]:
    fields = extraction.get("fields") or {}
    warnings = extraction.get("warnings") or []
    confidence = fields.get("confidence", extraction.get("confidence"))
    exported_fields = dict(fields)
    corrected_values, corrected_fields = correction_values(correction or {})
    if apply_corrections and corrected_values:
        exported_fields.update(corrected_values)
    else:
        corrected_fields = []
    return {
        "packet_id": empty_none(record.get("packet_id")),
        "project": empty_none(record.get("project")),
        "category": empty_none(record_category(record)),
        "created_at": empty_none(record.get("created_at")),
        "finalized_at": empty_none(record.get("finalized_at")),
        "merchant": empty_none(exported_fields.get("merchant")),
        "transaction_date": empty_none(exported_fields.get("transaction_date")),
        "transaction_time": empty_none(exported_fields.get("transaction_time")),
        "subtotal": empty_none(exported_fields.get("subtotal")),
        "tax": empty_none(exported_fields.get("tax")),
        "tip": empty_none(exported_fields.get("tip")),
        "total": empty_none(exported_fields.get("total")),
        "payment_method": empty_none(exported_fields.get("payment_method")),
        "last_four": empty_none(exported_fields.get("last_four")),
        "currency": empty_none(exported_fields.get("currency")),
        "extraction_confidence": empty_none(confidence),
        "extraction_warnings": "; ".join(str(warning) for warning in warnings),
        "corrections_applied": "true" if corrected_fields else "false",
        "corrected_fields": "; ".join(corrected_fields),
        "corrections": correction.get("corrections", {}) if correction and corrected_fields else {},
        "source_packet_dir": empty_none(record.get("source_packet_dir")),
        "archive_packet_dir": empty_none(record.get("destination_packet_dir")),
    }


def load_extract_for_record(record: dict[str, Any]) -> tuple[Optional[dict[str, Any]], str]:
    packet_dir = Path(str(record.get("source_packet_dir") or "")).expanduser()
    extract_path = packet_dir / "extract" / "extract.json"
    if not extract_path.exists():
        return None, "missing"
    try:
        return load_json(extract_path), ""
    except Exception:
        return None, "invalid"


def build_export(records: list[dict[str, Any]], *, apply_corrections: bool = True) -> dict[str, Any]:
    rows = []
    skipped_missing = 0
    skipped_invalid = 0
    for record in records:
        extraction, status = load_extract_for_record(record)
        if status == "missing":
            skipped_missing += 1
            continue
        if status == "invalid":
            skipped_invalid += 1
            continue
        correction = load_correction_for_record(record) if apply_corrections else {}
        rows.append(
            row_from_record(
                record,
                extraction or {},
                correction,
                apply_corrections=apply_corrections,
            )
        )
    return {
        "selected_catalog_records": len(records),
        "exported_records": len(rows),
        "skipped_missing_extract": skipped_missing,
        "skipped_invalid_extract": skipped_invalid,
        "records": rows,
    }


def default_output_path(project: str, fmt: str, export_root: Path = DEFAULT_EXPORT_ROOT) -> Path:
    slug = slugify(project or "exports")
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H%M%S")
    return export_root / slug / f"{slug}_{timestamp}.{fmt}"


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in CSV_FIELDS})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def export_catalog(args) -> tuple[Path, dict[str, Any]]:
    fmt = str(getattr(args, "format", "csv") or "csv").lower()
    if fmt not in {"csv", "json"}:
        raise SystemExit("Unsupported export format. Use csv or json.")
    limit_value = getattr(args, "limit", None)
    limit = int(limit_value) if limit_value is not None else None
    project = getattr(args, "project", "") or ""
    category = getattr(args, "category", "") or ""
    records = select_export_records(
        load_catalog_records(catalog_path()),
        project=project,
        category=category,
        limit=limit,
    )
    apply_corrections = not bool(getattr(args, "raw", False))
    export = build_export(records, apply_corrections=apply_corrections)
    exported_at = datetime.now().astimezone().isoformat(timespec="seconds")
    payload = {
        "exported_at": exported_at,
        "filters": {
            "project": project,
            "category": category,
            "limit": limit,
            "apply_corrections": apply_corrections,
        },
        "count": export["exported_records"],
        "skipped_missing_extract": export["skipped_missing_extract"],
        "skipped_invalid_extract": export["skipped_invalid_extract"],
        "records": export["records"],
    }
    output = getattr(args, "output", "") or ""
    output_path = Path(output).expanduser() if output else default_output_path(project or category or "exports", fmt)
    if fmt == "csv":
        write_csv(output_path, export["records"])
    else:
        write_json(output_path, payload)

    summary = {
        **export,
        "format": fmt,
        "output": str(output_path),
        "fields": CSV_FIELDS,
        "payload": payload,
    }
    return output_path, summary


def print_summary(output_path: Path, summary: dict[str, Any]) -> None:
    print("\nLAIA Librarian Export Complete\n")
    print(f"Format: {summary['format']}")
    print(f"Output: {output_path}")
    print("")
    print(f"Selected catalog records: {summary['selected_catalog_records']}")
    print(f"Exported records: {summary['exported_records']}")
    print(f"Skipped missing extract: {summary['skipped_missing_extract']}")
    print(f"Skipped invalid extract: {summary['skipped_invalid_extract']}")
    print("\nFields:")
    print("  " + ", ".join(CSV_FIELDS))
    print("")


def command_export(args) -> None:
    output_path, summary = export_catalog(args)
    print_summary(output_path, summary)
