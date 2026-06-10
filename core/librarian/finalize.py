import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.index import DEFAULT_INGEST_ROOT, load_packet
    from librarian.summarize import load_json, optional_json
except ModuleNotFoundError:
    from core.librarian.index import DEFAULT_INGEST_ROOT, load_packet
    from core.librarian.summarize import load_json, optional_json


DEFAULT_CATALOG_ROOT = Path.home() / "LAIA" / "Catalog"


def require_sidecar(packet_dir: Path, relative_path: str, stage: str) -> Path:
    path = packet_dir / relative_path
    if not path.exists():
        raise SystemExit(f"Packet must have {stage} before finalization: missing {path}")
    return path


def find_approved_unfinalized_packet(ingest_root: Path = DEFAULT_INGEST_ROOT) -> Path:
    candidates = []
    for packet_json in ingest_root.rglob("packet.json"):
        packet_dir = packet_json.parent
        if (packet_dir / "final" / "final.json").exists():
            continue
        approval_path = packet_dir / "approval" / "approval.json"
        if not approval_path.exists():
            continue
        try:
            approval = load_json(approval_path)
        except Exception:
            continue
        if approval.get("review_status") != "approved":
            continue
        candidates.append(packet_json)

    if not candidates:
        raise SystemExit("No approved unfinalized packet found to finalize.")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def slugify(value: Optional[str]) -> str:
    text = str(value or "inbox").strip().lower()
    chars = []
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
        elif ch in (" ", "-", "_"):
            chars.append("-")
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "inbox"


def packet_kind(packet_type: Optional[str]) -> str:
    if packet_type == "laia.ingest.scan":
        return "scan"
    text = str(packet_type or "packet")
    return slugify(text.split(".")[-1])


def packet_id_for(packet_json: Path, packet: dict[str, Any]) -> str:
    packet_dir = packet_json.parent
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})_(\d{6})_(.+)$", packet_dir.name)
    kind = packet_kind(packet.get("packet_type"))
    if match:
        year, month, day, hhmmss, suffix = match.groups()
        return f"laia-{kind}-{year}{month}{day}-{hhmmss[:2]}{hhmmss[2:4]}{hhmmss[4:]}-{slugify(suffix)}"

    created = str(packet.get("created_at") or "")
    created_match = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})", created)
    project = slugify(packet.get("project"))
    if created_match:
        year, month, day, hour, minute, second = created_match.groups()
        return f"laia-{kind}-{year}{month}{day}-{hour}{minute}{second}-{project}"

    compact_path = re.sub(r"[^a-z0-9]+", "-", str(packet_dir).lower()).strip("-")
    return f"laia-{kind}-{compact_path[-40:]}"


def build_final(packet_json: Path) -> dict[str, Any]:
    packet = load_packet(packet_json)
    packet_dir = packet_json.parent
    if (packet_dir / "final" / "final.json").exists():
        raise SystemExit(f"Packet is already finalized: {packet_dir}")
    index = load_json(require_sidecar(packet_dir, "index/index.json", "an index"))
    summary = load_json(require_sidecar(packet_dir, "summary/summary.json", "a summary"))
    classification = load_json(
        require_sidecar(packet_dir, "classify/classification.json", "a classification")
    )
    review = load_json(require_sidecar(packet_dir, "review/review.json", "a review"))
    approval = load_json(require_sidecar(packet_dir, "approval/approval.json", "an approval"))
    route = optional_json(packet_dir / "route" / "route.json")

    if approval.get("review_status") != "approved":
        raise SystemExit(
            f"Only approved packets can be finalized; found review_status={approval.get('review_status')}"
        )

    text_stats = index.get("text_stats") or {}
    finalized_at = datetime.now().astimezone().isoformat(timespec="seconds")
    routed = bool(route)
    confidence = approval.get("confidence", classification.get("confidence", 0.0))

    return {
        "final_type": "laia.librarian.final",
        "packet_type": packet.get("packet_type"),
        "project": packet.get("project"),
        "created_at": packet.get("created_at"),
        "finalized_at": finalized_at,
        "approved_category": approval.get("approved_category"),
        "document_type": approval.get("document_type"),
        "classification_corrected": bool(approval.get("classification_corrected")),
        "confidence": float(confidence or 0.0),
        "page_count": packet.get("page_count", summary.get("page_count", 0)),
        "word_count": text_stats.get("word_count", summary.get("word_count", 0)),
        "ocr_status": summary.get("ocr_status"),
        "pdf_status": summary.get("pdf_status"),
        "routed": routed,
        "destination_packet_dir": route.get("destination_packet_dir") if route else "",
        "source_packet_dir": str(packet_dir),
        "packet_id": packet_id_for(packet_json, packet),
        "catalog_status": "finalized",
        "source_review_status": review.get("review_status"),
    }


def catalog_record(final: dict[str, Any]) -> dict[str, Any]:
    return {
        "packet_id": final.get("packet_id"),
        "packet_type": final.get("packet_type"),
        "project": final.get("project"),
        "created_at": final.get("created_at"),
        "finalized_at": final.get("finalized_at"),
        "approved_category": final.get("approved_category"),
        "document_type": final.get("document_type"),
        "classification_corrected": bool(final.get("classification_corrected")),
        "confidence": final.get("confidence"),
        "page_count": final.get("page_count"),
        "word_count": final.get("word_count"),
        "source_packet_dir": final.get("source_packet_dir"),
        "destination_packet_dir": final.get("destination_packet_dir"),
    }


def markdown_final(final: dict[str, Any]) -> str:
    destination = final.get("destination_packet_dir") or "not routed"
    return (
        "# LAIA Ingest Final Record\n\n"
        f"- Packet ID: {final.get('packet_id')}\n"
        f"- Packet: {final.get('source_packet_dir')}\n"
        f"- Project: {final.get('project')}\n"
        f"- Final Category: {final.get('approved_category')}\n"
        f"- Document Type: {final.get('document_type') or ''}\n"
        f"- Classification Corrected: {final.get('classification_corrected')}\n"
        f"- Confidence: {final.get('confidence', 0.0):.2f}\n"
        f"- Pages: {final.get('page_count')}\n"
        f"- Words: {final.get('word_count')}\n"
        f"- OCR: {final.get('ocr_status')}\n"
        f"- PDF: {final.get('pdf_status')}\n"
        f"- Route Destination: {destination}\n"
        f"- Finalized: {final.get('finalized_at')}\n"
        f"- Catalog Status: {final.get('catalog_status')}\n\n"
        "`packet.json` remains unchanged. Finalization is recorded as a sidecar "
        "and a compact catalog entry.\n"
    )


def write_final(packet_json: Path, final: dict[str, Any]) -> tuple[Path, Path]:
    final_dir = packet_json.parent / "final"
    final_dir.mkdir(parents=True, exist_ok=True)
    final_json = final_dir / "final.json"
    final_md = final_dir / "final.md"
    final_json.write_text(json.dumps(final, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    final_md.write_text(markdown_final(final), encoding="utf-8")
    return final_json, final_md


def catalog_contains_packet_id(catalog_path: Path, packet_id: str) -> bool:
    if not catalog_path.exists():
        return False
    with catalog_path.open("r", encoding="utf-8") as f:
        for line in f:
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and record.get("packet_id") == packet_id:
                return True
    return False


def append_catalog_record(final: dict[str, Any], catalog_root: Path = DEFAULT_CATALOG_ROOT) -> Path:
    catalog_root.mkdir(parents=True, exist_ok=True)
    catalog_path = catalog_root / "ingest_catalog.jsonl"
    if catalog_contains_packet_id(catalog_path, str(final.get("packet_id") or "")):
        print("Catalog already contains packet_id; skipping append.")
        return catalog_path
    with catalog_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(catalog_record(final), sort_keys=False) + "\n")
    return catalog_path


def print_summary(final: dict[str, Any], final_json: Path, final_md: Path, catalog_path: Path) -> None:
    print("\nLAIA Librarian Finalize Complete\n")
    print(f"Packet: {final['source_packet_dir']}")
    print(f"Packet ID: {final['packet_id']}")
    print(f"Type: {final['packet_type']}")
    print(f"Project: {final.get('project')}")
    print(f"Final Category: {final.get('approved_category')}")
    print(f"Confidence: {final.get('confidence', 0.0):.2f}")
    print(f"Catalog Status: {final.get('catalog_status')}")
    print("\nWrote:")
    packet_dir = Path(final["source_packet_dir"])
    print(f"  {final_json.relative_to(packet_dir)}")
    print(f"  {final_md.relative_to(packet_dir)}")
    print(f"  {catalog_path}")
    print("\nNext:")
    print("  laia librarian catalog --last")
    print("")


def command_finalize(args) -> None:
    if not getattr(args, "last", False):
        raise SystemExit("Only --last is supported for v0: laia librarian finalize --last")
    packet_json = find_approved_unfinalized_packet()
    final = build_final(packet_json)
    final_json, final_md = write_final(packet_json, final)
    catalog_path = append_catalog_record(final)
    print_summary(final, final_json, final_md, catalog_path)
