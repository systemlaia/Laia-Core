import json
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.index import DEFAULT_INGEST_ROOT, load_packet
    from librarian.summarize import load_json, optional_json
except ModuleNotFoundError:
    from core.librarian.index import DEFAULT_INGEST_ROOT, load_packet
    from core.librarian.summarize import load_json, optional_json


def sort_key(packet: dict[str, Any]) -> tuple[str, float]:
    created = str(packet.get("created_at") or "")
    return created, float(packet.get("_mtime") or 0.0)


def pending_record(packet_json: Path) -> Optional[dict[str, Any]]:
    packet_dir = packet_json.parent
    review_path = packet_dir / "review" / "review.json"
    if not review_path.exists():
        return None
    if (packet_dir / "approval" / "approval.json").exists():
        return None
    if (packet_dir / "final" / "final.json").exists():
        return None

    packet = load_packet(packet_json)
    review = load_json(review_path)
    classification = optional_json(packet_dir / "classify" / "classification.json") or {}

    return {
        "created_at": packet.get("created_at") or "",
        "packet_folder": packet_dir.name,
        "project": packet.get("project"),
        "packet_type": packet.get("packet_type"),
        "primary_category": classification.get("primary_category") or review.get("primary_category"),
        "confidence": float(classification.get("confidence", review.get("confidence") or 0.0) or 0.0),
        "recommended_action": review.get("recommended_action"),
        "source_packet_dir": str(packet_dir),
        "_mtime": packet_dir.stat().st_mtime,
    }


def list_pending_packets(ingest_root: Path = DEFAULT_INGEST_ROOT, limit: int = 20) -> list[dict[str, Any]]:
    if not ingest_root.exists():
        return []
    records = []
    for packet_json in ingest_root.rglob("packet.json"):
        try:
            record = pending_record(packet_json)
        except SystemExit:
            continue
        except Exception:
            continue
        if record:
            records.append(record)

    records.sort(key=sort_key, reverse=True)
    return records[:limit]


def public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def print_pending(records: list[dict[str, Any]]) -> None:
    print("\nLAIA Librarian Pending Reviews\n")
    print(f"Count: {len(records)}")
    if not records:
        print("\nNo pending review packets found.")
        print("")
        return

    for index, record in enumerate(records, start=1):
        print("")
        print(f"{index}. {record.get('created_at')}")
        print(f"   Packet: {record.get('packet_folder')}")
        print(f"   Project: {record.get('project')}")
        print(f"   Type: {record.get('packet_type')}")
        print(f"   Category: {record.get('primary_category')}")
        print(f"   Confidence: {record.get('confidence', 0.0):.2f}")
        print(f"   Recommended Action: {record.get('recommended_action')}")
        print(f"   Path: {record.get('source_packet_dir')}")

    print("\nNext:")
    print("  laia librarian approve --last")
    print("  laia librarian correct --last --category <category>")
    print("")


def command_pending(args) -> None:
    limit = int(getattr(args, "limit", 20) or 20)
    records = list_pending_packets(limit=limit)
    public_records = [public_record(record) for record in records]
    if getattr(args, "json", False):
        print(json.dumps({"count": len(public_records), "pending": public_records}, indent=2) + "\n")
        return
    print_pending(public_records)
