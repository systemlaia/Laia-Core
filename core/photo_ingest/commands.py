import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

try:
    from photo_ingest.cohorts import (
        VALID_COHORT_STATUSES,
        VALID_SUBJECT_STATUSES,
        add_files,
        add_subject,
        append_cohort_history_event,
        build_contact_sheet,
        build_contact_sheet_html,
        cohort_dir,
        create_cohort,
        export_cohort,
        latest_cohort_export_path,
        range_files,
        read_cohort,
        read_cohort_index,
        read_cohort_project_links,
        read_subjects,
        remove_cohort_project_link,
        remove_files,
        resolve_photo_packet,
        upsert_cohort_project_link,
        update_cohort,
        update_subject,
    )
except ModuleNotFoundError:
    from core.photo_ingest.cohorts import (
        VALID_COHORT_STATUSES,
        VALID_SUBJECT_STATUSES,
        add_files,
        add_subject,
        append_cohort_history_event,
        build_contact_sheet,
        build_contact_sheet_html,
        cohort_dir,
        create_cohort,
        export_cohort,
        latest_cohort_export_path,
        range_files,
        read_cohort,
        read_cohort_index,
        read_cohort_project_links,
        read_subjects,
        remove_cohort_project_link,
        remove_files,
        resolve_photo_packet,
        upsert_cohort_project_link,
        update_cohort,
        update_subject,
    )

try:
    from photo_ingest.record_vision import (
        confirm_record,
        create_record_pair_cohorts,
        create_record_cohorts,
        identify_records,
        suggest_record_pairs,
        suggest_record_groups,
    )
except ModuleNotFoundError:
    from core.photo_ingest.record_vision import (
        confirm_record,
        create_record_pair_cohorts,
        create_record_cohorts,
        identify_records,
        suggest_record_pairs,
        suggest_record_groups,
    )

try:
    from packets.standard import (
        checksum_path as standard_checksum_path,
        count_checksum_entries,
        latest_packet as discover_latest_packet,
        parse_checksum_file,
        read_packet_manifest,
        read_review_sidecar,
        review_dir_path,
        review_sidecar_path,
        selects_path as standard_selects_path,
        validate_required_items,
        write_packet_manifest,
        write_review_sidecar,
    )
except ModuleNotFoundError:
    from core.packets.standard import (
        checksum_path as standard_checksum_path,
        count_checksum_entries,
        latest_packet as discover_latest_packet,
        parse_checksum_file,
        read_packet_manifest,
        read_review_sidecar,
        review_dir_path,
        review_sidecar_path,
        selects_path as standard_selects_path,
        validate_required_items,
        write_packet_manifest,
        write_review_sidecar,
    )


PHOTO_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".raf",
    ".raw",
    ".dng",
    ".tif",
    ".tiff",
    ".png",
}

PREVIEW_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}

DEFAULT_PACKET_ROOT = Path("/Volumes/Public/LAIA/packets/photo_ingest")
DEFAULT_CATALOG_ROOT = Path("/Volumes/Public/LAIA/catalogs/photo_ingest")
DEFAULT_LOCAL_ROOT = Path("~/LAIA/photo_ingest").expanduser()

DEFAULT_REVIEW = {
    "review_status": "new",
    "rating_pass": None,
    "notes": "",
    "reviewed_at": None,
    "updated_at": None,
}

VALID_REVIEW_STATUSES = {"new", "reviewed", "selected", "rejected", "exported", "published"}


@dataclass(frozen=True)
class PhotoConfig:
    packet_root: Path
    catalog_root: Path
    local_root: Path

    @property
    def db_path(self) -> Path:
        return self.catalog_root / "photo_packets.db"

    @property
    def csv_index_path(self) -> Path:
        return self.packet_root / "photo_ingest_index.csv"


def config_from_env() -> PhotoConfig:
    return PhotoConfig(
        packet_root=Path(os.environ.get("LAIA_PHOTO_PACKET_ROOT", DEFAULT_PACKET_ROOT)).expanduser(),
        catalog_root=Path(os.environ.get("LAIA_PHOTO_CATALOG_ROOT", DEFAULT_CATALOG_ROOT)).expanduser(),
        local_root=Path(os.environ.get("LAIA_PHOTO_LOCAL_ROOT", DEFAULT_LOCAL_ROOT)).expanduser(),
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_card_name(value: str) -> str:
    cleaned = "".join("_" if ch in " /:" else ch for ch in value)
    cleaned = "".join(ch for ch in cleaned if ch.isalnum() or ch in "_.-")
    return cleaned or "card"


def iter_photo_files(src: Path):
    for item in sorted(src.rglob("*")):
        if item.is_file() and item.suffix.lower() in PHOTO_EXTENSIONS:
            yield item


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def human_size(path: Path) -> str:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    units = ["B", "K", "M", "G", "T"]
    size = float(total)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{total}B"


def latest_packet(root: Optional[Path] = None) -> Path:
    cfg = config_from_env()
    packet_root = root or cfg.packet_root
    try:
        return discover_latest_packet(packet_root)
    except FileNotFoundError:
        raise SystemExit("No photo ingest packets found.")


def resolve_packet(packet_arg: Optional[str]) -> Path:
    if packet_arg in (None, "", "--last"):
        return latest_packet()
    packet = Path(packet_arg).expanduser()
    if not packet.is_dir():
        raise SystemExit(f"Packet folder not found: {packet}")
    return packet


def command_ingest_sd(args):
    cfg = config_from_env()
    src = Path(args.source).expanduser()
    if not src.is_dir():
        raise SystemExit(f"Source folder not found: {src}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    card_name = src.parent.name
    job_id = f"{stamp}_{safe_card_name(card_name)}_sd_ingest"
    packet = cfg.packet_root / datetime.now().strftime("%Y") / job_id
    log_path = cfg.local_root / "logs" / f"{job_id}.log"

    for folder in ["originals", "previews", "metadata", "contact_sheet", "logs"]:
        (packet / folder).mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    def log(message: str):
        print(message)
        with log_path.open("a", encoding="utf-8") as log_file:
            log_file.write(message + "\n")

    log(f"LAIA Photo SD Ingest Job: {job_id}")
    log(f"Source: {src}")
    log(f"Packet: {packet}")
    log(f"Started: {datetime.now()}")

    log("Copying originals to NAS packet...")
    copied = []
    for source_file in iter_photo_files(src):
        rel = source_file.relative_to(src)
        dest = packet / "originals" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, dest)
        copied.append(dest)

    log("Generating checksums...")
    checksum_path = packet / "checksums.sha256"
    with checksum_path.open("w", encoding="utf-8") as f:
        for file in sorted(copied):
            rel = "./" + str(file.relative_to(packet / "originals"))
            f.write(f"{file_sha256(file)}  {rel}\n")

    log("Generating EXIF metadata...")
    if shutil.which("exiftool"):
        with (packet / "metadata" / "exiftool.json").open("w", encoding="utf-8") as f:
            subprocess.run(["exiftool", "-json", "-r", str(packet / "originals")], stdout=f, check=False)
        with (packet / "metadata" / "exiftool.csv").open("w", encoding="utf-8") as f:
            subprocess.run(["exiftool", "-csv", "-r", str(packet / "originals")], stdout=f, check=False)
    else:
        log("exiftool not found; skipping EXIF extraction")

    log("Generating JPEG previews...")
    if shutil.which("magick"):
        preview_files = []
        for image in sorted(p for p in (packet / "originals").rglob("*") if p.is_file() and p.suffix.lower() in PREVIEW_EXTENSIONS):
            rel = image.relative_to(packet / "originals")
            out = packet / "previews" / rel.with_suffix(".jpg")
            out.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["magick", str(image), "-auto-orient", "-resize", "1600x1600>", "-quality", "85", str(out)],
                check=False,
            )
            if out.exists():
                preview_files.append(out)

        log("Creating contact sheet...")
        contact_list = packet / "contact_sheet" / "contact_sheet_files.txt"
        contact_items = sorted(preview_files)[:60]
        contact_list.write_text("\n".join(str(p) for p in contact_items) + ("\n" if contact_items else ""), encoding="utf-8")
        if contact_items:
            subprocess.run(
                [
                    "magick",
                    "montage",
                    f"@{contact_list}",
                    "-thumbnail",
                    "240x240",
                    "-background",
                    "white",
                    "-gravity",
                    "center",
                    "-extent",
                    "240x240",
                    "-tile",
                    "5x",
                    "-geometry",
                    "+8+8",
                    str(packet / "contact_sheet" / "contact_sheet.jpg"),
                ],
                check=False,
            )
    else:
        log("ImageMagick not found; skipping previews")
        log("ImageMagick not found; skipping contact sheet")

    photo_count = len(copied)
    packet_size = human_size(packet)
    manifest = {
        "packet_type": "laia.photo_ingest",
        "packet_version": "0.1",
        "job_id": job_id,
        "source": str(src),
        "packet_path": str(packet),
        "photo_count": photo_count,
        "packet_size": packet_size,
        "created_at": utc_now(),
    }
    write_packet_manifest(packet, manifest)
    (packet / "ingest_report.md").write_text(
        "\n".join(
            [
                "# LAIA Photo SD Ingest Report",
                "",
                f"Job ID: {job_id}  ",
                f"Source: {src}  ",
                f"Packet: {packet}  ",
                f"Completed: {datetime.now()}",
                "",
                "## Summary",
                "",
                f"- Photo count: {photo_count}",
                f"- Packet size: {packet_size}",
                "- Originals copied to NAS packet",
                "- SHA256 checksums generated",
                "- EXIF metadata extracted when available",
                "- JPEG previews generated when available",
                "- Contact sheet attempted",
                "",
                "## Packet Contents",
                "",
                "- originals/",
                "- previews/",
                "- metadata/",
                "- contact_sheet/",
                "- logs/",
                "- checksums.sha256",
                "- packet_manifest.json",
                "- ingest_report.md",
                "",
            ]
        ),
        encoding="utf-8",
    )
    shutil.copy2(log_path, packet / "logs" / "ingest.log")

    log(f"Completed: {datetime.now()}")
    log(f"Photo count: {photo_count}")
    log(f"Packet size: {packet_size}")
    log(f"Archived packet: {packet}")


def verify_packet(packet: Path) -> int:
    print("Verifying LAIA photo packet:")
    print(packet)
    print()

    required = [
        "originals",
        "previews",
        "metadata",
        "contact_sheet",
        "logs",
        "checksums.sha256",
        "packet_manifest.json",
        "ingest_report.md",
    ]
    validation = validate_required_items(packet, required)
    fail = 0
    for item in required:
        if item in validation.missing:
            print(f"MISSING: {item}")
            fail = 1
        else:
            print(f"OK: {item}")

    print()
    print("Counting files...")
    originals = packet / "originals"
    checksum_file = standard_checksum_path(packet)
    original_count = sum(1 for p in originals.rglob("*") if p.is_file()) if originals.exists() else 0
    checksum_entries = []
    checksum_lines = checksum_file.read_text(errors="replace").splitlines() if checksum_file.exists() else []
    checksum_count = 0
    if checksum_file.exists():
        try:
            checksum_entries = parse_checksum_file(checksum_file)
            checksum_count = count_checksum_entries(checksum_file)
        except ValueError:
            checksum_count = sum(1 for line in checksum_lines if line.strip())
    preview_count = sum(1 for p in (packet / "previews").rglob("*.jpg") if p.is_file()) if (packet / "previews").exists() else 0

    print(f"Originals: {original_count}")
    print(f"Checksums: {checksum_count}")
    print(f"Previews: {preview_count}")

    if original_count != checksum_count:
        print("WARNING: original count and checksum count do not match")
        fail = 1

    if not (packet / "contact_sheet" / "contact_sheet.jpg").is_file():
        print("WARNING: contact_sheet.jpg missing")
        fail = 1
    else:
        print("OK: contact_sheet.jpg")

    print()
    print("Running checksum verification...")
    if checksum_entries:
        checksum_items = [(entry.sha256, entry.relative_path) for entry in checksum_entries]
    else:
        checksum_items = []
        for line in checksum_lines:
            if not line.strip():
                continue
            parts = line.split(maxsplit=1)
            if len(parts) != 2:
                print(f"FAILED malformed checksum line: {line}")
                fail = 1
                continue
            expected, rel = parts
            rel = rel.strip()
            if rel.startswith("*"):
                rel = rel[1:]
            checksum_items.append((expected, rel))

    for expected, rel in checksum_items:
        if rel.startswith("./"):
            rel = rel[2:]
        file = originals / rel
        if not file.is_file():
            print(f"FAILED missing file: ./{rel}")
            fail = 1
            continue
        actual = file_sha256(file)
        if actual == expected:
            print(f"./{rel}: OK")
        else:
            print(f"./{rel}: FAILED")
            fail = 1

    print()
    if fail == 0:
        print("PACKET VERIFIED")
    else:
        print("PACKET HAS WARNINGS OR ERRORS")
    return fail


def command_verify(args):
    packet = resolve_packet(args.packet)
    result = verify_packet(packet)
    if result:
        raise SystemExit(2)


def command_verify_last(_args):
    packet = latest_packet()
    print("Latest packet:")
    print(packet)
    print()
    result = verify_packet(packet)
    if result:
        raise SystemExit(2)


def command_open_last(_args):
    packet = latest_packet()
    print("Opening:")
    print(packet)
    subprocess.run(["open", str(packet)], check=False)
    contact = packet / "contact_sheet" / "contact_sheet.jpg"
    if contact.is_file():
        subprocess.run(["open", str(contact)], check=False)


def packet_manifest_rows(packet_root: Path):
    for packet in sorted(p for p in packet_root.glob("*/*") if p.is_dir()):
        try:
            data = read_packet_manifest(packet)
        except Exception:
            continue
        yield packet, data


def command_rebuild_index(_args=None):
    cfg = config_from_env()
    cfg.packet_root.mkdir(parents=True, exist_ok=True)
    with cfg.csv_index_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["job_id", "packet_path", "source", "photo_count", "packet_size", "created_at"])
        for packet, data in packet_manifest_rows(cfg.packet_root):
            writer.writerow(
                [
                    data.get("job_id", ""),
                    data.get("packet_path", str(packet)),
                    data.get("source", ""),
                    data.get("photo_count", ""),
                    data.get("packet_size", ""),
                    data.get("created_at", ""),
                ]
            )
    print("Index written:")
    print(cfg.csv_index_path)


def initialize_catalog(db_path: Path):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.executescript(
        """
CREATE TABLE IF NOT EXISTS packets (
    job_id TEXT PRIMARY KEY,
    packet_path TEXT,
    source TEXT,
    photo_count INTEGER,
    packet_size TEXT,
    created_at TEXT,
    ingest_report TEXT,
    review_status TEXT,
    review_notes TEXT,
    reviewed_at TEXT,
    select_count INTEGER DEFAULT 0
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
"""
    )
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
    return conn


def build_catalog(packet_root: Path, db_path: Path):
    conn = initialize_catalog(db_path)
    cur = conn.cursor()

    for packet, manifest in packet_manifest_rows(packet_root):
        job_id = manifest.get("job_id", packet.name)
        report_path = packet / "ingest_report.md"
        ingest_report = report_path.read_text(errors="replace") if report_path.exists() else ""

        review_status = "new"
        review_notes = ""
        reviewed_at = None
        review_path = review_sidecar_path(packet)
        if review_path.exists():
            try:
                review = read_review_sidecar(packet)
                review_status = review.get("review_status", "new")
                review_notes = review.get("notes", "")
                reviewed_at = review.get("reviewed_at", None)
            except Exception:
                pass

        packet_selects_path = standard_selects_path(packet)
        select_count = len(read_selects(packet_selects_path)) if packet_selects_path.exists() else 0

        cur.execute(
            """
            INSERT OR REPLACE INTO packets
            (
                job_id, packet_path, source, photo_count, packet_size,
                created_at, ingest_report, review_status, review_notes, reviewed_at, select_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
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
            ),
        )
        cur.execute("DELETE FROM images WHERE job_id = ?", (job_id,))
        cur.execute("DELETE FROM checksums WHERE job_id = ?", (job_id,))

        checksum_file = standard_checksum_path(packet)
        if checksum_file.exists():
            try:
                for entry in parse_checksum_file(checksum_file):
                    cur.execute(
                        "INSERT OR REPLACE INTO checksums (job_id, relative_path, sha256) VALUES (?, ?, ?)",
                        (job_id, entry.relative_path, entry.sha256),
                    )
            except ValueError:
                for line in checksum_file.read_text(errors="replace").splitlines():
                    if not line.strip():
                        continue
                    parts = line.split(maxsplit=1)
                    if len(parts) == 2:
                        sha256, rel = parts
                        cur.execute(
                            "INSERT OR REPLACE INTO checksums (job_id, relative_path, sha256) VALUES (?, ?, ?)",
                            (job_id, rel.strip(), sha256),
                        )

        exif_by_rel = {}
        exif_json = packet / "metadata" / "exiftool.json"
        if exif_json.exists():
            try:
                for item in json.loads(exif_json.read_text(errors="replace")):
                    source_file = item.get("SourceFile", "")
                    rel = source_file.split("/originals/", 1)[-1].lstrip("./")
                    exif_by_rel[rel] = item
            except Exception as e:
                print(f"Warning: failed to parse EXIF for {packet}: {e}")

        originals = packet / "originals"
        if originals.exists():
            for file in sorted(p for p in originals.rglob("*") if p.is_file()):
                rel = str(file.relative_to(originals))
                exif = exif_by_rel.get(rel, {})
                cur.execute(
                    """
                    INSERT INTO images
                    (
                        job_id, relative_path, filename, extension, file_size,
                        camera_make, camera_model, lens_model, date_time_original,
                        iso, aperture, shutter_speed, focal_length
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
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
                    ),
                )

    conn.commit()
    return conn


def command_catalog(_args):
    cfg = config_from_env()
    conn = build_catalog(cfg.packet_root, cfg.db_path)
    cur = conn.cursor()
    packet_count = cur.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
    image_count = cur.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    camera_rows = cur.execute(
        """
        SELECT camera_make, camera_model, COUNT(*)
        FROM images
        GROUP BY camera_make, camera_model
        ORDER BY COUNT(*) DESC
        """
    ).fetchall()
    review_rows = cur.execute(
        """
        SELECT COALESCE(review_status, 'new'), COUNT(*)
        FROM packets
        GROUP BY COALESCE(review_status, 'new')
        ORDER BY COUNT(*) DESC
        """
    ).fetchall()
    conn.close()

    print(f"Catalog written: {cfg.db_path}")
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


def connect_catalog():
    cfg = config_from_env()
    if not cfg.db_path.exists():
        print(f"Catalog database not found: {cfg.db_path}")
        print("Run: laia photo catalog")
        raise SystemExit(1)
    return sqlite3.connect(cfg.db_path), cfg.db_path


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


def command_stats(_args):
    conn, db_path = connect_catalog()
    cur = conn.cursor()
    packets = cur.execute("SELECT COUNT(*) FROM packets").fetchone()[0]
    images = cur.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    total_bytes = cur.execute("SELECT COALESCE(SUM(file_size), 0) FROM images").fetchone()[0]
    cameras = cur.execute(
        """
        SELECT COUNT(*) FROM (
            SELECT camera_make, camera_model FROM images GROUP BY camera_make, camera_model
        )
        """
    ).fetchone()[0]
    print("LAIA Photo Catalog Stats")
    print()
    print(f"Database: {db_path}")
    print(f"Packets:  {packets}")
    print(f"Images:   {images}")
    print(f"Cameras:  {cameras}")
    print(f"Bytes:    {total_bytes:,}")
    print(f"Approx:   {total_bytes / (1024**3):.2f} GiB")
    conn.close()


def command_cameras(_args):
    conn, _ = connect_catalog()
    rows = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(camera_make, ''), 'Unknown') AS make,
            COALESCE(NULLIF(camera_model, ''), 'Unknown') AS model,
            COUNT(*) AS images
        FROM images
        GROUP BY make, model
        ORDER BY images DESC
        """
    ).fetchall()
    print_rows(["make", "model", "images"], rows)
    conn.close()


def command_list_packets(_args):
    conn, _ = connect_catalog()
    rows = conn.execute(
        """
        SELECT job_id, photo_count, packet_size, created_at
        FROM packets
        ORDER BY created_at DESC
        """
    ).fetchall()
    print_rows(["job_id", "photos", "size", "created_at"], rows)
    conn.close()


def command_recent(args):
    conn, _ = connect_catalog()
    rows = conn.execute(
        """
        SELECT filename, date_time_original, camera_model, job_id
        FROM images
        ORDER BY date_time_original DESC
        LIMIT ?
        """,
        (args.limit,),
    ).fetchall()
    print_rows(["filename", "date_time_original", "camera", "job_id"], rows)
    conn.close()


def command_duplicates(_args):
    conn, _ = connect_catalog()
    rows = conn.execute(
        """
        SELECT sha256, COUNT(*) AS copies
        FROM checksums
        GROUP BY sha256
        HAVING COUNT(*) > 1
        ORDER BY copies DESC
        """
    ).fetchall()
    if not rows:
        print("No duplicate checksums found.")
        conn.close()
        return
    print_rows(["sha256", "copies"], rows)
    print()
    print("Duplicate files:")
    detail_rows = conn.execute(
        """
        SELECT c.sha256, c.job_id, c.relative_path
        FROM checksums c
        WHERE c.sha256 IN (
            SELECT sha256 FROM checksums GROUP BY sha256 HAVING COUNT(*) > 1
        )
        ORDER BY c.sha256, c.job_id, c.relative_path
        """
    ).fetchall()
    print_rows(["sha256", "job_id", "relative_path"], detail_rows)
    conn.close()


def review_paths(packet: Path):
    return review_dir_path(packet), review_sidecar_path(packet), standard_selects_path(packet)


def ensure_review(packet: Path):
    _, review_json, selects_txt = review_paths(packet)
    try:
        data = read_review_sidecar(packet)
    except Exception:
        data = DEFAULT_REVIEW.copy()
    for key, value in DEFAULT_REVIEW.items():
        data.setdefault(key, value)
    if data["updated_at"] is None:
        data["updated_at"] = utc_now()
    data = write_review_sidecar(packet, data)
    return data, review_json, selects_txt


def command_review_last(_args):
    packet = latest_packet()
    data, review_json, selects_txt = ensure_review(packet)
    print("LAIA Photo Packet Review")
    print()
    print(f"Packet:       {packet}")
    print(f"Review file:  {review_json}")
    print(f"Selects file: {selects_txt}")
    print()
    print(f"Status:       {data.get('review_status', '')}")
    print(f"Rating pass:  {data.get('rating_pass', '')}")
    print(f"Reviewed at:  {data.get('reviewed_at', '')}")
    print(f"Updated at:   {data.get('updated_at', '')}")
    print(f"Notes:        {data.get('notes', '')}")


def set_review_status(status: str):
    if status not in VALID_REVIEW_STATUSES:
        raise SystemExit(f"Invalid status: {status}\nValid: {', '.join(sorted(VALID_REVIEW_STATUSES))}")
    packet = latest_packet()
    data, review_json, _ = ensure_review(packet)
    data["review_status"] = status
    data["updated_at"] = utc_now()
    data["reviewed_at"] = utc_now() if status != "new" else None
    write_review_sidecar(packet, data)
    print(f"Updated review status: {status}")
    print(f"Packet: {packet}")


def command_mark_reviewed(_args):
    set_review_status("reviewed")


def command_mark_new(_args):
    set_review_status("new")


def command_notes_last(args):
    packet = latest_packet()
    data, review_json, _ = ensure_review(packet)
    data["notes"] = " ".join(args.notes)
    data["updated_at"] = utc_now()
    write_review_sidecar(packet, data)
    print("Updated review notes.")
    print(f"Packet: {packet}")


def packet_paths(packet):
    review_dir = review_dir_path(packet)
    selects = standard_selects_path(packet)
    review_dir.mkdir(parents=True, exist_ok=True)
    if not selects.exists():
        selects.write_text("", encoding="utf-8")
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
    selects_path.write_text("\n".join(header + clean) + "\n", encoding="utf-8")


def command_add_select(args):
    packet = latest_packet()
    _, selects_path = packet_paths(packet)
    rel, _ = find_original(packet, args.query)
    rows = read_selects(selects_path)
    if rel not in rows:
        rows.append(rel)
        write_selects(selects_path, rows)
        print(f"Added select: {rel}")
    else:
        print(f"Already selected: {rel}")
    print(f"Selects file: {selects_path}")


def command_remove_select(args):
    packet = latest_packet()
    _, selects_path = packet_paths(packet)
    rows = read_selects(selects_path)
    q = args.query.lower()
    keep = []
    removed = []
    for row in rows:
        if row.lower() == q or Path(row).name.lower() == q or q in row.lower():
            removed.append(row)
        else:
            keep.append(row)
    if not removed:
        print(f"No select matched: {args.query}")
        return
    write_selects(selects_path, keep)
    for row in removed:
        print(f"Removed select: {row}")


def command_list_selects(_args):
    packet = latest_packet()
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


def command_clear_selects(_args):
    packet = latest_packet()
    _, selects_path = packet_paths(packet)
    write_selects(selects_path, [])
    print(f"Cleared selects: {selects_path}")


def command_export_selects(args):
    packet = latest_packet()
    _, selects_path = packet_paths(packet)
    rows = read_selects(selects_path)
    if not rows:
        raise SystemExit("No selects to export.")
    dest = Path(args.destination).expanduser()
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
            out = dest / f"{out.stem}_{copied + 1:03d}{out.suffix}"
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


def _print_json(data):
    print(json.dumps(data, indent=2))


def _subject_packet(args):
    return resolve_photo_packet(args.packet)


def command_subject_add(args):
    packet = _subject_packet(args)
    subject = add_subject(packet, args.subject_name, note=args.note, status=args.status)
    if args.json:
        _print_json(subject)
    else:
        print(f"{subject['subject_id']}: {subject['name']} ({subject['status']})")


def command_subjects(args):
    packet = _subject_packet(args)
    subjects = read_subjects(packet).get("subjects", [])
    if args.status:
        subjects = [item for item in subjects if item.get("status") == args.status]
    if args.json:
        _print_json(subjects)
        return
    print_rows(
        ["subject_id", "name", "status", "note", "updated_at"],
        [
            (
                item.get("subject_id", ""),
                item.get("name", ""),
                item.get("status", ""),
                item.get("note", ""),
                item.get("updated_at", ""),
            )
            for item in subjects
        ],
    )


def command_subject_update(args):
    packet = _subject_packet(args)
    if args.name is None and args.note is None and args.status is None:
        raise SystemExit("Supply at least one of --name, --note, or --status.")
    subject = update_subject(packet, args.subject_id, name=args.name, note=args.note, status=args.status)
    print(f"Updated subject: {subject['subject_id']}")


def command_subject_archive(args):
    packet = _subject_packet(args)
    subject = update_subject(packet, args.subject_id, status="archived")
    print(f"Archived subject: {subject['subject_id']}")


def command_cohort_create(args):
    packet = _subject_packet(args)
    cohort = create_cohort(
        packet,
        args.cohort_name,
        subject=args.subject,
        description=args.description or "",
        parent=args.parent,
        status=args.status,
    )
    if args.json:
        _print_json(cohort)
    else:
        print(f"{cohort['cohort_id']}: {cohort['name']} ({cohort['status']})")


def command_cohorts(args):
    packet = _subject_packet(args)
    entries = read_cohort_index(packet).get("cohorts", [])
    if args.status:
        entries = [item for item in entries if item.get("status") == args.status]
    if args.subject:
        subjects = read_subjects(packet)
        subject = next(
            (
                item
                for item in subjects.get("subjects", [])
                if item.get("subject_id") == args.subject
                or str(item.get("name", "")).lower() == args.subject.lower()
            ),
            None,
        )
        subject_id = subject["subject_id"] if subject else args.subject
        entries = [item for item in entries if item.get("subject_id") == subject_id]
    if args.json:
        _print_json(entries)
        return
    print_rows(
        ["cohort_id", "name", "subject", "parent", "status", "file_count", "updated_at"],
        [
            (
                item.get("cohort_id", ""),
                item.get("name", ""),
                item.get("subject_id") or "",
                item.get("parent_cohort_id") or "",
                item.get("status", ""),
                item.get("file_count", 0),
                item.get("updated_at", ""),
            )
            for item in entries
        ],
    )


def command_cohort_show(args):
    packet = _subject_packet(args)
    cohort = read_cohort(packet, args.cohort)
    if args.json:
        _print_json(cohort)
        return
    print(f"Cohort: {cohort['name']} ({cohort['cohort_id']})")
    print(f"Description: {cohort.get('description', '')}")
    print(f"Subject: {cohort.get('subject_id') or 'none'}")
    print(f"Parent: {cohort.get('parent_cohort_id') or 'none'}")
    print(f"Status: {cohort.get('status', '')}")
    print(f"File count: {len(cohort.get('files', []))}")
    print(f"Contact sheet: {cohort_dir(packet, cohort['cohort_id']) / 'contact_sheet.jpg'}")
    files = [item["relative_path"] for item in cohort.get("files", [])]
    if files:
        print("Files:")
        shown = files if len(files) <= 25 else files[:25]
        for value in shown:
            print(f"  {value}")
        if len(shown) < len(files):
            print(f"  ...and {len(files) - len(shown)} more")


def command_cohort_add(args):
    packet = _subject_packet(args)
    cohort, added = add_files(packet, args.cohort, args.files, note=args.note or "")
    result = {"cohort_id": cohort["cohort_id"], "added": added, "file_count": len(cohort["files"])}
    if args.json:
        _print_json(result)
    else:
        print(f"Added: {len(added)}")
        print(f"Cohort file count: {len(cohort['files'])}")


def command_cohort_add_range(args):
    packet = _subject_packet(args)
    selected = range_files(packet, args.folder, args.range_from, args.range_to)
    print(f"Range contains {len(selected)} existing files.")
    if args.dry_run:
        result = {"dry_run": True, "count": len(selected), "files": selected}
    else:
        cohort, added = add_files(packet, args.cohort, selected, event="range_added")
        result = {
            "dry_run": False,
            "range_count": len(selected),
            "added": added,
            "file_count": len(cohort["files"]),
        }
    if args.json:
        _print_json(result)
    elif args.dry_run:
        for value in selected:
            print(value)
    else:
        print(f"Added: {len(result['added'])}")


def command_cohort_remove(args):
    packet = _subject_packet(args)
    cohort, removed = remove_files(packet, args.cohort, args.files)
    result = {"cohort_id": cohort["cohort_id"], "removed": removed, "file_count": len(cohort["files"])}
    if args.json:
        _print_json(result)
    else:
        print(f"Removed memberships: {len(removed)}")
        print(f"Cohort file count: {len(cohort['files'])}")


def command_cohort_update(args):
    packet = _subject_packet(args)
    supplied = any(
        value is not None
        for value in [args.name, args.description, args.subject, args.parent, args.status]
    ) or args.clear_parent or args.clear_subject
    if not supplied:
        raise SystemExit("Supply at least one cohort update option.")
    cohort = update_cohort(
        packet,
        args.cohort,
        name=args.name,
        description=args.description,
        subject=args.subject,
        parent=args.parent,
        status=args.status,
        clear_parent=args.clear_parent,
        clear_subject=args.clear_subject,
    )
    print(f"Updated cohort: {cohort['cohort_id']}")


def command_cohort_contact_sheet(args):
    packet = _subject_packet(args)
    limit = None if getattr(args, "all", False) else args.limit
    html_result = build_contact_sheet_html(
        packet, args.cohort, limit=limit, page_size=args.page_size,
        columns=args.columns, use_previews=args.use_previews,
    )
    jpg_result = None
    jpg_error = ""
    try:
        jpg_result = build_contact_sheet(packet, args.cohort, limit=limit, columns=args.columns)
    except SystemExit as exc:
        jpg_error = str(exc)
    result = {
        "path": jpg_result["path"] if jpg_result else "",
        "html_path": html_result["path"],
        "files_path": html_result["files_path"],
        "file_count": html_result["file_count"],
        "jpg_error": jpg_error,
    }
    if args.open:
        subprocess.run(["open", html_result["path"]], check=False)
    if args.json:
        _print_json(result)
    else:
        if result["path"]:
            print(f"Contact sheet: {result['path']}")
        elif jpg_error:
            print(f"JPEG contact sheet unavailable: {jpg_error}")
        print(f"HTML contact sheet: {result['html_path']}")
        print(f"Files: {result['file_count']}")


def command_cohort_contact_sheet_html(args):
    packet = _subject_packet(args)
    result = build_contact_sheet_html(
        packet, args.cohort, page_size=args.page_size,
        columns=args.columns, use_previews=args.use_previews,
    )
    if args.open:
        subprocess.run(["open", result["path"]], check=False)
    if args.json:
        _print_json(result)
    else:
        print(f"HTML contact sheet: {result['path']}")
        print(f"Files: {result['file_count']}")


def command_cohort_identify_records(args):
    packet = _subject_packet(args)
    result = identify_records(
        packet, args.cohort, model=args.model, limit=args.limit,
        start=args.start, end=args.end, force=args.force,
    )
    if args.open_review:
        subprocess.run(["open", result["markdown_path"]], check=False)
    if args.json:
        _print_json(result)
    else:
        print(f"Record candidates: {result['markdown_path']}")
        print(f"Processed: {result['processed']}  Successful: {result['successful']}  Failed: {result['failed']}")


def command_records_suggest_groups(args):
    packet = _subject_packet(args)
    result = suggest_record_groups(packet, args.cohort, group_size=args.group_size)
    created = []
    if args.create_cohorts:
        created = create_record_cohorts(packet, args.cohort, limit=args.limit)
    if args.json:
        _print_json({**result, "created_cohorts": [row["cohort_id"] for row in created]})
    else:
        print("Suggested record groups:")
        for group in result["groups"]:
            print(f"\n{group['group_id']}")
            for value in group["files"]:
                print(f"  {value}")
        print(f"\nSuggestions: {result['markdown_path']}")
        if created:
            print(f"Created cohorts: {len(created)}")


def command_records_create_cohorts(args):
    packet = _subject_packet(args)
    if not args.from_suggestions:
        raise SystemExit("Use --from-suggestions.")
    created = create_record_cohorts(packet, args.cohort, limit=args.limit)
    if args.json:
        _print_json(created)
    else:
        for cohort in created:
            print(f"{cohort['cohort_id']}: {cohort['name']} ({len(cohort['files'])} files)")


def _comma_list(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def command_records_suggest_pairs(args):
    packet = _subject_packet(args)
    result = suggest_record_pairs(
        packet,
        args.parent_cohort,
        start=args.start,
        end=args.end,
        offset=args.offset or 0,
        limit=args.limit,
        mode=args.mode,
        prefix=args.prefix,
        start_index=args.start_index,
    )
    if args.json:
        _print_json(result)
        return
    print(f"Record Pair Suggestions: {result['parent_cohort']}")
    print(f"Packet: {result['packet']}")
    print(f"Mode: {result['mode']}")
    print("Range:")
    print(f"  start: {result['range'].get('start') or '-'}")
    print(f"  end: {result['range'].get('end') or '-'}")
    print("\nSuggested pairs:")
    for suggestion in result["suggestions"]:
        print(f"  {suggestion['id']}")
        print(f"    front: {suggestion['files'][0]}")
        print(f"    back:  {suggestion['files'][1]}")
        print(f"    status: {suggestion['status']}")
        print()
    print("Warnings:")
    warnings = list(result.get("warnings", []))
    for suggestion in result["suggestions"]:
        warnings.extend(suggestion.get("warnings", []))
    if warnings:
        for warning in warnings:
            print(f"  {warning}")
    else:
        print("  none")
    print(f"\nSuggestions: {result['markdown_path']}")


def command_records_create_pair_cohorts(args):
    packet = _subject_packet(args)
    if not args.from_suggestions and not args.suggestions_file:
        raise SystemExit("Use --from-suggestions or --suggestions-file.")
    result = create_record_pair_cohorts(
        packet,
        args.parent_cohort,
        suggestions_file=args.suggestions_file,
        limit=args.limit,
        only=_comma_list(args.only),
        skip_existing=args.skip_existing,
        force_existing=args.force_existing,
        mark_ready=args.mark_ready,
        export=args.export,
        contact_sheets=args.contact_sheets,
    )
    if args.json:
        _print_json(result)
        return
    print(f"Created record pair cohorts: {len(result['created'])}")
    print(f"Skipped existing: {sum(1 for item in result['skipped'] if item.get('reason') == 'already exists')}")
    if result["created"]:
        print("\nCreated:")
        for item in result["created"]:
            print(f"  {item['cohort_id']}: {item['file_count']} files")
    if result["skipped"]:
        print("\nSkipped:")
        for item in result["skipped"]:
            print(f"  {item['id']}: {item['reason']}")
    if result["exports"]:
        print("\nExports:")
        for item in result["exports"]:
            print(f"  {item['destination']}")


def command_record_confirm(args):
    packet = _subject_packet(args)
    result = confirm_record(
        packet, args.cohort, args.artist, args.title, args.label,
        args.catalog_number, args.notes,
    )
    if args.json:
        _print_json(result)
    else:
        print(f"Confirmed record metadata: {result['path']}")


def command_cohort_export(args):
    packet = _subject_packet(args)
    result = export_cohort(packet, args.cohort, destination=args.destination)
    if args.json:
        _print_json(result)
    else:
        print(f"Export folder: {result['destination']}")
        print(f"Copied: {result['file_count']}")
        print(f"Manifest: {result['manifest']}")


def command_cohort_history(args):
    packet = _subject_packet(args)
    history = read_cohort(packet, args.cohort).get("history", [])
    if args.json:
        _print_json(history)
        return
    if not history:
        print("No cohort history.")
        return
    for event in history:
        details = []
        if event.get("count") is not None:
            details.append(f"{event['count']} files")
        if event.get("destination"):
            details.append(event["destination"])
        suffix = f" - {', '.join(details)}" if details else ""
        print(f"{event.get('timestamp', '')}  {event.get('event', '')}{suffix}")


def _projects_registry_module():
    try:
        from projects import registry as projects_registry
    except (ImportError, ModuleNotFoundError):
        from core.projects import registry as projects_registry
    return projects_registry


def command_cohort_link_project(args):
    packet = _subject_packet(args)
    cohort = read_cohort(packet, args.cohort)
    projects_registry = _projects_registry_module()
    project = projects_registry.ensure_project_record(args.project, args.type)
    project_id = project["project_id"]
    linked_at = utc_now()
    artifact_path = args.artifact or latest_cohort_export_path(packet, cohort)
    packet_info = {
        "job_id": packet.name if not (packet / "packet_manifest.json").exists() else json.loads(
            (packet / "packet_manifest.json").read_text(encoding="utf-8")
        ).get("job_id", packet.name),
        "packet_type": "laia.photo_ingest",
        "packet_path": str(packet),
    }
    projects_registry.add_packet_to_project(project_id, packet_info, linked_at)
    if artifact_path:
        projects_registry.add_artifact_to_project(
            project_id,
            artifact_path,
            packet_info["job_id"],
            linked_at,
            artifact_type="photo_cohort_export",
        )
    cohort_path = cohort_dir(packet, cohort["cohort_id"])
    contribution = {
        "packet_id": packet_info["job_id"],
        "packet_path": str(packet),
        "cohort_id": cohort["cohort_id"],
        "cohort_name": cohort["name"],
        "cohort_path": str(cohort_path),
        "cohort_status": cohort.get("status", ""),
        "file_count": len(cohort.get("files", [])),
        "artifact_path": artifact_path or "",
        "linked_at": linked_at,
    }
    projects_registry.add_cohort_to_project(project_id, contribution)
    sidecar_entry = {
        "project_id": project_id,
        "project_name": project.get("name", args.project),
        "project_type": project.get("project_type", args.type),
        "project_record_path": str(projects_registry.project_folder(project_id)),
        "artifact_path": artifact_path or "",
        "linked_at": linked_at,
        "note": args.note or "",
    }
    existing_links = read_cohort_project_links(packet, cohort["cohort_id"]).get("links", [])
    is_new = not any(str(item.get("project_id", "")) == project_id for item in existing_links)
    link = upsert_cohort_project_link(packet, cohort["cohort_id"], sidecar_entry)
    if is_new:
        append_cohort_history_event(
            packet,
            cohort,
            {"event": "project_linked", "project_id": project_id, "timestamp": linked_at},
        )
    result = {"project": project, "cohort": contribution, "link": link}
    if args.json:
        _print_json(result)
    else:
        print(f"Linked cohort {cohort['cohort_id']} -> project {project_id}")


def command_cohort_unlink_project(args):
    packet = _subject_packet(args)
    cohort = read_cohort(packet, args.cohort)
    projects_registry = _projects_registry_module()
    try:
        project_id = projects_registry.find_project(args.project)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    packet_identifier = json.loads((packet / "packet_manifest.json").read_text(encoding="utf-8")).get(
        "job_id", packet.name
    )
    project_removed = projects_registry.remove_cohort_from_project(
        project_id, packet_identifier, cohort["cohort_id"]
    )
    sidecar_removed = remove_cohort_project_link(packet, cohort["cohort_id"], project_id)
    if project_removed or sidecar_removed:
        append_cohort_history_event(
            packet,
            cohort,
            {"event": "project_unlinked", "project_id": project_id, "timestamp": utc_now()},
        )
    print(f"Unlinked cohort {cohort['cohort_id']} from project {project_id}")


def command_cohort_project_links(args):
    packet = _subject_packet(args)
    cohort = read_cohort(packet, args.cohort)
    links = read_cohort_project_links(packet, cohort["cohort_id"]).get("links", [])
    if args.json:
        _print_json(links)
        return
    print_rows(
        ["project_id", "project_name", "project_type", "artifact_path", "linked_at"],
        [
            (
                link.get("project_id", ""),
                link.get("project_name", ""),
                link.get("project_type", ""),
                link.get("artifact_path", ""),
                link.get("linked_at", ""),
            )
            for link in links
        ],
    )


def register_photo_subcommands(sub):
    photo_p = sub.add_parser("photo", help="Photo ingest commands")
    photo_sub = photo_p.add_subparsers(dest="photo_command")

    ingest_sd_p = photo_sub.add_parser("ingest-sd", help="Ingest photos from an SD card DCIM folder")
    ingest_sd_p.add_argument("source")
    ingest_sd_p.set_defaults(func=command_ingest_sd)

    verify_p = photo_sub.add_parser("verify", help="Verify a photo packet")
    verify_p.add_argument("packet")
    verify_p.set_defaults(func=command_verify)

    photo_sub.add_parser("verify-last", help="Verify latest photo packet").set_defaults(func=command_verify_last)
    photo_sub.add_parser("open-last", help="Open latest photo packet").set_defaults(func=command_open_last)
    photo_sub.add_parser("index", help="Rebuild photo CSV index").set_defaults(func=command_rebuild_index)
    photo_sub.add_parser("catalog", help="Build photo SQLite catalog").set_defaults(func=command_catalog)
    photo_sub.add_parser("stats", help="Show photo catalog stats").set_defaults(func=command_stats)
    photo_sub.add_parser("cameras", help="List cameras in photo catalog").set_defaults(func=command_cameras)
    photo_sub.add_parser("list-packets", help="List photo packets").set_defaults(func=command_list_packets)

    recent_p = photo_sub.add_parser("recent", help="List recent catalog images")
    recent_p.add_argument("positional_limit", nargs="?", type=int)
    recent_p.add_argument("--limit", type=int, default=None)
    recent_p.set_defaults(func=lambda args: command_recent(_normalize_recent_args(args)))

    photo_sub.add_parser("duplicates", help="List duplicate photo checksums").set_defaults(func=command_duplicates)
    photo_sub.add_parser("review-last", help="Show latest packet review sidecar").set_defaults(func=command_review_last)
    photo_sub.add_parser("mark-reviewed", help="Mark latest packet reviewed").set_defaults(func=command_mark_reviewed)
    photo_sub.add_parser("mark-new", help="Mark latest packet new").set_defaults(func=command_mark_new)

    notes_p = photo_sub.add_parser("notes-last", help="Set notes on latest packet")
    notes_p.add_argument("notes", nargs="+")
    notes_p.set_defaults(func=command_notes_last)

    add_select_p = photo_sub.add_parser("add-select", help="Add a select from latest packet")
    add_select_p.add_argument("query")
    add_select_p.set_defaults(func=command_add_select)

    remove_select_p = photo_sub.add_parser("remove-select", help="Remove a select from latest packet")
    remove_select_p.add_argument("query")
    remove_select_p.set_defaults(func=command_remove_select)

    photo_sub.add_parser("list-selects", help="List latest packet selects").set_defaults(func=command_list_selects)
    photo_sub.add_parser("clear-selects", help="Clear latest packet selects").set_defaults(func=command_clear_selects)

    export_p = photo_sub.add_parser("export-selects", help="Export latest packet selects")
    export_p.add_argument("destination")
    export_p.set_defaults(func=command_export_selects)

    subject_add_p = photo_sub.add_parser("subject-add", help="Add a named subject to a photo packet")
    subject_add_p.add_argument("packet")
    subject_add_p.add_argument("subject_name")
    subject_add_p.add_argument("--note", default=None)
    subject_add_p.add_argument("--status", choices=sorted(VALID_SUBJECT_STATUSES), default=None)
    subject_add_p.add_argument("--json", action="store_true")
    subject_add_p.set_defaults(func=command_subject_add)

    subjects_p = photo_sub.add_parser("subjects", help="List photo packet subjects")
    subjects_p.add_argument("packet")
    subjects_p.add_argument("--status", choices=sorted(VALID_SUBJECT_STATUSES))
    subjects_p.add_argument("--json", action="store_true")
    subjects_p.set_defaults(func=command_subjects)

    subject_update_p = photo_sub.add_parser("subject-update", help="Update a photo packet subject")
    subject_update_p.add_argument("packet")
    subject_update_p.add_argument("subject_id")
    subject_update_p.add_argument("--name")
    subject_update_p.add_argument("--note")
    subject_update_p.add_argument("--status", choices=sorted(VALID_SUBJECT_STATUSES))
    subject_update_p.set_defaults(func=command_subject_update)

    subject_archive_p = photo_sub.add_parser("subject-archive", help="Archive a photo packet subject")
    subject_archive_p.add_argument("packet")
    subject_archive_p.add_argument("subject_id")
    subject_archive_p.set_defaults(func=command_subject_archive)

    cohort_create_p = photo_sub.add_parser("cohort-create", help="Create a reusable photo cohort")
    cohort_create_p.add_argument("packet")
    cohort_create_p.add_argument("cohort_name")
    cohort_create_p.add_argument("--subject")
    cohort_create_p.add_argument("--description")
    cohort_create_p.add_argument("--parent")
    cohort_create_p.add_argument("--status", choices=sorted(VALID_COHORT_STATUSES), default="new")
    cohort_create_p.add_argument("--json", action="store_true")
    cohort_create_p.set_defaults(func=command_cohort_create)

    cohorts_p = photo_sub.add_parser("cohorts", help="List photo packet cohorts")
    cohorts_p.add_argument("packet")
    cohorts_p.add_argument("--status", choices=sorted(VALID_COHORT_STATUSES))
    cohorts_p.add_argument("--subject")
    cohorts_p.add_argument("--json", action="store_true")
    cohorts_p.set_defaults(func=command_cohorts)

    cohort_show_p = photo_sub.add_parser("cohort-show", help="Show photo cohort details")
    cohort_show_p.add_argument("packet")
    cohort_show_p.add_argument("cohort")
    cohort_show_p.add_argument("--json", action="store_true")
    cohort_show_p.set_defaults(func=command_cohort_show)

    cohort_add_p = photo_sub.add_parser("cohort-add", help="Add original files to a cohort")
    cohort_add_p.add_argument("packet")
    cohort_add_p.add_argument("cohort")
    cohort_add_p.add_argument("files", nargs="+")
    cohort_add_p.add_argument("--note")
    cohort_add_p.add_argument("--json", action="store_true")
    cohort_add_p.set_defaults(func=command_cohort_add)

    cohort_range_p = photo_sub.add_parser("cohort-add-range", help="Add a natural filename range to a cohort")
    cohort_range_p.add_argument("packet")
    cohort_range_p.add_argument("cohort")
    cohort_range_p.add_argument("--folder", required=True)
    cohort_range_p.add_argument("--from", dest="range_from", required=True)
    cohort_range_p.add_argument("--to", dest="range_to", required=True)
    cohort_range_p.add_argument("--dry-run", action="store_true")
    cohort_range_p.add_argument("--json", action="store_true")
    cohort_range_p.set_defaults(func=command_cohort_add_range)

    cohort_remove_p = photo_sub.add_parser("cohort-remove", help="Remove cohort membership")
    cohort_remove_p.add_argument("packet")
    cohort_remove_p.add_argument("cohort")
    cohort_remove_p.add_argument("files", nargs="+")
    cohort_remove_p.add_argument("--json", action="store_true")
    cohort_remove_p.set_defaults(func=command_cohort_remove)

    cohort_update_p = photo_sub.add_parser("cohort-update", help="Update cohort metadata")
    cohort_update_p.add_argument("packet")
    cohort_update_p.add_argument("cohort")
    cohort_update_p.add_argument("--name")
    cohort_update_p.add_argument("--description")
    cohort_update_p.add_argument("--subject")
    cohort_update_p.add_argument("--parent")
    cohort_update_p.add_argument("--status", choices=sorted(VALID_COHORT_STATUSES))
    cohort_update_p.add_argument("--clear-parent", action="store_true")
    cohort_update_p.add_argument("--clear-subject", action="store_true")
    cohort_update_p.set_defaults(func=command_cohort_update)

    contact_p = photo_sub.add_parser("cohort-contact-sheet", help="Build a cohort contact sheet")
    contact_p.add_argument("packet")
    contact_p.add_argument("cohort")
    contact_p.add_argument("--limit", type=int)
    contact_p.add_argument("--columns", type=int, default=5)
    contact_p.add_argument("--page-size", type=int, default=25)
    contact_p.add_argument("--html", action="store_true")
    contact_p.add_argument("--labels", action="store_true")
    contact_p.add_argument("--all", action="store_true")
    contact_p.add_argument("--use-previews", action=argparse.BooleanOptionalAction, default=True)
    contact_p.add_argument("--open", action="store_true")
    contact_p.add_argument("--json", action="store_true")
    contact_p.set_defaults(func=command_cohort_contact_sheet)

    html_contact_p = photo_sub.add_parser("cohort-contact-sheet-html", help="Build a labeled HTML cohort contact sheet")
    html_contact_p.add_argument("packet")
    html_contact_p.add_argument("cohort")
    html_contact_p.add_argument("--page-size", type=int, default=25)
    html_contact_p.add_argument("--columns", type=int, default=5)
    html_contact_p.add_argument("--use-previews", action=argparse.BooleanOptionalAction, default=True)
    html_contact_p.add_argument("--open", action="store_true")
    html_contact_p.add_argument("--json", action="store_true")
    html_contact_p.set_defaults(func=command_cohort_contact_sheet_html)

    identify_records_p = photo_sub.add_parser("cohort-identify-records", help="Identify vinyl records with local Ollama vision")
    identify_records_p.add_argument("packet")
    identify_records_p.add_argument("cohort")
    identify_records_p.add_argument("--model", default="llava")
    identify_records_p.add_argument("--limit", type=int)
    identify_records_p.add_argument("--start")
    identify_records_p.add_argument("--end")
    identify_records_p.add_argument("--force", action="store_true")
    identify_records_p.add_argument("--json", action="store_true")
    identify_records_p.add_argument("--open-review", action="store_true")
    identify_records_p.set_defaults(func=command_cohort_identify_records)

    suggest_groups_p = photo_sub.add_parser("records-suggest-groups", help="Suggest adjacent image groups for records")
    suggest_groups_p.add_argument("packet")
    suggest_groups_p.add_argument("cohort")
    suggest_groups_p.add_argument("--group-size", type=int, default=3)
    suggest_groups_p.add_argument("--create-cohorts", action="store_true")
    suggest_groups_p.add_argument("--limit", type=int)
    suggest_groups_p.add_argument("--json", action="store_true")
    suggest_groups_p.set_defaults(func=command_records_suggest_groups)

    create_records_p = photo_sub.add_parser("records-create-cohorts", help="Create record child cohorts from suggestions")
    create_records_p.add_argument("packet")
    create_records_p.add_argument("cohort")
    create_records_p.add_argument("--from-suggestions", action="store_true")
    create_records_p.add_argument("--limit", type=int)
    create_records_p.add_argument("--json", action="store_true")
    create_records_p.set_defaults(func=command_records_create_cohorts)

    suggest_pairs_p = photo_sub.add_parser("records-suggest-pairs", help="Suggest two-photo record child cohorts")
    suggest_pairs_p.add_argument("packet")
    suggest_pairs_p.add_argument("parent_cohort")
    suggest_pairs_p.add_argument("--start")
    suggest_pairs_p.add_argument("--end")
    suggest_pairs_p.add_argument("--offset", type=int, default=0)
    suggest_pairs_p.add_argument("--limit", type=int)
    suggest_pairs_p.add_argument("--mode", default="pairs")
    suggest_pairs_p.add_argument("--prefix", default="record")
    suggest_pairs_p.add_argument("--start-index", type=int, default=1)
    suggest_pairs_p.add_argument("--dry-run", action="store_true")
    suggest_pairs_p.add_argument("--json", action="store_true")
    suggest_pairs_p.set_defaults(func=command_records_suggest_pairs)

    create_pairs_p = photo_sub.add_parser("records-create-pair-cohorts", help="Create two-photo record child cohorts from pair suggestions")
    create_pairs_p.add_argument("packet")
    create_pairs_p.add_argument("parent_cohort")
    create_pairs_p.add_argument("--from-suggestions", action="store_true")
    create_pairs_p.add_argument("--suggestions-file")
    create_pairs_p.add_argument("--limit", type=int)
    create_pairs_p.add_argument("--only")
    create_pairs_p.add_argument("--skip-existing", action=argparse.BooleanOptionalAction, default=True)
    create_pairs_p.add_argument("--force-existing", action=argparse.BooleanOptionalAction, default=False)
    create_pairs_p.add_argument("--mark-ready", action="store_true")
    create_pairs_p.add_argument("--export", action="store_true")
    create_pairs_p.add_argument("--contact-sheets", action="store_true")
    create_pairs_p.add_argument("--json", action="store_true")
    create_pairs_p.set_defaults(func=command_records_create_pair_cohorts)

    confirm_record_p = photo_sub.add_parser("record-confirm", help="Write human-confirmed record metadata")
    confirm_record_p.add_argument("packet")
    confirm_record_p.add_argument("cohort")
    confirm_record_p.add_argument("--artist", required=True)
    confirm_record_p.add_argument("--title", required=True)
    confirm_record_p.add_argument("--label", default="")
    confirm_record_p.add_argument("--catalog-number", default="")
    confirm_record_p.add_argument("--notes", default="")
    confirm_record_p.add_argument("--json", action="store_true")
    confirm_record_p.set_defaults(func=command_record_confirm)

    cohort_export_p = photo_sub.add_parser("cohort-export", help="Export cohort originals and metadata")
    cohort_export_p.add_argument("packet")
    cohort_export_p.add_argument("cohort")
    cohort_export_p.add_argument("destination", nargs="?")
    cohort_export_p.add_argument("--json", action="store_true")
    cohort_export_p.set_defaults(func=command_cohort_export)

    history_p = photo_sub.add_parser("cohort-history", help="Show cohort history")
    history_p.add_argument("packet")
    history_p.add_argument("cohort")
    history_p.add_argument("--json", action="store_true")
    history_p.set_defaults(func=command_cohort_history)

    link_project_p = photo_sub.add_parser("cohort-link-project", help="Link a photo cohort to a project")
    link_project_p.add_argument("packet")
    link_project_p.add_argument("cohort")
    link_project_p.add_argument("--project", required=True)
    link_project_p.add_argument("--type", choices=["project", "publication"], default="project")
    link_project_p.add_argument("--artifact")
    link_project_p.add_argument("--note")
    link_project_p.add_argument("--json", action="store_true")
    link_project_p.set_defaults(func=command_cohort_link_project)

    unlink_project_p = photo_sub.add_parser("cohort-unlink-project", help="Unlink a cohort from a project")
    unlink_project_p.add_argument("packet")
    unlink_project_p.add_argument("cohort")
    unlink_project_p.add_argument("--project", required=True)
    unlink_project_p.set_defaults(func=command_cohort_unlink_project)

    project_links_p = photo_sub.add_parser("cohort-project-links", help="List project links for a cohort")
    project_links_p.add_argument("packet")
    project_links_p.add_argument("cohort")
    project_links_p.add_argument("--json", action="store_true")
    project_links_p.set_defaults(func=command_cohort_project_links)


def _normalize_recent_args(args):
    args.limit = args.limit if args.limit is not None else (args.positional_limit or 20)
    return args
