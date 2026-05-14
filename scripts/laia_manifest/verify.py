#!/usr/bin/env python3
from pathlib import Path
import argparse, csv, json, datetime
from collections import Counter

def main():
    p = argparse.ArgumentParser()
    p.add_argument("manifest_csv")
    p.add_argument("--out", default="archive/reports")
    p.add_argument("--limit", type=int, default=0, help="Optional max rows to verify for testing")
    args = p.parse_args()

    manifest = Path(args.manifest_csv).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    rows = []
    with manifest.open(newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if args.limit and i >= args.limit:
                break
            rows.append(row)

    results = []
    counts = Counter()

    for row in rows:
        path = Path(row["path"])
        expected_size = int(row.get("size_bytes") or 0)
        expected_mtime = row.get("modified_time", "")

        result = {
            "path": str(path),
            "relative_path": row.get("relative_path", ""),
            "exists": path.exists(),
            "expected_size_bytes": expected_size,
            "actual_size_bytes": None,
            "size_matches": None,
            "expected_modified_time": expected_mtime,
            "actual_modified_time": None,
            "mtime_matches": None,
            "status": "unknown",
        }

        if not path.exists():
            result["status"] = "missing"
            counts["missing"] += 1
        elif not path.is_file():
            result["status"] = "not_file"
            counts["not_file"] += 1
        else:
            stat = path.stat()
            actual_size = stat.st_size
            actual_mtime = datetime.datetime.fromtimestamp(stat.st_mtime).isoformat()

            result["actual_size_bytes"] = actual_size
            result["actual_modified_time"] = actual_mtime
            result["size_matches"] = actual_size == expected_size
            result["mtime_matches"] = actual_mtime == expected_mtime

            if result["size_matches"] and result["mtime_matches"]:
                result["status"] = "ok"
                counts["ok"] += 1
            elif not result["size_matches"]:
                result["status"] = "size_changed"
                counts["size_changed"] += 1
            elif not result["mtime_matches"]:
                result["status"] = "mtime_changed"
                counts["mtime_changed"] += 1

        results.append(result)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out / f"manifest_verify_{stamp}.json"
    md_path = out / f"manifest_verify_{stamp}.md"

    with json_path.open("w") as f:
        json.dump({
            "source_manifest": str(manifest),
            "generated": stamp,
            "rows_verified": len(rows),
            "counts": dict(counts),
            "results": results,
        }, f, indent=2)

    with md_path.open("w") as f:
        f.write("# LAIA Manifest Verification Report\n\n")
        f.write("## Source\n\n")
        f.write(f"- Manifest: `{manifest}`\n")
        f.write(f"- Generated: `{stamp}`\n")
        f.write(f"- Rows verified: `{len(rows)}`\n\n")

        f.write("## Status Counts\n\n")
        for key in ["ok", "missing", "size_changed", "mtime_changed", "not_file"]:
            f.write(f"- `{key}`: {counts.get(key, 0)}\n")

        problems = [r for r in results if r["status"] != "ok"]

        f.write("\n## Problems\n\n")
        if not problems:
            f.write("- No problems detected.\n")
        else:
            for r in problems[:100]:
                f.write(f"- `{r['status']}` — `{r['relative_path']}`\n")
            if len(problems) > 100:
                f.write(f"\n_Only first 100 problems shown. Total problems: {len(problems)}_\n")

        f.write("\n## Archivist Notes\n\n")
        f.write("- This verification is read-only.\n")
        f.write("- No archive files were modified.\n")
        f.write("- This compares manifest evidence against current filesystem state.\n")

    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print(f"Rows verified: {len(rows)}")
    print("Counts:", dict(counts))

if __name__ == "__main__":
    main()
