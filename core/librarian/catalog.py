import json
from pathlib import Path
from typing import Any

try:
    from librarian.finalize import DEFAULT_CATALOG_ROOT
except ModuleNotFoundError:
    from core.librarian.finalize import DEFAULT_CATALOG_ROOT


def catalog_path(catalog_root: Path = DEFAULT_CATALOG_ROOT) -> Path:
    return catalog_root / "ingest_catalog.jsonl"


def load_catalog_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"Catalog file not found: {path}")

    records = []
    with path.open("r", encoding="utf-8") as f:
        for line_number, line in enumerate(f, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)

    if not records:
        raise SystemExit(f"No valid catalog records found in {path}")
    return records


def latest_catalog_record(path: Path) -> dict[str, Any]:
    return load_catalog_records(path)[-1]


def query_catalog_records(
    records: list[dict[str, Any]],
    *,
    project: str = "",
    category: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    filtered = list(records)
    if project:
        filtered = [
            record for record in filtered
            if str(record.get("project") or "").lower() == project.lower()
        ]
    if category:
        filtered = [
            record for record in filtered
            if str(record.get("approved_category") or record.get("category") or "").lower() == category.lower()
        ]
    filtered.reverse()
    return filtered[:limit]


def print_catalog_entry(record: dict[str, Any]) -> None:
    print("\nLAIA Librarian Catalog Entry\n")
    print(f"Packet ID: {record.get('packet_id')}")
    print(f"Type: {record.get('packet_type')}")
    print(f"Project: {record.get('project')}")
    print(f"Category: {record.get('approved_category')}")
    if "document_type" in record:
        print(f"Document Type: {record.get('document_type')}")
    if "classification_corrected" in record:
        print(f"Classification Corrected: {str(bool(record.get('classification_corrected'))).lower()}")
    print(f"Confidence: {float(record.get('confidence') or 0.0):.2f}")
    print(f"Pages: {record.get('page_count')}")
    print(f"Words: {record.get('word_count')}")
    print(f"Created: {record.get('created_at')}")
    print(f"Finalized: {record.get('finalized_at')}")
    print(f"Source Packet: {record.get('source_packet_dir')}")
    print(f"Archive Packet: {record.get('destination_packet_dir') or 'not routed'}")
    print("")


def print_catalog_query(records: list[dict[str, Any]]) -> None:
    print("\nLAIA Librarian Catalog Query\n")
    print(f"Count: {len(records)}")
    for index, record in enumerate(records, start=1):
        print("")
        print(f"{index}. {record.get('packet_id')}")
        print(f"   Project: {record.get('project')}")
        print(f"   Category: {record.get('approved_category') or record.get('category')}")
        if "document_type" in record:
            print(f"   Document Type: {record.get('document_type')}")
        if "classification_corrected" in record:
            print(f"   Classification Corrected: {str(bool(record.get('classification_corrected'))).lower()}")
        print(f"   Confidence: {float(record.get('confidence') or 0.0):.2f}")
        print(f"   Pages: {record.get('page_count')}")
        print(f"   Words: {record.get('word_count')}")
        print(f"   Created: {record.get('created_at')}")
        print(f"   Finalized: {record.get('finalized_at')}")
        print(f"   Source: {record.get('source_packet_dir')}")
    print("")


def command_catalog(args) -> None:
    path = catalog_path()
    if getattr(args, "last", False):
        record = latest_catalog_record(path)
        print_catalog_entry(record)
        return

    records = query_catalog_records(
        load_catalog_records(path),
        project=getattr(args, "project", "") or "",
        category=getattr(args, "category", "") or "",
        limit=int(getattr(args, "limit", 20) or 20),
    )
    if getattr(args, "json", False):
        print(json.dumps({"count": len(records), "records": records}, indent=2) + "\n")
        return
    print_catalog_query(records)
