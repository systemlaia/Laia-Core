import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.index import find_latest_packet, load_packet, path_from_packet
    from librarian.route import require_index
except ModuleNotFoundError:
    from core.librarian.index import find_latest_packet, load_packet, path_from_packet
    from core.librarian.route import require_index


PREVIEW_LIMIT = 1000


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def optional_json(path: Path) -> Optional[dict[str, Any]]:
    if not path.exists():
        return None
    return load_json(path)


def read_text_preview(text_path: Optional[Path], limit: int = PREVIEW_LIMIT) -> str:
    if not text_path or not text_path.exists():
        return ""
    text = text_path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip()


def build_summary(packet_json: Path, preview_limit: int = PREVIEW_LIMIT) -> dict[str, Any]:
    packet = load_packet(packet_json)
    packet_dir = packet_json.parent
    index_path = require_index(packet_dir)
    index = load_json(index_path)
    route = optional_json(packet_dir / "route" / "route.json")
    text_path = path_from_packet(packet, "text")
    text_preview = read_text_preview(text_path, limit=preview_limit)
    text_stats = index.get("text_stats") or {}

    routed = bool(route)
    return {
        "summary_type": "laia.librarian.summary",
        "summarized_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "packet_type": packet.get("packet_type"),
        "project": packet.get("project"),
        "created_at": packet.get("created_at"),
        "page_count": packet.get("page_count", 0),
        "word_count": text_stats.get("word_count", 0),
        "character_count": text_stats.get("character_count", 0),
        "line_count": text_stats.get("line_count", 0),
        "ocr_status": packet.get("ocr_status") or ("complete" if packet.get("ocr_completed") else "missing"),
        "pdf_status": packet.get("pdf_status") or ("created" if packet.get("pdf_created") else "missing"),
        "routed": routed,
        "destination_packet_dir": route.get("destination_packet_dir") if route else "",
        "text_preview": text_preview,
        "source_packet_dir": str(packet_dir),
    }


def markdown_summary(summary: dict[str, Any]) -> str:
    routed = "yes" if summary.get("routed") else "no"
    destination = summary.get("destination_packet_dir") or "not routed"
    preview = summary.get("text_preview") or "_No OCR text preview available._"
    return (
        "# LAIA Ingest Summary\n\n"
        f"- Packet Type: `{summary.get('packet_type')}`\n"
        f"- Project: {summary.get('project')}\n"
        f"- Created: {summary.get('created_at')}\n"
        f"- Pages: {summary.get('page_count')}\n"
        f"- Words: {summary.get('word_count')}\n"
        f"- Characters: {summary.get('character_count')}\n"
        f"- Lines: {summary.get('line_count')}\n"
        f"- OCR: {summary.get('ocr_status')}\n"
        f"- PDF: {summary.get('pdf_status')}\n"
        f"- Routed: {routed}\n"
        f"- Destination: {destination}\n\n"
        "## Text Preview\n\n"
        f"{preview}\n"
    )


def write_summary(packet_json: Path, summary: dict[str, Any]) -> tuple[Path, Path]:
    summary_dir = packet_json.parent / "summary"
    summary_dir.mkdir(parents=True, exist_ok=True)
    summary_json = summary_dir / "summary.json"
    summary_md = summary_dir / "summary.md"
    summary_json.write_text(json.dumps(summary, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    summary_md.write_text(markdown_summary(summary), encoding="utf-8")
    return summary_md, summary_json


def print_summary(summary: dict[str, Any], summary_md: Path, summary_json: Path) -> None:
    print("\nLAIA Librarian Summary Complete\n")
    print(f"Packet: {summary['source_packet_dir']}")
    print(f"Type: {summary['packet_type']}")
    print(f"Project: {summary.get('project')}")
    print(f"Pages: {summary.get('page_count')}")
    print(f"Words: {summary.get('word_count')}")
    print(f"OCR: {summary.get('ocr_status')}")
    print(f"Routed: {'yes' if summary.get('routed') else 'no'}")
    print("\nWrote:")
    packet_dir = Path(summary["source_packet_dir"])
    print(f"  {summary_md.relative_to(packet_dir)}")
    print(f"  {summary_json.relative_to(packet_dir)}")
    print("\nNext:")
    print("  laia librarian classify --last")
    print("")


def command_summarize(args) -> None:
    if not getattr(args, "last", False):
        raise SystemExit("Only --last is supported for v0: laia librarian summarize --last")
    packet_json = find_latest_packet()
    summary = build_summary(packet_json)
    summary_md, summary_json = write_summary(packet_json, summary)
    print_summary(summary, summary_md, summary_json)
