#!/usr/bin/env python3
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("/Volumes/Public/LAIA/packets/photo_ingest")

DEFAULT_REVIEW = {
    "review_status": "new",
    "rating_pass": None,
    "notes": "",
    "reviewed_at": None,
    "updated_at": None
}

VALID_STATUSES = {"new", "reviewed", "selected", "rejected", "exported", "published"}


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_packet():
    packets = sorted(p for p in ROOT.glob("*/*") if p.is_dir())
    if not packets:
        raise SystemExit("No photo ingest packets found.")
    return packets[-1]


def resolve_packet(arg: str | None):
    if arg in (None, "", "--last"):
        return latest_packet()
    p = Path(arg)
    if not p.is_dir():
        raise SystemExit(f"Packet folder not found: {p}")
    return p


def review_paths(packet: Path):
    review_dir = packet / "review"
    review_json = review_dir / "packet_review.json"
    selects_txt = review_dir / "selects.txt"
    return review_dir, review_json, selects_txt


def ensure_review(packet: Path):
    review_dir, review_json, selects_txt = review_paths(packet)
    review_dir.mkdir(parents=True, exist_ok=True)

    if review_json.exists():
        try:
            data = json.loads(review_json.read_text(errors="replace"))
        except Exception:
            data = DEFAULT_REVIEW.copy()
    else:
        data = DEFAULT_REVIEW.copy()

    for key, value in DEFAULT_REVIEW.items():
        data.setdefault(key, value)

    if data["updated_at"] is None:
        data["updated_at"] = utc_now()

    review_json.write_text(json.dumps(data, indent=2) + "\n")

    if not selects_txt.exists():
        selects_txt.write_text("")

    return data, review_json, selects_txt


def show_status(packet: Path):
    data, review_json, selects_txt = ensure_review(packet)

    print("LAIA Photo Packet Review")
    print()
    print(f"Packet:       {packet}")
    print(f"Review file:  {review_json}")
    print(f"Selects file: {selects_txt}")
    print()
    print(f"Status:       {data.get('review_status', '')}")
    print(f"Rating pass:  {data.get('rating_pass', '')}")
    print(f"Reviewed at:  {data.get('reviewed_at', '')}")
    print(f"Updated at:   {data.get('updated_at', '')}")
    print(f"Notes:        {data.get('notes', '')}")


def set_status(packet: Path, status: str):
    if status not in VALID_STATUSES:
        raise SystemExit(f"Invalid status: {status}\nValid: {', '.join(sorted(VALID_STATUSES))}")

    data, review_json, _ = ensure_review(packet)
    data["review_status"] = status
    data["updated_at"] = utc_now()

    if status != "new":
        data["reviewed_at"] = utc_now()
    else:
        data["reviewed_at"] = None

    review_json.write_text(json.dumps(data, indent=2) + "\n")

    print(f"Updated review status: {status}")
    print(f"Packet: {packet}")


def set_notes(packet: Path, notes: str):
    data, review_json, _ = ensure_review(packet)
    data["notes"] = notes
    data["updated_at"] = utc_now()
    review_json.write_text(json.dumps(data, indent=2) + "\n")

    print("Updated review notes.")
    print(f"Packet: {packet}")


def help_text():
    print("LAIA Photo Review Tool")
    print()
    print("Usage:")
    print("  laia_photo_review_packet.py status [packet|--last]")
    print("  laia_photo_review_packet.py set-status <status> [packet|--last]")
    print("  laia_photo_review_packet.py set-notes <notes> [packet|--last]")


def main():
    if len(sys.argv) < 2:
        help_text()
        return

    cmd = sys.argv[1]

    if cmd == "status":
        packet = resolve_packet(sys.argv[2] if len(sys.argv) > 2 else "--last")
        show_status(packet)

    elif cmd == "set-status":
        if len(sys.argv) < 3:
            raise SystemExit("Usage: laia_photo_review_packet.py set-status <status> [packet|--last]")
        status = sys.argv[2]
        packet = resolve_packet(sys.argv[3] if len(sys.argv) > 3 else "--last")
        set_status(packet, status)

    elif cmd == "set-notes":
        if len(sys.argv) < 3:
            raise SystemExit('Usage: laia_photo_review_packet.py set-notes "notes here" [packet|--last]')
        notes = sys.argv[2]
        packet = resolve_packet(sys.argv[3] if len(sys.argv) > 3 else "--last")
        set_notes(packet, notes)

    else:
        help_text()


if __name__ == "__main__":
    main()
