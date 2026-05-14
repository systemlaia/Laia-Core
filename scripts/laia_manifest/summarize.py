#!/usr/bin/env python3
from pathlib import Path
import argparse, csv, json, datetime
from collections import Counter, defaultdict

def human_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    size = float(n)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024

def main():
    p = argparse.ArgumentParser()
    p.add_argument("manifest_csv")
    p.add_argument("--out", default="archive/reports")
    args = p.parse_args()

    manifest = Path(args.manifest_csv).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    with manifest.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            row["size_bytes"] = int(row.get("size_bytes") or 0)
            rows.append(row)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    ext_counts = Counter(r["extension"] for r in rows)
    ext_bytes = defaultdict(int)
    top_dirs = Counter()
    total_bytes = 0

    for r in rows:
        total_bytes += r["size_bytes"]
        ext_bytes[r["extension"]] += r["size_bytes"]
        parts = Path(r["relative_path"]).parts
        top = parts[0] if parts else "."
        top_dirs[top] += 1

    summary = {
        "source_manifest": str(manifest),
        "generated": stamp,
        "total_files": len(rows),
        "total_bytes": total_bytes,
        "total_size_human": human_bytes(total_bytes),
        "extensions": {
            ext: {
                "count": ext_counts[ext],
                "bytes": ext_bytes[ext],
                "size_human": human_bytes(ext_bytes[ext]),
            }
            for ext in sorted(ext_counts)
        },
        "top_level_directories": dict(top_dirs.most_common(25)),
        "sample_files": rows[:10],
    }

    json_path = out / f"manifest_summary_{stamp}.json"
    md_path = out / f"manifest_summary_{stamp}.md"

    with json_path.open("w") as f:
        json.dump(summary, f, indent=2)

    with md_path.open("w") as f:
        f.write("# LAIA Manifest Summary\n\n")
        f.write("## Source\n\n")
        f.write(f"- Manifest: `{manifest}`\n")
        f.write(f"- Generated: `{stamp}`\n\n")

        f.write("## Verified Totals\n\n")
        f.write(f"- Total files: `{len(rows)}`\n")
        f.write(f"- Total size: `{human_bytes(total_bytes)}`\n")
        f.write(f"- Total bytes: `{total_bytes}`\n\n")

        f.write("## Verified File Types\n\n")
        f.write("| Extension | Count | Size |\n")
        f.write("|---|---:|---:|\n")
        for ext in sorted(ext_counts):
            f.write(f"| `{ext}` | {ext_counts[ext]} | {human_bytes(ext_bytes[ext])} |\n")

        f.write("\n## Top-Level Directory Counts\n\n")
        f.write("| Directory | Files |\n")
        f.write("|---|---:|\n")
        for name, count in top_dirs.most_common(25):
            f.write(f"| `{name}` | {count} |\n")

        f.write("\n## Sample Files\n\n")
        for r in rows[:10]:
            f.write(f"- `{r['relative_path']}` — `{r['extension']}`, {human_bytes(r['size_bytes'])}\n")

        f.write("\n## Archivist Notes\n\n")
        f.write("- This report is derived from a CSV manifest artifact.\n")
        f.write("- No archive files were modified.\n")
        f.write("- Aggregate claims in this report are artifact-backed.\n")

    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print(f"Files summarized: {len(rows)}")

if __name__ == "__main__":
    main()
