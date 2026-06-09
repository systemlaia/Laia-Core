import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


DEFAULT_INGEST_ROOT = Path.home() / "LAIA" / "Inbox" / "Ingest"
IMAGE_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp"}


def find_latest_packet(ingest_root: Path = DEFAULT_INGEST_ROOT) -> Path:
    packets = [path for path in ingest_root.rglob("packet.json") if path.is_file()]
    if not packets:
        raise SystemExit(f"No ingest packets found under {ingest_root}")
    return max(packets, key=lambda path: path.stat().st_mtime)


def load_packet(packet_json: Path) -> dict[str, Any]:
    with packet_json.open("r", encoding="utf-8") as f:
        packet = json.load(f)
    packet_type = str(packet.get("packet_type", ""))
    if not packet_type.startswith("laia.ingest."):
        raise SystemExit(f"Unsupported packet_type for Librarian ingest index: {packet_type}")
    return packet


def path_from_packet(packet: dict[str, Any], key: str) -> Optional[Path]:
    value = (packet.get("paths") or {}).get(key)
    if not value:
        return None
    return Path(value).expanduser()


def text_stats(text_path: Optional[Path]) -> tuple[bool, dict[str, int]]:
    if not text_path or not text_path.exists():
        return False, {"character_count": 0, "word_count": 0, "line_count": 0}
    text = text_path.read_text(encoding="utf-8", errors="replace")
    return True, {
        "character_count": len(text),
        "word_count": len(re.findall(r"\b\w+\b", text)),
        "line_count": len(text.splitlines()),
    }


def file_inventory(packet: dict[str, Any]) -> dict[str, Any]:
    source_dir = path_from_packet(packet, "source_dir")
    source_images = []
    if source_dir and source_dir.exists():
        source_images = [
            path
            for path in source_dir.iterdir()
            if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS
        ]

    pdf = path_from_packet(packet, "pdf")
    ocr_pdf = path_from_packet(packet, "ocr_pdf")
    text = path_from_packet(packet, "text")
    scan_log = path_from_packet(packet, "scan_log")

    return {
        "source_image_count": len(source_images),
        "pdf_exists": bool(pdf and pdf.exists()),
        "ocr_pdf_exists": bool(ocr_pdf and ocr_pdf.exists()),
        "text_exists": bool(text and text.exists()),
        "scan_log_exists": bool(scan_log and scan_log.exists()),
    }


def build_index(packet_json: Path) -> dict[str, Any]:
    packet = load_packet(packet_json)
    packet_dir = packet_json.parent
    text_path = path_from_packet(packet, "text")
    text_available, stats = text_stats(text_path)
    inventory = file_inventory(packet)

    return {
        "index_type": "laia.librarian.index",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "packet_json": str(packet_json),
        "packet_dir": str(packet_dir),
        "packet_type": packet.get("packet_type"),
        "project": packet.get("project"),
        "page_count": packet.get("page_count", 0),
        "ocr_text_available": text_available,
        "text_stats": stats,
        "file_inventory": inventory,
    }


def write_index(packet_json: Path, index: dict[str, Any]) -> Path:
    index_dir = packet_json.parent / "index"
    index_dir.mkdir(parents=True, exist_ok=True)
    index_path = index_dir / "index.json"
    index_path.write_text(json.dumps(index, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return index_path


def print_summary(index: dict[str, Any], index_path: Path) -> None:
    inventory = index["file_inventory"]
    stats = index["text_stats"]
    print("\nLAIA Librarian Index Complete\n")
    print(f"Packet: {index['packet_dir']}")
    print(f"Type: {index['packet_type']}")
    print(f"Project: {index.get('project')}")
    print(f"Pages: {index.get('page_count')}")
    print(f"OCR Text: {'available' if index['ocr_text_available'] else 'missing'}")
    print(f"Words: {stats['word_count']}")
    print("Files:")
    print(f"  source images: {inventory['source_image_count']}")
    print(f"  pdf: {'yes' if inventory['pdf_exists'] else 'no'}")
    print(f"  ocr_pdf: {'yes' if inventory['ocr_pdf_exists'] else 'no'}")
    print(f"  text: {'yes' if inventory['text_exists'] else 'no'}")
    print(f"  scan_log: {'yes' if inventory['scan_log_exists'] else 'no'}")
    print("\nWrote:")
    print(f"  {index_path.relative_to(Path(index['packet_dir']))}")
    print("\nNext:")
    print("  laia librarian route --last")
    print("")


def command_index(args) -> None:
    if not getattr(args, "last", False):
        raise SystemExit("Only --last is supported for v0: laia librarian index --last")
    packet_json = find_latest_packet()
    index = build_index(packet_json)
    index_path = write_index(packet_json, index)
    print_summary(index, index_path)
