#!/usr/bin/env python3
import json
import sqlite3
from pathlib import Path

ROOT = Path("/Volumes/Public/LAIA/packets/photo_ingest")
DB_PATH = Path("/Volumes/Public/LAIA/catalogs/photo_ingest/photo_packets.db")

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

cur.executescript("""
CREATE TABLE IF NOT EXISTS packets (
    job_id TEXT PRIMARY KEY,
    packet_path TEXT,
    source TEXT,
    photo_count INTEGER,
    packet_size TEXT,
    created_at TEXT,
    ingest_report TEXT
);

CREATE TABLE IF NOT EXISTS images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    relative_path TEXT,
    filename TEXT,
    extension TEXT,
    file_size INTEGER,
    camera_make TEXT,
    camera_model TEXT,
    lens_model TEXT,
    date_time_original TEXT,
    iso TEXT,
    aperture TEXT,
    shutter_speed TEXT,
    focal_length TEXT,
    FOREIGN KEY(job_id) REFERENCES packets(job_id)
);

CREATE TABLE IF NOT EXISTS checksums (
    job_id TEXT,
    relative_path TEXT,
    sha256 TEXT,
    PRIMARY KEY(job_id, relative_path)
);

CREATE INDEX IF NOT EXISTS idx_images_job_id ON images(job_id);
CREATE INDEX IF NOT EXISTS idx_images_filename ON images(filename);
CREATE INDEX IF NOT EXISTS idx_images_camera_model ON images(camera_model);
CREATE INDEX IF NOT EXISTS idx_images_date_time_original ON images(date_time_original);
CREATE INDEX IF NOT EXISTS idx_checksums_sha256 ON checksums(sha256);
""")

# Backward-compatible schema upgrades
for sql in [
    "ALTER TABLE packets ADD COLUMN review_status TEXT;",
    "ALTER TABLE packets ADD COLUMN review_notes TEXT;",
    "ALTER TABLE packets ADD COLUMN reviewed_at TEXT;",
    "ALTER TABLE packets ADD COLUMN select_count INTEGER DEFAULT 0;",
]:
    try:
        cur.execute(sql)
    except sqlite3.OperationalError:
        pass

packet_dirs = sorted(p for p in ROOT.glob("*/*") if p.is_dir())

for packet in packet_dirs:
    manifest_path = packet / "packet_manifest.json"
    if not manifest_path.exists():
        continue

    manifest = json.loads(manifest_path.read_text(errors="replace"))

    job_id = manifest.get("job_id", packet.name)
    report_path = packet / "ingest_report.md"
    ingest_report = report_path.read_text(errors="replace") if report_path.exists() else ""

    review_path = packet / "review" / "packet_review.json"
    review_status = "new"
    review_notes = ""
    reviewed_at = None

    if review_path.exists():
        try:
            review = json.loads(review_path.read_text(errors="replace"))
            review_status = review.get("review_status", "new")
            review_notes = review.get("notes", "")
            reviewed_at = review.get("reviewed_at", None)
        except Exception:
            pass

    selects_path = packet / "review" / "selects.txt"
    select_count = 0
    if selects_path.exists():
        select_count = sum(
            1
            for line in selects_path.read_text(errors="replace").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )

    cur.execute("""
        INSERT OR REPLACE INTO packets
        (
            job_id, packet_path, source, photo_count, packet_size,
            created_at, ingest_report, review_status, review_notes, reviewed_at, select_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        job_id,
        manifest.get("packet_path", str(packet)),
        manifest.get("source", ""),
        int(manifest.get("photo_count", 0)),
        manifest.get("packet_size", ""),
        manifest.get("created_at", ""),
        ingest_report,
        review_status,
        review_notes,
        reviewed_at,
        select_count,
    ))

    cur.execute("DELETE FROM images WHERE job_id = ?", (job_id,))
    cur.execute("DELETE FROM checksums WHERE job_id = ?", (job_id,))

    checksum_path = packet / "checksums.sha256"
    if checksum_path.exists():
        for line in checksum_path.read_text(errors="replace").splitlines():
            if not line.strip():
                continue
            parts = line.split(maxsplit=1)
            if len(parts) == 2:
                sha256, rel = parts
                rel = rel.strip()
                cur.execute("""
                    INSERT OR REPLACE INTO checksums
                    (job_id, relative_path, sha256)
                    VALUES (?, ?, ?)
                """, (job_id, rel, sha256))

    exif_json = packet / "metadata" / "exiftool.json"
    exif_by_rel = {}

    if exif_json.exists():
        try:
            exif_data = json.loads(exif_json.read_text(errors="replace"))
            for item in exif_data:
                source_file = item.get("SourceFile", "")
                rel = source_file.split("/originals/", 1)[-1]
                rel = rel.lstrip("./")
                exif_by_rel[rel] = item
        except Exception as e:
            print(f"Warning: failed to parse EXIF for {packet}: {e}")

    originals = packet / "originals"
    if originals.exists():
        for file in sorted(p for p in originals.rglob("*") if p.is_file()):
            rel = str(file.relative_to(originals))
            exif = exif_by_rel.get(rel, {})

            cur.execute("""
                INSERT INTO images
                (
                    job_id, relative_path, filename, extension, file_size,
                    camera_make, camera_model, lens_model, date_time_original,
                    iso, aperture, shutter_speed, focal_length
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job_id,
                "./" + rel,
                file.name,
                file.suffix.lower().lstrip("."),
                file.stat().st_size,
                str(exif.get("Make", "")),
                str(exif.get("Model", "")),
                str(exif.get("LensModel", "")),
                str(exif.get("DateTimeOriginal", "")),
                str(exif.get("ISO", "")),
                str(exif.get("Aperture", "")),
                str(exif.get("ShutterSpeed", "")),
                str(exif.get("FocalLength", "")),
            ))

conn.commit()

packet_count = cur.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
image_count = cur.execute("SELECT COUNT(*) FROM images").fetchone()[0]
camera_rows = cur.execute("""
    SELECT camera_make, camera_model, COUNT(*)
    FROM images
    GROUP BY camera_make, camera_model
    ORDER BY COUNT(*) DESC
""").fetchall()

review_rows = cur.execute("""
    SELECT COALESCE(review_status, 'new'), COUNT(*)
    FROM packets
    GROUP BY COALESCE(review_status, 'new')
    ORDER BY COUNT(*) DESC
""").fetchall()

conn.close()

print(f"Catalog written: {DB_PATH}")
print(f"Packets: {packet_count}")
print(f"Images: {image_count}")

if camera_rows:
    print("Cameras:")
    for make, model, count in camera_rows:
        label = " ".join(x for x in [make, model] if x).strip() or "Unknown camera"
        print(f"  {label}: {count}")

if review_rows:
    print("Review status:")
    for status, count in review_rows:
        print(f"  {status}: {count}")
