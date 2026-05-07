#!/usr/bin/env python3

from pathlib import Path
import sqlite3
import subprocess
import json
from tqdm import tqdm
from datetime import datetime

ROOT = Path.home() / "LAIA/archive/media"
DB_PATH = Path.home() / "LAIA/index/sqlite/archive.db"

PHOTO_EXTENSIONS = {
    ".jpg", ".jpeg", ".raf", ".png", ".dng", ".tif", ".tiff"
}

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        path TEXT UNIQUE,
        filename TEXT,
        extension TEXT,
        size INTEGER,
        modified TEXT,
        camera_model TEXT,
        film_mode TEXT,
        datetime_original TEXT
    )
    """)

    conn.commit()
    return conn

def exif_extract(path):
    try:
        result = subprocess.run(
            [
                "exiftool",
                "-j",
                "-Model",
                "-FilmMode",
                "-DateTimeOriginal",
                str(path)
            ],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            return {}

        data = json.loads(result.stdout)

        if not data:
            return {}

        return data[0]

    except Exception:
        return {}

def scan_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        if path.suffix.lower() not in PHOTO_EXTENSIONS:
            continue

        yield path

def main():
    print("== LAIA INGEST INDEX ==")
    print(f"Root: {ROOT}")
    print()

    conn = init_db()
    cur = conn.cursor()

    files = list(scan_files())

    print(f"Discovered {len(files)} candidate files")
    print()

    indexed = 0
    skipped = 0

    for path in tqdm(files):

        stat = path.stat()

        modified = datetime.fromtimestamp(
            stat.st_mtime
        ).isoformat()

        cur.execute(
            "SELECT modified FROM files WHERE path=?",
            (str(path),)
        )

        existing = cur.fetchone()

        if existing and existing[0] == modified:
            skipped += 1
            continue

        exif = exif_extract(path)

        cur.execute("""
        INSERT OR REPLACE INTO files (
            path,
            filename,
            extension,
            size,
            modified,
            camera_model,
            film_mode,
            datetime_original
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            str(path),
            path.name,
            path.suffix.lower(),
            stat.st_size,
            modified,
            exif.get("Model"),
            exif.get("FilmMode"),
            exif.get("DateTimeOriginal")
        ))

        indexed += 1

    conn.commit()
    conn.close()

    print()
    print(f"Indexed: {indexed}")
    print(f"Skipped unchanged: {skipped}")
    print()
    print(f"Database: {DB_PATH}")

if __name__ == "__main__":
    main()
