#!/usr/bin/env python3
from pathlib import Path
import csv, json, hashlib, argparse, os, datetime

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dng", ".raf", ".xmp"}

def sha256_file(path, block_size=1024 * 1024):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("--out", default="archive/manifests")
    p.add_argument("--hash", action="store_true")
    args = p.parse_args()

    root = Path(args.root).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rows = []

    for path in root.rglob("*"):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in IMAGE_EXTS:
            continue

        stat = path.stat()
        row = {
            "path": str(path),
            "relative_path": str(path.relative_to(root)),
            "filename": path.name,
            "extension": ext,
            "size_bytes": stat.st_size,
            "modified_time": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "sha256": sha256_file(path) if args.hash else "",
        }
        rows.append(row)

    csv_path = out / f"manifest_{stamp}.csv"
    json_path = out / f"manifest_{stamp}.json"
    md_path = out / f"manifest_{stamp}.md"

    fields = ["path", "relative_path", "filename", "extension", "size_bytes", "modified_time", "sha256"]

    with csv_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    with json_path.open("w") as f:
        json.dump(rows, f, indent=2)

    counts = {}
    total_bytes = 0
    for r in rows:
        counts[r["extension"]] = counts.get(r["extension"], 0) + 1
        total_bytes += int(r["size_bytes"])

    with md_path.open("w") as f:
        f.write("# LAIA Manifest Report\n\n")
        f.write(f"- Root: `{root}`\n")
        f.write(f"- Generated: `{stamp}`\n")
        f.write(f"- Files indexed: `{len(rows)}`\n")
        f.write(f"- Total bytes: `{total_bytes}`\n\n")
        f.write("## File Types\n\n")
        for ext, count in sorted(counts.items()):
            f.write(f"- `{ext}`: {count}\n")
        f.write("\n## Artifact Files\n\n")
        f.write(f"- CSV: `{csv_path}`\n")
        f.write(f"- JSON: `{json_path}`\n")

    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print(f"Files indexed: {len(rows)}")

if __name__ == "__main__":
    main()
