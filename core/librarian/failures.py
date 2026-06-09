import json
from datetime import datetime
from pathlib import Path
from typing import Optional


DEFAULT_SCAN_ROOT = Path.home() / "LAIA" / "Inbox" / "Ingest" / "Scans"


def infer_failure_status(log_text: str, error: Optional[str] = None) -> str:
    text = f"{log_text}\n{error or ''}".lower()
    if "document feeder jammed" in text or "jammed" in text:
        return "Document feeder jammed"
    if "0 pages" in text or "no pages" in text:
        return "0 pages scanned"
    if "scanimage failed" in text or "error" in text:
        return "scanimage failed"
    return "scan failed"


def failure_metadata(packet_dir: Path, stage: str, error: str, status_text: str) -> dict[str, str]:
    return {
        "failure_type": "laia.librarian.failure",
        "failed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "stage": stage,
        "error": error,
        "packet_dir": str(packet_dir),
        "status": "failed",
        "failure_status": status_text,
        "recommended_action": "clear issue and rescan",
    }


def markdown_failure(metadata: dict[str, str]) -> str:
    return (
        "# LAIA Ingest Failure\n\n"
        f"- Packet: {metadata.get('packet_dir')}\n"
        f"- Stage: {metadata.get('stage')}\n"
        f"- Status: {metadata.get('status')}\n"
        f"- Failure: {metadata.get('failure_status')}\n"
        f"- Error: {metadata.get('error')}\n"
        f"- Failed At: {metadata.get('failed_at')}\n"
        f"- Recommended Action: {metadata.get('recommended_action')}\n"
    )


def write_failure(packet_dir: Path, stage: str, error: str, status_text: Optional[str] = None) -> tuple[Path, Path]:
    log_path = packet_dir / "logs" / "scanimage.log"
    log_text = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else ""
    metadata = failure_metadata(
        packet_dir=packet_dir,
        stage=stage,
        error=error,
        status_text=status_text or infer_failure_status(log_text, error),
    )
    failure_dir = packet_dir / "failure"
    failure_dir.mkdir(parents=True, exist_ok=True)
    failure_json = failure_dir / "failure.json"
    failure_md = failure_dir / "failure.md"
    failure_json.write_text(json.dumps(metadata, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    failure_md.write_text(markdown_failure(metadata), encoding="utf-8")
    return failure_json, failure_md


def log_only_scan_dirs(scan_root: Path = DEFAULT_SCAN_ROOT) -> list[Path]:
    if not scan_root.exists():
        return []
    packet_dirs = []
    for log_path in scan_root.glob("*/logs/scanimage.log"):
        packet_dir = log_path.parents[1]
        if (packet_dir / "packet.json").exists():
            continue
        packet_dirs.append(packet_dir)
    return sorted(packet_dirs, key=lambda path: path.stat().st_mtime)


def mark_failure_dirs(scan_root: Path = DEFAULT_SCAN_ROOT) -> list[Path]:
    written = []
    for packet_dir in log_only_scan_dirs(scan_root):
        log_path = packet_dir / "logs" / "scanimage.log"
        log_text = log_path.read_text(encoding="utf-8", errors="replace")
        status_text = infer_failure_status(log_text)
        failure_json, _failure_md = write_failure(
            packet_dir,
            stage="ingest scan",
            error=status_text,
            status_text=status_text,
        )
        written.append(failure_json)
    return written


def command_mark_failures(_args) -> None:
    written = mark_failure_dirs()
    print("\nLAIA Librarian Failure Marking Complete\n")
    print(f"Failures marked: {len(written)}")
    for path in written:
        print(f"  {path.parent.parent}")
    print("")
