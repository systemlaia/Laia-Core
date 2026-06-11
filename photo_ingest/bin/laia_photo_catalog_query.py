#!/usr/bin/env python3
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path("/Volumes/Public/LAIA/catalogs/photo_ingest/photo_packets.db")

def connect():
    if not DB_PATH.exists():
        print(f"Catalog database not found: {DB_PATH}")
        print("Run: laia-photo catalog")
        sys.exit(1)
    return sqlite3.connect(DB_PATH)

def print_rows(headers, rows):
    if not rows:
        print("No results.")
        return

    widths = [len(h) for h in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(str(value)))

    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * widths[i] for i in range(len(headers))))

    for row in rows:
        print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))

def stats():
    conn = connect()
    cur = conn.cursor()

    packets = cur.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
    images = cur.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    total_bytes = cur.execute("SELECT COALESCE(SUM(file_size), 0) FROM images").fetchone()[0]
    cameras = cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT camera_make, camera_model
            FROM images
            GROUP BY camera_make, camera_model
        )
    """).fetchone()[0]

    print("LAIA Photo Catalog Stats")
    print()
    print(f"Database: {DB_PATH}")
    print(f"Packets:  {packets}")
    print(f"Images:   {images}")
    print(f"Cameras:  {cameras}")
    print(f"Bytes:    {total_bytes:,}")
    print(f"Approx:   {total_bytes / (1024**3):.2f} GiB")

    conn.close()

def cameras():
    conn = connect()
    rows = conn.execute("""
        SELECT
            COALESCE(NULLIF(camera_make, ''), 'Unknown') AS make,
            COALESCE(NULLIF(camera_model, ''), 'Unknown') AS model,
            COUNT(*) AS images
        FROM images
        GROUP BY make, model
        ORDER BY images DESC
    """).fetchall()
    print_rows(["make", "model", "images"], rows)
    conn.close()

def list_packets():
    conn = connect()
    rows = conn.execute("""
        SELECT job_id, photo_count, packet_size, created_at
        FROM packets
        ORDER BY created_at DESC
    """).fetchall()
    print_rows(["job_id", "photos", "size", "created_at"], rows)
    conn.close()

def recent(limit=20):
    conn = connect()
    rows = conn.execute("""
        SELECT filename, date_time_original, camera_model, job_id
        FROM images
        ORDER BY date_time_original DESC
        LIMIT ?
    """, (limit,)).fetchall()
    print_rows(["filename", "date_time_original", "camera", "job_id"], rows)
    conn.close()

def duplicates():
    conn = connect()
    rows = conn.execute("""
        SELECT sha256, COUNT(*) AS copies
        FROM checksums
        GROUP BY sha256
        HAVING COUNT(*) > 1
        ORDER BY copies DESC
    """).fetchall()

    if not rows:
        print("No duplicate checksums found.")
        conn.close()
        return

    print_rows(["sha256", "copies"], rows)

    print()
    print("Duplicate files:")
    detail_rows = conn.execute("""
        SELECT c.sha256, c.job_id, c.relative_path
        FROM checksums c
        WHERE c.sha256 IN (
            SELECT sha256
            FROM checksums
            GROUP BY sha256
            HAVING COUNT(*) > 1
        )
        ORDER BY c.sha256, c.job_id, c.relative_path
    """).fetchall()
    print_rows(["sha256", "job_id", "relative_path"], detail_rows)
    conn.close()

def help_text():
    print("LAIA Photo Catalog Query")
    print()
    print("Usage:")
    print("  laia_photo_catalog_query.py stats")
    print("  laia_photo_catalog_query.py cameras")
    print("  laia_photo_catalog_query.py list-packets")
    print("  laia_photo_catalog_query.py recent [limit]")
    print("  laia_photo_catalog_query.py duplicates")

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"

    if cmd == "stats":
        stats()
    elif cmd == "cameras":
        cameras()
    elif cmd == "list-packets":
        list_packets()
    elif cmd == "recent":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        recent(limit)
    elif cmd == "duplicates":
        duplicates()
    else:
        help_text()

if __name__ == "__main__":
    main()
