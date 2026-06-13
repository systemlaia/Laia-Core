import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


STANDARD_REQUIRED_ITEMS = (
    "originals",
    "metadata",
    "logs",
    "checksums.sha256",
    "packet_manifest.json",
    "ingest_report.md",
)

DEFAULT_REVIEW_SIDECAR = {
    "review_status": "new",
    "rating_pass": None,
    "notes": "",
    "reviewed_at": None,
    "updated_at": None,
}


@dataclass(frozen=True)
class ChecksumEntry:
    sha256: str
    relative_path: str
    line_number: int


@dataclass(frozen=True)
class PacketValidation:
    packet: Path
    required_items: Sequence[str]
    present: Sequence[str]
    missing: Sequence[str]

    @property
    def ok(self) -> bool:
        return not self.missing


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def packet_path(root: Path, year: str, packet_id: str) -> Path:
    return Path(root).expanduser() / str(year) / packet_id


def packet_manifest_path(packet: Path) -> Path:
    return Path(packet) / "packet_manifest.json"


def checksum_path(packet: Path) -> Path:
    return Path(packet) / "checksums.sha256"


def review_dir_path(packet: Path) -> Path:
    return Path(packet) / "review"


def review_sidecar_path(packet: Path) -> Path:
    return review_dir_path(packet) / "packet_review.json"


def selects_path(packet: Path) -> Path:
    return review_dir_path(packet) / "selects.txt"


def read_packet_manifest(packet: Path) -> Dict[str, Any]:
    path = packet_manifest_path(packet)
    if not path.exists():
        raise FileNotFoundError(f"Packet manifest not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Packet manifest must be a JSON object: {path}")
    return data


def write_packet_manifest(packet: Path, manifest: Dict[str, Any]) -> Path:
    if not isinstance(manifest, dict):
        raise TypeError("Packet manifest must be a dictionary")
    path = packet_manifest_path(packet)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def parse_checksum_file(path: Path) -> List[ChecksumEntry]:
    entries = []
    for line_number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        parts = text.split(maxsplit=1)
        if len(parts) != 2:
            raise ValueError(f"Malformed checksum line {line_number}: {line}")
        sha256, rel = parts
        rel = rel.strip()
        if rel.startswith("*"):
            rel = rel[1:]
        entries.append(ChecksumEntry(sha256=sha256, relative_path=rel, line_number=line_number))
    return entries


def count_checksum_entries(path: Path) -> int:
    return len(parse_checksum_file(path))


def validate_required_items(
    packet: Path,
    required_items: Optional[Iterable[str]] = None,
) -> PacketValidation:
    packet = Path(packet)
    items = tuple(required_items or STANDARD_REQUIRED_ITEMS)
    present = []
    missing = []
    for item in items:
        if (packet / item).exists():
            present.append(item)
        else:
            missing.append(item)
    return PacketValidation(packet=packet, required_items=items, present=tuple(present), missing=tuple(missing))


def read_review_sidecar(packet: Path, create: bool = False) -> Dict[str, Any]:
    path = review_sidecar_path(packet)
    if not path.exists():
        if not create:
            return dict(DEFAULT_REVIEW_SIDECAR)
        return write_review_sidecar(packet, DEFAULT_REVIEW_SIDECAR.copy())

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Review sidecar must be a JSON object: {path}")
    merged = dict(DEFAULT_REVIEW_SIDECAR)
    merged.update(data)
    return merged


def write_review_sidecar(packet: Path, review: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(review, dict):
        raise TypeError("Review sidecar must be a dictionary")
    data = dict(DEFAULT_REVIEW_SIDECAR)
    data.update(review)
    if data.get("updated_at") is None:
        data["updated_at"] = utc_now()
    path = review_sidecar_path(packet)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    selects = selects_path(packet)
    if not selects.exists():
        selects.write_text("", encoding="utf-8")
    return data


def latest_packet(root: Path, depth: int = 2) -> Path:
    root = Path(root).expanduser()
    if depth < 1:
        raise ValueError("depth must be at least 1")

    pattern = "/".join(["*"] * depth)
    packets = sorted(p for p in root.glob(pattern) if p.is_dir())
    if not packets:
        raise FileNotFoundError(f"No packets found under: {root}")
    return packets[-1]

