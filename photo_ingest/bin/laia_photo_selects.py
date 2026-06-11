#!/usr/bin/env python3
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("/Volumes/Public/LAIA/packets/photo_ingest")


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def latest_packet():
    packets = sorted(p for p in ROOT.glob("*/*") if p.is_dir())
    if not packets:
        raise SystemExit("No photo ingest packets found.")
    return packets[-1]


def packet_paths(packet):
    review_dir = packet / "review"
    selects = review_dir / "selects.txt"
    review_dir.mkdir(parents=True, exist_ok=True)
    if not selects.exists():
        selects.write_text("")
    return review_dir, selects


def find_original(packet, query):
    originals = packet / "originals"
    if not originals.exists():
        raise SystemExit(f"Missing originals folder: {originals}")

    matches = []
    q = query.lower()

    for f in originals.rglob("*"):
        if not f.is_file():
            continue
        rel = str(f.relative_to(originals))
        if f.name.lower() == q or rel.lower() == q or q in rel.lower():
            matches.append((rel, f))

    if not matches:
        raise SystemExit(f"No original matched: {query}")

    exact = [m for m in matches if m[0].lower() == q or Path(m[0]).name.lower() == q]
    if len(exact) == 1:
        return exact[0]

    if len(matches) == 1:
        return matches[0]

    print(f"Multiple matches for: {query}")
    for rel, _ in matches[:25]:
        print(f"  {rel}")
    if len(matches) > 25:
        print(f"  ...and {len(matches) - 25} more")
    raise SystemExit("Use a more specific relative path.")


def read_selects(selects_path):
    rows = []
    for line in selects_path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(line)
    return rows


def write_selects(selects_path, rows):
    clean = []
    seen = set()
    for row in rows:
        row = row.strip()
        if row and row not in seen:
            clean.append(row)
            seen.add(row)

    header = [
        "# LAIA photo selects",
        f"# updated_at: {utc_now()}",
        "# paths are relative to packet/originals",
        "",
    ]

    selects_path.write_text("\n".join(header + clean) + "\n")


def add_select(packet, query):
    _, selects_path = packet_paths(packet)
    rel, _ = find_original(packet, query)

    rows = read_selects(selects_path)
    if rel not in rows:
        rows.append(rel)
        write_selects(selects_path, rows)
        print(f"Added select: {rel}")
    else:
        print(f"Already selected: {rel}")

    print(f"Selects file: {selects_path}")


def remove_select(packet, query):
    _, selects_path = packet_paths(packet)
    rows = read_selects(selects_path)

    q = query.lower()
    keep = []
    removed = []

    for row in rows:
        if row.lower() == q or Path(row).name.lower() == q or q in row.lower():
            removed.append(row)
        else:
            keep.append(row)

    if not removed:
        print(f"No select matched: {query}")
        return

    write_selects(selects_path, keep)

    for row in removed:
        print(f"Removed select: {row}")


def list_selects(packet):
    _, selects_path = packet_paths(packet)
    rows = read_selects(selects_path)

    print("LAIA Photo Selects")
    print()
    print(f"Packet: {packet}")
    print(f"Selects file: {selects_path}")
    print(f"Count: {len(rows)}")
    print()

    if not rows:
        print("No selects yet.")
        return

    for i, row in enumerate(rows, 1):
        print(f"{i:03d}. {row}")


def clear_selects(packet):
    _, selects_path = packet_paths(packet)
    write_selects(selects_path, [])
    print(f"Cleared selects: {selects_path}")


def export_selects(packet, dest):
    _, selects_path = packet_paths(packet)
    rows = read_selects(selects_path)

    if not rows:
        raise SystemExit("No selects to export.")

    dest = Path(dest).expanduser()
    dest.mkdir(parents=True, exist_ok=True)

    originals = packet / "originals"
    copied = 0
    missing = []

    for rel in rows:
        src = originals / rel
        if not src.exists():
            missing.append(rel)
            continue

        out = dest / Path(rel).name
        if out.exists():
            stem = out.stem
            suffix = out.suffix
            out = dest / f"{stem}_{copied+1:03d}{suffix}"

        shutil.copy2(src, out)
        copied += 1
        print(f"Copied: {rel} -> {out}")

    print()
    print(f"Export folder: {dest}")
    print(f"Copied: {copied}")

    if missing:
        print("Missing:")
        for rel in missing:
            print(f"  {rel}")


def help_text():
    print("LAIA Photo Selects")
    print()
    print("Usage:")
    print("  laia_photo_selects.py add <filename-or-relative-path>")
    print("  laia_photo_selects.py remove <filename-or-relative-path>")
    print("  laia_photo_selects.py list")
    print("  laia_photo_selects.py clear")
    print("  laia_photo_selects.py export <destination-folder>")


def main():
    packet = latest_packet()

    if len(sys.argv) < 2:
        help_text()
        return

    cmd = sys.argv[1]

    if cmd == "add":
        if len(sys.argv) < 3:
            raise SystemExit("Usage: laia_photo_selects.py add <filename>")
        add_select(packet, sys.argv[2])

    elif cmd == "remove":
        if len(sys.argv) < 3:
            raise SystemExit("Usage: laia_photo_selects.py remove <filename>")
        remove_select(packet, sys.argv[2])

    elif cmd == "list":
        list_selects(packet)

    elif cmd == "clear":
        clear_selects(packet)

    elif cmd == "export":
        if len(sys.argv) < 3:
            raise SystemExit("Usage: laia_photo_selects.py export <destination-folder>")
        export_selects(packet, sys.argv[2])

    else:
        help_text()


if __name__ == "__main__":
    main()
