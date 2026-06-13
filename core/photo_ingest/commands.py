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


def _normalize_recent_args(args):
    args.limit = args.limit if args.limit is not None else (args.positional_limit or 20)
    return args
