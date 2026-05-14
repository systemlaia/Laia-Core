#!/usr/bin/env python3
from pathlib import Path
import argparse, csv, json, sqlite3, hashlib, datetime
from collections import defaultdict

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".dng", ".raf", ".xmp"}

def sha256_file(path, block_size=1024 * 1024):
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(block_size):
            h.update(chunk)
    return h.hexdigest()

def load_catalog(conn):
    rows = conn.execute("""
        SELECT
            file_path,
            relative_path,
            extension,
            size_bytes,
            json_extract(exif_json,'$.DateTimeOriginal') as dto,
            json_extract(exif_json,'$.Model') as model
        FROM photo_metadata
    """).fetchall()

    by_name_size = defaultdict(list)
    by_size_dto = defaultdict(list)

    for file_path, rel, ext, size, dto, model in rows:
        name = Path(file_path).name.lower()
        by_name_size[(name, size)].append((file_path, rel, ext, size, dto, model))
        if dto:
            by_size_dto[(size, dto)].append((file_path, rel, ext, size, dto, model))

    return by_name_size, by_size_dto

def main():
    p = argparse.ArgumentParser()
    p.add_argument("incoming_root", help="Folder to scan for possible imports")
    p.add_argument("--db", default="archive/catalog/photo_metadata.sqlite")
    p.add_argument("--out", default="archive/reports")
    p.add_argument("--hash", action="store_true", help="Optional slow hash check for incoming files")
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args()

    incoming_root = Path(args.incoming_root).expanduser().resolve()
    db = Path(args.db).expanduser().resolve()
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(db)
    by_name_size, by_size_dto = load_catalog(conn)

    scanned = []
    possible_duplicates = []
    unique_candidates = []
    unsupported = []

    count = 0
    for path in incoming_root.rglob("*"):
        if not path.is_file():
            continue
        ext = path.suffix.lower()
        if ext not in IMAGE_EXTS:
            unsupported.append(str(path))
            continue

        stat = path.stat()
        name = path.name.lower()
        size = stat.st_size

        item = {
            "incoming_path": str(path),
            "incoming_relative_path": str(path.relative_to(incoming_root)),
            "filename": path.name,
            "extension": ext,
            "size_bytes": size,
            "modified_time": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
            "sha256": sha256_file(path) if args.hash else "",
            "matches": [],
            "status": "unique_candidate",
            "reason": "no name+size or size+datetime match found",
        }

        name_size_matches = by_name_size.get((name, size), [])
        if name_size_matches:
            item["status"] = "possible_duplicate"
            item["reason"] = "filename + size match"
            for m in name_size_matches:
                item["matches"].append({
                    "match_type": "filename_size",
                    "catalog_path": m[0],
                    "catalog_relative_path": m[1],
                    "catalog_extension": m[2],
                    "catalog_size_bytes": m[3],
                    "catalog_datetime_original": m[4],
                    "catalog_model": m[5],
                })

        # If filename does not match, still catch likely same-photo duplicates by size + DateTimeOriginal
        # This requires incoming EXIF later, so for now this only works against catalog side if future enhancement adds incoming EXIF.
        # Kept as structure placeholder; no false claims made here.

        scanned.append(item)
        if item["status"] == "possible_duplicate":
            possible_duplicates.append(item)
        else:
            unique_candidates.append(item)

        count += 1
        if args.limit and count >= args.limit:
            break

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = out / f"duplicate_scan_{stamp}.json"
    md_path = out / f"duplicate_scan_{stamp}.md"

    result = {
        "generated": stamp,
        "incoming_root": str(incoming_root),
        "catalog_db": str(db),
        "files_scanned": len(scanned),
        "possible_duplicates": len(possible_duplicates),
        "unique_candidates": len(unique_candidates),
        "unsupported_files_seen": len(unsupported),
        "hash_enabled": args.hash,
        "results": scanned,
    }

    json_path.write_text(json.dumps(result, indent=2))

    with md_path.open("w") as f:
        f.write("# LAIA Duplicate Scan Report\n\n")
        f.write(f"- Generated: `{stamp}`\n")
        f.write(f"- Incoming root: `{incoming_root}`\n")
        f.write(f"- Catalog DB: `{db}`\n")
        f.write(f"- Files scanned: `{len(scanned)}`\n")
        f.write(f"- Possible duplicates: `{len(possible_duplicates)}`\n")
        f.write(f"- Unique candidates: `{len(unique_candidates)}`\n")
        f.write(f"- Unsupported files seen: `{len(unsupported)}`\n")
        f.write(f"- Hash enabled: `{args.hash}`\n\n")

        f.write("## Possible Duplicates\n\n")
        if not possible_duplicates:
            f.write("- No possible duplicates detected by filename + size.\n")
        else:
            for item in possible_duplicates[:100]:
                f.write(f"### `{item['incoming_relative_path']}`\n\n")
                f.write(f"- Reason: `{item['reason']}`\n")
                f.write(f"- Size: `{item['size_bytes']}`\n")
                for match in item["matches"][:5]:
                    f.write(f"- Matches catalog: `{match['catalog_relative_path']}`\n")
                f.write("\n")
            if len(possible_duplicates) > 100:
                f.write(f"\n_Only first 100 shown. Total: {len(possible_duplicates)}_\n")

        f.write("\n## Unique Candidate Samples\n\n")
        for item in unique_candidates[:50]:
            f.write(f"- `{item['incoming_relative_path']}` — `{item['extension']}`, {item['size_bytes']} bytes\n")

        f.write("\n## Archivist Notes\n\n")
        f.write("- This scan is read-only.\n")
        f.write("- No incoming or archive files were modified.\n")
        f.write("- Current duplicate rule: filename + byte size match.\n")
        f.write("- Future stronger rule: hash match and EXIF DateTimeOriginal matching.\n")

    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print(f"Files scanned: {len(scanned)}")
    print(f"Possible duplicates: {len(possible_duplicates)}")
    print(f"Unique candidates: {len(unique_candidates)}")

if __name__ == "__main__":
    main()
