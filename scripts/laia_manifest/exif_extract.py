#!/usr/bin/env python3
from pathlib import Path
import argparse, csv, json, sqlite3, subprocess, datetime

DEFAULT_FIELDS = [
    "FileName",
    "Directory",
    "FileType",
    "MIMEType",
    "FileSize",
    "CreateDate",
    "DateTimeOriginal",
    "ModifyDate",
    "Make",
    "Model",
    "LensModel",
    "FNumber",
    "ExposureTime",
    "ISO",
    "FocalLength",
    "ImageWidth",
    "ImageHeight",
    "FilmMode",
    "WhiteBalance",
]

def run_exiftool(paths, fields):
    cmd = ["exiftool", "-json"]
    for field in fields:
        cmd.append(f"-{field}")
    cmd.extend(str(p) for p in paths)

    result = subprocess.run(cmd, text=True, capture_output=True)
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)

    return json.loads(result.stdout or "[]")

def init_db(conn):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS photo_metadata (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_manifest TEXT,
        file_path TEXT UNIQUE,
        relative_path TEXT,
        extension TEXT,
        size_bytes INTEGER,
        modified_time TEXT,
        exif_json TEXT,
        extracted_at TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS extraction_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_manifest TEXT,
        generated TEXT,
        files_seen INTEGER,
        files_attempted INTEGER,
        files_extracted INTEGER,
        db_path TEXT
    )
    """)
    conn.commit()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("manifest_csv")
    p.add_argument("--db", default="archive/catalog/photo_metadata.sqlite")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--batch-size", type=int, default=25)
    p.add_argument("--extensions", default=".jpg,.jpeg,.raf,.dng,.tif,.tiff,.png")
    args = p.parse_args()

    manifest = Path(args.manifest_csv).expanduser().resolve()
    db_path = Path(args.db).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    allowed_exts = {e.strip().lower() for e in args.extensions.split(",") if e.strip()}
    rows = []

    with manifest.open(newline="") as f:
        for row in csv.DictReader(f):
            if row.get("extension", "").lower() not in allowed_exts:
                continue
            rows.append(row)

    if args.limit and args.limit > 0:
        rows = rows[:args.limit]

    conn = sqlite3.connect(db_path)
    init_db(conn)

    extracted = 0
    generated = datetime.datetime.now().isoformat()

    for start in range(0, len(rows), args.batch_size):
        batch = rows[start:start + args.batch_size]
        paths = [Path(r["path"]) for r in batch if Path(r["path"]).exists()]

        if not paths:
            continue

        metadata = run_exiftool(paths, DEFAULT_FIELDS)
        by_source = {m.get("SourceFile"): m for m in metadata}

        for row in batch:
            path = row["path"]
            exif = by_source.get(path)
            if not exif:
                continue

            conn.execute("""
            INSERT INTO photo_metadata (
                source_manifest,
                file_path,
                relative_path,
                extension,
                size_bytes,
                modified_time,
                exif_json,
                extracted_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                source_manifest=excluded.source_manifest,
                relative_path=excluded.relative_path,
                extension=excluded.extension,
                size_bytes=excluded.size_bytes,
                modified_time=excluded.modified_time,
                exif_json=excluded.exif_json,
                extracted_at=excluded.extracted_at
            """, (
                str(manifest),
                path,
                row.get("relative_path", ""),
                row.get("extension", ""),
                int(row.get("size_bytes") or 0),
                row.get("modified_time", ""),
                json.dumps(exif, ensure_ascii=False),
                generated,
            ))
            extracted += 1

        conn.commit()

    conn.execute("""
    INSERT INTO extraction_runs (
        source_manifest,
        generated,
        files_seen,
        files_attempted,
        files_extracted,
        db_path
    )
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(manifest),
        generated,
        len(rows),
        len(rows),
        extracted,
        str(db_path),
    ))
    conn.commit()

    print(f"DB: {db_path}")
    print(f"Manifest: {manifest}")
    print(f"Files attempted: {len(rows)}")
    print(f"Files extracted: {extracted}")

if __name__ == "__main__":
    main()
