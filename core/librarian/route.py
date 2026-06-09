import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.index import find_latest_packet, load_packet
except ModuleNotFoundError:
    from core.librarian.index import find_latest_packet, load_packet


DEFAULT_ARCHIVE_ROOT = Path.home() / "LAIA" / "Archive" / "Ingest"


def slugify(value: Optional[str]) -> str:
    text = (value or "inbox").strip().lower()
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


def require_index(packet_dir: Path) -> Path:
    index_path = packet_dir / "index" / "index.json"
    if not index_path.exists():
        raise SystemExit(f"Packet must be indexed before routing: missing {index_path}")
    return index_path


def packet_year_month(packet_dir: Path) -> tuple[str, str]:
    name = packet_dir.name
    if len(name) >= 7 and name[4] == "-" and name[7] == "-":
        return name[0:4], name[5:7]
    now = datetime.now().astimezone()
    return now.strftime("%Y"), now.strftime("%m")


def destination_for_packet(
    packet_json: Path,
    packet: dict[str, Any],
    archive_root: Path = DEFAULT_ARCHIVE_ROOT,
) -> Path:
    packet_dir = packet_json.parent
    year, month = packet_year_month(packet_dir)
    project_slug = slugify(str(packet.get("project") or "inbox"))
    packet_type = str(packet.get("packet_type"))

    if packet_type == "laia.ingest.scan":
        media_dir = "Scans"
    else:
        media_dir = "Packets"

    return archive_root / media_dir / project_slug / year / month / packet_dir.name


def route_metadata(
    packet_json: Path,
    packet: dict[str, Any],
    destination: Path,
    action: str = "copy",
    status: str = "complete",
) -> dict[str, Any]:
    return {
        "routed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_packet_dir": str(packet_json.parent),
        "destination_packet_dir": str(destination),
        "packet_type": packet.get("packet_type"),
        "project": packet.get("project"),
        "action": action,
        "status": status,
    }


def write_route(packet_dir: Path, metadata: dict[str, Any]) -> Path:
    route_dir = packet_dir / "route"
    route_dir.mkdir(parents=True, exist_ok=True)
    route_path = route_dir / "route.json"
    route_path.write_text(json.dumps(metadata, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return route_path


def copy_packet(packet_dir: Path, destination: Path) -> None:
    if destination.exists():
        raise SystemExit(f"Destination already exists; refusing to overwrite: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(packet_dir, destination)


def route_packet(packet_json: Path, archive_root: Path = DEFAULT_ARCHIVE_ROOT) -> tuple[dict[str, Any], Path]:
    packet = load_packet(packet_json)
    packet_dir = packet_json.parent
    require_index(packet_dir)
    destination = destination_for_packet(packet_json, packet, archive_root)
    metadata = route_metadata(packet_json, packet, destination)
    source_route_path = write_route(packet_dir, metadata)
    copy_packet(packet_dir, destination)
    write_route(destination, metadata)
    return metadata, source_route_path


def print_summary(metadata: dict[str, Any], route_path: Path) -> None:
    print("\nLAIA Librarian Route Complete\n")
    print(f"Packet: {metadata['source_packet_dir']}")
    print(f"Type: {metadata['packet_type']}")
    print(f"Project: {metadata.get('project')}")
    print(f"Action: {metadata['action']}")
    print(f"Destination: {metadata['destination_packet_dir']}")
    print("\nWrote:")
    print(f"  {route_path.relative_to(Path(metadata['source_packet_dir']))}")
    print("\nNext:")
    print("  laia librarian summarize --last")
    print("")


def command_route(args) -> None:
    if not getattr(args, "last", False):
        raise SystemExit("Only --last is supported for v0: laia librarian route --last")
    packet_json = find_latest_packet()
    metadata, route_path = route_packet(packet_json)
    print_summary(metadata, route_path)
