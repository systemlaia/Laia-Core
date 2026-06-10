import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.catalog import catalog_path, load_catalog_records
    from librarian.finalize import packet_id_for
    from librarian.index import DEFAULT_INGEST_ROOT, load_packet
    from librarian.summarize import load_json, optional_json
except ModuleNotFoundError:
    from core.librarian.catalog import catalog_path, load_catalog_records
    from core.librarian.finalize import packet_id_for
    from core.librarian.index import DEFAULT_INGEST_ROOT, load_packet
    from core.librarian.summarize import load_json, optional_json


def catalog_records_if_available() -> list[dict[str, Any]]:
    try:
        return load_catalog_records(catalog_path())
    except SystemExit:
        return []


def find_packet_by_id(packet_id: str, ingest_root: Path = DEFAULT_INGEST_ROOT) -> Path:
    for packet_json in ingest_root.rglob("packet.json"):
        try:
            packet = load_packet(packet_json)
        except Exception:
            continue
        if packet.get("packet_id") == packet_id or packet_id_for(packet_json, packet) == packet_id:
            return packet_json

    for record in catalog_records_if_available():
        if record.get("packet_id") != packet_id:
            continue
        packet_json = Path(str(record.get("source_packet_dir") or "")).expanduser() / "packet.json"
        if packet_json.exists():
            return packet_json

    raise SystemExit("Packet ID not found.")


def require_classification(packet_dir: Path) -> Path:
    classification_path = packet_dir / "classify" / "classification.json"
    if not classification_path.exists():
        raise SystemExit("No classification sidecar found for packet.")
    return classification_path


def read_classification_correction(packet_dir: Path) -> dict[str, Any]:
    return optional_json(packet_dir / "classify" / "correction.json") or {}


def build_correction(
    packet_json: Path,
    *,
    category: str,
    document_type: str = "",
    notes: Optional[list[str]] = None,
) -> dict[str, Any]:
    packet = load_packet(packet_json)
    packet_dir = packet_json.parent
    classification = load_json(require_classification(packet_dir))
    corrected = {"primary_category": category}
    if document_type:
        corrected["document_type"] = document_type

    return {
        "correction_type": "laia.librarian.classification_correction",
        "packet_id": packet.get("packet_id") or packet_id_for(packet_json, packet),
        "packet_dir": str(packet_dir),
        "corrected_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "corrector": "human",
        "original": {
            "primary_category": classification.get("primary_category"),
            "confidence": classification.get("confidence"),
            "matched_keywords": classification.get("matched_keywords") or {},
        },
        "corrected": corrected,
        "notes": notes or [],
    }


def markdown_correction(correction: dict[str, Any]) -> str:
    original = correction.get("original") or {}
    corrected = correction.get("corrected") or {}
    lines = [
        "# LAIA Classification Correction",
        "",
        f"Packet ID: {correction.get('packet_id')}",
        f"Corrected At: {correction.get('corrected_at')}",
        "",
        "Original:",
        f"- Category: {original.get('primary_category')}",
        f"- Confidence: {original.get('confidence')}",
        f"- Matched Keywords: {json.dumps(original.get('matched_keywords') or {}, sort_keys=True)}",
        "",
        "Corrected:",
        f"- Category: {corrected.get('primary_category')}",
        f"- Document Type: {corrected.get('document_type') or ''}",
        "",
        "Notes:",
    ]
    notes = correction.get("notes") or []
    if notes:
        for note in notes:
            lines.append(f"- {note}")
    else:
        lines.append("- none")
    lines.append("")
    return "\n".join(lines)


def write_correction(packet_json: Path, correction: dict[str, Any]) -> tuple[Path, Path]:
    classify_dir = packet_json.parent / "classify"
    classify_dir.mkdir(parents=True, exist_ok=True)
    correction_json = classify_dir / "correction.json"
    correction_md = classify_dir / "correction.md"
    correction_json.write_text(json.dumps(correction, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    correction_md.write_text(markdown_correction(correction), encoding="utf-8")
    return correction_json, correction_md


def print_summary(correction: dict[str, Any], correction_json: Path, correction_md: Path) -> None:
    original = correction.get("original") or {}
    corrected = correction.get("corrected") or {}
    print("\nLAIA Librarian Classification Correction Complete\n")
    print(f"Packet: {correction.get('packet_dir')}")
    print(f"Packet ID: {correction.get('packet_id')}")
    print(f"Category: {original.get('primary_category')} -> {corrected.get('primary_category')}")
    if corrected.get("document_type"):
        print(f"Document Type: {corrected.get('document_type')}")
    print("\nWrote:")
    packet_dir = Path(str(correction.get("packet_dir")))
    print(f"  {correction_json.relative_to(packet_dir)}")
    print(f"  {correction_md.relative_to(packet_dir)}")
    print("")


def command_correct_classification(args) -> None:
    packet_json = find_packet_by_id(getattr(args, "packet", ""))
    notes = getattr(args, "note", None) or []
    if isinstance(notes, str):
        notes = [notes]
    correction = build_correction(
        packet_json,
        category=str(getattr(args, "category", "") or ""),
        document_type=str(getattr(args, "document_type", "") or ""),
        notes=[str(note) for note in notes],
    )
    correction_json, correction_md = write_correction(packet_json, correction)
    print_summary(correction, correction_json, correction_md)
