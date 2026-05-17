#!/usr/bin/env python3
from pathlib import Path
import argparse, csv, json, datetime
from collections import Counter, defaultdict

EXCLUDE_DIRS = {"@Recycle", "@Recently-Snapshot", ".AppleDouble", ".TemporaryItems"}

def human_bytes(n):
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    for u in units:
        if size < 1024 or u == units[-1]:
            return f"{size:.2f} {u}"
        size /= 1024

def should_skip(path):
    return any(part in EXCLUDE_DIRS for part in path.parts)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("root")
    p.add_argument("--out", default="archive/nas_manifests")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    root = Path(args.root).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    rows = []
    ext_counts = Counter()
    ext_bytes = defaultdict(int)
    top_dirs = Counter()
    total_bytes = 0

    count = 0
    for path in root.rglob("*"):
        if should_skip(path):
            continue
        if not path.is_file():
            continue

        stat = path.stat()
        ext = path.suffix.lower() or "[no extension]"
        rel = path.relative_to(root)
        top = rel.parts[0] if rel.parts else "."

        row = {
            "path": str(path),
            "relative_path": str(rel),
            "filename": path.name,
            "extension": ext,
            "size_bytes": stat.st_size,
            "modified_time": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "top_level_dir": top,
        }

        rows.append(row)
        ext_counts[ext] += 1
        ext_bytes[ext] += stat.st_size
        top_dirs[top] += 1
        total_bytes += stat.st_size

        count += 1
        if args.limit and count >= args.limit:
            break

    csv_path = out / f"nas_manifest_{stamp}.csv"
    json_path = out / f"nas_manifest_{stamp}.json"
    md_path = out / f"nas_manifest_{stamp}.md"

    fields = ["path", "relative_path", "filename", "extension", "size_bytes", "modified_time", "top_level_dir"]

    with csv_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    with json_path.open("w") as f:
        json.dump(rows, f, indent=2)

    with md_path.open("w") as f:
        f.write("# LAIA NAS Manifest\n\n")
        f.write(f"- Root: `{root}`\n")
        f.write(f"- Generated: `{stamp}`\n")
        f.write(f"- Files indexed: `{len(rows)}`\n")
        f.write(f"- Total size: `{human_bytes(total_bytes)}`\n")
        f.write(f"- Total bytes: `{total_bytes}`\n")
        f.write(f"- Excluded dirs: `{', '.join(sorted(EXCLUDE_DIRS))}`\n\n")

        f.write("## Top File Types\n\n")
        f.write("| Extension | Count | Size |\n")
        f.write("|---|---:|---:|\n")
        for ext, c in ext_counts.most_common(50):
            f.write(f"| `{ext}` | {c} | {human_bytes(ext_bytes[ext])} |\n")

        f.write("\n## Top-Level Directories\n\n")
        f.write("| Directory | Files |\n")
        f.write("|---|---:|\n")
        for d, c in top_dirs.most_common(50):
            f.write(f"| `{d}` | {c} |\n")

        f.write("\n## Artifact Files\n\n")
        f.write(f"- CSV: `{csv_path}`\n")
        f.write(f"- JSON: `{json_path}`\n")

    latest_csv = out / "nas_manifest_latest.csv"
    latest_json = out / "nas_manifest_latest.json"
    latest_md = out / "nas_manifest_latest.md"

    latest_csv.write_text(csv_path.read_text())
    latest_json.write_text(json_path.read_text())
    latest_md.write_text(md_path.read_text())

    print(f"CSV:  {csv_path}")
    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print(f"Latest CSV:  {latest_csv}")
    print(f"Latest JSON: {latest_json}")
    print(f"Latest MD:   {latest_md}")
    print(f"Files indexed: {len(rows)}")
    print(f"Total size: {human_bytes(total_bytes)}")

if __name__ == "__main__":
    main()
