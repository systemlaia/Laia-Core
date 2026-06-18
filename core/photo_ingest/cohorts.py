import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from typing import Optional


VALID_SUBJECT_STATUSES = {"active", "deferred", "archived"}
VALID_COHORT_STATUSES = {"new", "in_review", "reviewed", "ready", "archived"}
DEFAULT_EXPORT_ROOT = Path("~/LAIA/exports/photo_cohorts").expanduser()
CONTACT_SHEET_FONT_ENV = "LAIA_PHOTO_CONTACT_SHEET_FONT"
CONTACT_SHEET_FONT_CANDIDATES = (
    Path("/System/Library/Fonts/Helvetica.ttc"),
    Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "item"


def natural_key(value: str):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Invalid JSON sidecar: {path}: {exc}")
    return data


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def packet_id(packet: Path) -> str:
    manifest = packet / "packet_manifest.json"
    data = _read_json(manifest, {})
    return str(data.get("job_id") or data.get("packet_id") or packet.name)


def resolve_photo_packet(identifier: str) -> Path:
    direct = Path(identifier).expanduser()
    if direct.is_dir():
        return direct.resolve()

    try:
        from packets.registry import config_from_env as registry_config_from_env, resolve_packet
    except ModuleNotFoundError:
        from core.packets.registry import config_from_env as registry_config_from_env, resolve_packet

    cfg = registry_config_from_env()
    try:
        row = resolve_packet(identifier, cfg.db_path)
        packet = Path(row["packet_path"]).expanduser()
        if packet.is_dir():
            return packet.resolve()
    except (FileNotFoundError, sqlite3.Error):
        pass

    photo_root = Path(os.environ.get("LAIA_PHOTO_PACKET_ROOT", "/Volumes/Public/LAIA/packets/photo_ingest")).expanduser()
    matches = [path for path in photo_root.glob(f"*/{identifier}") if path.is_dir()]
    if len(matches) == 1:
        return matches[0].resolve()
    if len(matches) > 1:
        raise SystemExit(f"Packet ID is ambiguous: {identifier}")
    raise SystemExit(f"Photo packet not found by ID or path: {identifier}")


def subjects_path(packet: Path) -> Path:
    return packet / "review" / "photo_subjects.json"


def read_subjects(packet: Path) -> dict:
    return _read_json(
        subjects_path(packet),
        {"packet_id": packet_id(packet), "updated_at": "", "subjects": []},
    )


def write_subjects(packet: Path, data: dict) -> dict:
    data["packet_id"] = packet_id(packet)
    data["updated_at"] = utc_now()
    data.setdefault("subjects", [])
    _write_json(subjects_path(packet), data)
    return data


def find_subject(data: dict, query: str) -> Optional[dict]:
    query_lower = query.strip().lower()
    query_slug = slugify(query)
    for subject in data.get("subjects", []):
        if subject.get("subject_id") == query or subject.get("subject_id") == query_slug:
            return subject
        if str(subject.get("name", "")).strip().lower() == query_lower:
            return subject
    return None


def add_subject(packet: Path, name: str, note: Optional[str] = None, status: Optional[str] = None) -> dict:
    status_value = status or "active"
    if status_value not in VALID_SUBJECT_STATUSES:
        raise SystemExit(f"Invalid subject status: {status_value}")
    data = read_subjects(packet)
    subject_id = slugify(name)
    subject = find_subject(data, subject_id)
    now = utc_now()
    if subject is None:
        subject = {
            "subject_id": subject_id,
            "name": name,
            "status": status_value,
            "note": note or "",
            "created_at": now,
            "updated_at": now,
        }
        data["subjects"].append(subject)
    else:
        changed = False
        if note is not None and subject.get("note") != note:
            subject["note"] = note
            changed = True
        if status is not None and subject.get("status") != status:
            subject["status"] = status
            changed = True
        if changed:
            subject["updated_at"] = now
    write_subjects(packet, data)
    return subject


def update_subject(
    packet: Path,
    subject_id: str,
    name: Optional[str] = None,
    note: Optional[str] = None,
    status: Optional[str] = None,
) -> dict:
    if status is not None and status not in VALID_SUBJECT_STATUSES:
        raise SystemExit(f"Invalid subject status: {status}")
    data = read_subjects(packet)
    subject = find_subject(data, subject_id)
    if subject is None:
        raise SystemExit(f"Subject not found: {subject_id}")
    changed = False
    for key, value in (("name", name), ("note", note), ("status", status)):
        if value is not None and subject.get(key) != value:
            subject[key] = value
            changed = True
    if changed:
        subject["updated_at"] = utc_now()
        write_subjects(packet, data)
    return subject


def cohorts_root(packet: Path) -> Path:
    return packet / "review" / "cohorts"


def cohorts_index_path(packet: Path) -> Path:
    return cohorts_root(packet) / "index.json"


def read_cohort_index(packet: Path) -> dict:
    return _read_json(
        cohorts_index_path(packet),
        {"packet_id": packet_id(packet), "updated_at": "", "cohorts": []},
    )


def write_cohort_index(packet: Path, data: dict) -> dict:
    data["packet_id"] = packet_id(packet)
    data["updated_at"] = utc_now()
    data.setdefault("cohorts", [])
    _write_json(cohorts_index_path(packet), data)
    return data


def cohort_dir(packet: Path, cohort_id: str) -> Path:
    return cohorts_root(packet) / cohort_id


def cohort_json_path(packet: Path, cohort_id: str) -> Path:
    return cohort_dir(packet, cohort_id) / "cohort.json"


def cohort_project_links_path(packet: Path, cohort_id: str) -> Path:
    return cohort_dir(packet, cohort_id) / "project_links.json"


def read_cohort_project_links(packet: Path, cohort_id: str) -> dict:
    data = _read_json(
        cohort_project_links_path(packet, cohort_id),
        {"packet_id": packet_id(packet), "cohort_id": cohort_id, "links": []},
    )
    data.setdefault("packet_id", packet_id(packet))
    data.setdefault("cohort_id", cohort_id)
    data.setdefault("links", [])
    return data


def write_cohort_project_links(packet: Path, cohort_id: str, data: dict) -> dict:
    data["packet_id"] = packet_id(packet)
    data["cohort_id"] = cohort_id
    data.setdefault("links", [])
    _write_json(cohort_project_links_path(packet, cohort_id), data)
    return data


def upsert_cohort_project_link(packet: Path, cohort_id: str, entry: dict) -> dict:
    data = read_cohort_project_links(packet, cohort_id)
    project_id = str(entry.get("project_id", ""))
    existing = next((item for item in data["links"] if str(item.get("project_id", "")) == project_id), None)
    if existing is None:
        data["links"].append(entry)
        link = entry
    else:
        existing.update(entry)
        link = existing
    write_cohort_project_links(packet, cohort_id, data)
    return link


def remove_cohort_project_link(packet: Path, cohort_id: str, project_id: str) -> bool:
    data = read_cohort_project_links(packet, cohort_id)
    filtered = [item for item in data["links"] if str(item.get("project_id", "")) != str(project_id)]
    if len(filtered) == len(data["links"]):
        return False
    data["links"] = filtered
    write_cohort_project_links(packet, cohort_id, data)
    return True


def read_cohort(packet: Path, query: str) -> dict:
    index = read_cohort_index(packet)
    query_lower = query.strip().lower()
    query_slug = slugify(query)
    entry = next(
        (
            item
            for item in index.get("cohorts", [])
            if item.get("cohort_id") in {query, query_slug}
            or str(item.get("name", "")).strip().lower() == query_lower
        ),
        None,
    )
    if entry is None:
        raise SystemExit(f"Cohort not found: {query}")
    path = cohort_json_path(packet, entry["cohort_id"])
    data = _read_json(path, None)
    if not isinstance(data, dict):
        raise SystemExit(f"Cohort metadata missing or invalid: {path}")
    return data


def _cohort_index_entry(cohort: dict) -> dict:
    return {
        "cohort_id": cohort["cohort_id"],
        "name": cohort["name"],
        "subject_id": cohort.get("subject_id"),
        "parent_cohort_id": cohort.get("parent_cohort_id"),
        "status": cohort.get("status", "new"),
        "file_count": len(cohort.get("files", [])),
        "updated_at": cohort.get("updated_at", ""),
    }


def write_cohort(packet: Path, cohort: dict) -> dict:
    cohort["updated_at"] = utc_now()
    cohort.setdefault("files", [])
    cohort.setdefault("history", [])
    folder = cohort_dir(packet, cohort["cohort_id"])
    folder.mkdir(parents=True, exist_ok=True)
    _write_json(folder / "cohort.json", cohort)
    lines = [str(item["relative_path"]) for item in cohort["files"]]
    (folder / "files.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    index = read_cohort_index(packet)
    entry = _cohort_index_entry(cohort)
    existing = next((item for item in index["cohorts"] if item.get("cohort_id") == cohort["cohort_id"]), None)
    if existing is None:
        index["cohorts"].append(entry)
    else:
        existing.clear()
        existing.update(entry)
    write_cohort_index(packet, index)
    return cohort


def create_cohort(
    packet: Path,
    name: str,
    subject: Optional[str] = None,
    description: str = "",
    parent: Optional[str] = None,
    status: str = "new",
) -> dict:
    if status not in VALID_COHORT_STATUSES:
        raise SystemExit(f"Invalid cohort status: {status}")
    cohort_id = slugify(name)
    index = read_cohort_index(packet)
    existing = next((item for item in index["cohorts"] if item.get("cohort_id") == cohort_id), None)
    if existing is not None:
        return read_cohort(packet, cohort_id)
    subject_id = None
    if subject:
        found_subject = find_subject(read_subjects(packet), subject)
        if found_subject is None:
            raise SystemExit(f"Subject not found: {subject}")
        subject_id = found_subject["subject_id"]
    parent_id = None
    if parent:
        parent_id = read_cohort(packet, parent)["cohort_id"]
        if parent_id == cohort_id:
            raise SystemExit("A cohort cannot be its own parent.")
    now = utc_now()
    cohort = {
        "cohort_id": cohort_id,
        "name": name,
        "description": description,
        "subject_id": subject_id,
        "parent_cohort_id": parent_id,
        "status": status,
        "created_at": now,
        "updated_at": now,
        "files": [],
        "history": [{"event": "created", "timestamp": now}],
    }
    return write_cohort(packet, cohort)


def validate_original_path(packet: Path, relative_path: str) -> tuple[str, Path]:
    raw = Path(relative_path)
    if raw.is_absolute():
        raise SystemExit(f"Original path must be packet-relative: {relative_path}")
    clean = Path(str(raw).replace("\\", "/"))
    originals = (packet / "originals").resolve()
    candidate = (originals / clean).resolve()
    try:
        normalized = candidate.relative_to(originals)
    except ValueError:
        raise SystemExit(f"Original path escapes packet: {relative_path}")
    if not candidate.is_file():
        raise SystemExit(f"Original not found: {normalized.as_posix()}")
    return normalized.as_posix(), candidate


def add_files(packet: Path, cohort_query: str, paths: list[str], note: str = "", event: str = "files_added") -> tuple[dict, list[str]]:
    cohort = read_cohort(packet, cohort_query)
    validated = [validate_original_path(packet, value)[0] for value in paths]
    existing = {item["relative_path"] for item in cohort.get("files", [])}
    now = utc_now()
    added = []
    for relative_path in validated:
        if relative_path not in existing:
            cohort["files"].append({"relative_path": relative_path, "added_at": now, "note": note})
            existing.add(relative_path)
            added.append(relative_path)
    if added:
        cohort["history"].append(
            {"event": event, "timestamp": now, "count": len(added), "files": added, "note": note}
        )
        write_cohort(packet, cohort)
    return cohort, added


def remove_files(packet: Path, cohort_query: str, paths: list[str]) -> tuple[dict, list[str]]:
    cohort = read_cohort(packet, cohort_query)
    requested = {Path(value).as_posix() for value in paths}
    removed = [item["relative_path"] for item in cohort.get("files", []) if item["relative_path"] in requested]
    if removed:
        cohort["files"] = [item for item in cohort["files"] if item["relative_path"] not in requested]
        cohort["history"].append(
            {"event": "files_removed", "timestamp": utc_now(), "count": len(removed), "files": removed}
        )
        write_cohort(packet, cohort)
    return cohort, removed


def range_files(packet: Path, folder: str, start: str, end: str) -> list[str]:
    folder_path = Path(folder)
    if folder_path.is_absolute() or ".." in folder_path.parts:
        raise SystemExit(f"Invalid originals folder: {folder}")
    source = packet / "originals" / folder_path
    if not source.is_dir():
        raise SystemExit(f"Originals folder not found: {folder}")
    files = sorted((item.name for item in source.iterdir() if item.is_file()), key=natural_key)
    if start not in files:
        raise SystemExit(f"Range start not found: {start}")
    if end not in files:
        raise SystemExit(f"Range end not found: {end}")
    start_index = files.index(start)
    end_index = files.index(end)
    if start_index > end_index:
        raise SystemExit(f"Reversed filename range: {start} comes after {end}")
    return [(folder_path / name).as_posix() for name in files[start_index : end_index + 1]]


def update_cohort(
    packet: Path,
    cohort_query: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
    subject: Optional[str] = None,
    parent: Optional[str] = None,
    status: Optional[str] = None,
    clear_parent: bool = False,
    clear_subject: bool = False,
) -> dict:
    if status is not None and status not in VALID_COHORT_STATUSES:
        raise SystemExit(f"Invalid cohort status: {status}")
    cohort = read_cohort(packet, cohort_query)
    changes = {}
    for key, value in (("name", name), ("description", description), ("status", status)):
        if value is not None and cohort.get(key) != value:
            changes[key] = {"from": cohort.get(key), "to": value}
            cohort[key] = value
    if subject is not None:
        found = find_subject(read_subjects(packet), subject)
        if found is None:
            raise SystemExit(f"Subject not found: {subject}")
        value = found["subject_id"]
        if cohort.get("subject_id") != value:
            changes["subject_id"] = {"from": cohort.get("subject_id"), "to": value}
            cohort["subject_id"] = value
    elif clear_subject and cohort.get("subject_id") is not None:
        changes["subject_id"] = {"from": cohort.get("subject_id"), "to": None}
        cohort["subject_id"] = None
    if parent is not None:
        value = read_cohort(packet, parent)["cohort_id"]
        if value == cohort["cohort_id"]:
            raise SystemExit("A cohort cannot be its own parent.")
        if cohort.get("parent_cohort_id") != value:
            changes["parent_cohort_id"] = {"from": cohort.get("parent_cohort_id"), "to": value}
            cohort["parent_cohort_id"] = value
    elif clear_parent and cohort.get("parent_cohort_id") is not None:
        changes["parent_cohort_id"] = {"from": cohort.get("parent_cohort_id"), "to": None}
        cohort["parent_cohort_id"] = None
    if changes:
        cohort["history"].append({"event": "metadata_updated", "timestamp": utc_now(), "changes": changes})
        write_cohort(packet, cohort)
    return cohort


def preview_for(packet: Path, relative_path: str) -> Path:
    rel = Path(relative_path)
    previews = packet / "previews"
    candidates = [
        previews / rel,
        previews / rel.with_suffix(".jpg"),
        previews / rel.with_suffix(".JPG"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return packet / "originals" / rel


def contact_sheet_font() -> Optional[Path]:
    configured = os.environ.get(CONTACT_SHEET_FONT_ENV)
    if configured:
        path = Path(configured).expanduser()
        return path.resolve() if path.is_file() else None
    for candidate in CONTACT_SHEET_FONT_CANDIDATES:
        if candidate.is_file():
            return candidate.resolve()
    return None


def contact_sheet_command(
    magick: str,
    source_list: Path,
    output: Path,
    columns: int,
    font: Optional[Path] = None,
) -> list[str]:
    command = [
        magick,
        "montage",
        f"@{source_list}",
        "-auto-orient",
        "-thumbnail",
        "240x240",
        "-background",
        "white",
        "-gravity",
        "center",
        "-extent",
        "240x240",
    ]
    if font is not None:
        command.extend(["-font", str(font), "-pointsize", "14", "-label", "%t"])
    else:
        command.append("+label")
    command.extend(
        [
            "-tile",
            f"{max(1, columns)}x",
            "-geometry",
            "+8+8",
            str(output),
        ]
    )
    return command


def build_contact_sheet(packet: Path, cohort_query: str, limit: Optional[int] = None, columns: int = 5) -> dict:
    cohort = read_cohort(packet, cohort_query)
    files = cohort.get("files", [])
    if limit is not None:
        files = files[:limit]
    if not files:
        raise SystemExit("Cohort has no files.")
    magick = shutil.which("magick")
    if not magick:
        raise SystemExit("ImageMagick 'magick' command not found.")
    folder = cohort_dir(packet, cohort["cohort_id"])
    sources = [preview_for(packet, item["relative_path"]) for item in files]
    missing = [str(path) for path in sources if not path.is_file()]
    if missing:
        raise SystemExit(f"Contact-sheet source missing: {missing[0]}")
    source_list = folder / "contact_sheet_sources.txt"
    source_list.write_text("\n".join(str(path) for path in sources) + "\n", encoding="utf-8")
    files_list = folder / "contact_sheet_files.txt"
    files_list.write_text("\n".join(item["relative_path"] for item in files) + "\n", encoding="utf-8")
    output = folder / "contact_sheet.jpg"
    font = contact_sheet_font()
    command = contact_sheet_command(magick, source_list, output, columns, font=font)
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    used_labels = font is not None
    fell_back_to_unlabeled = False
    if used_labels and not output.is_file():
        fell_back_to_unlabeled = True
        command = contact_sheet_command(magick, source_list, output, columns, font=None)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    if not output.is_file():
        detail = result.stderr.strip() or result.stdout.strip() or "unknown ImageMagick failure"
        raise SystemExit(f"Failed to generate contact sheet: {detail}")
    cohort["history"].append(
        {
            "event": "contact_sheet_generated",
            "timestamp": utc_now(),
            "file_count": len(files),
            "path": str(output),
            "labeled": used_labels and not fell_back_to_unlabeled,
            "font": str(font) if used_labels and not fell_back_to_unlabeled else "",
            "fell_back_to_unlabeled": fell_back_to_unlabeled,
        }
    )
    write_cohort(packet, cohort)
    return {
        "path": str(output),
        "files_path": str(files_list),
        "file_count": len(files),
        "labeled": used_labels and not fell_back_to_unlabeled,
        "font": str(font) if used_labels and not fell_back_to_unlabeled else "",
        "fell_back_to_unlabeled": fell_back_to_unlabeled,
    }


def checksum_map(packet: Path) -> dict[str, str]:
    result = {}
    path = packet / "checksums.sha256"
    if not path.exists():
        return result
    for line in path.read_text(errors="replace").splitlines():
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        checksum, relative_path = parts
        relative_path = relative_path.strip().lstrip("*")
        if relative_path.startswith("./"):
            relative_path = relative_path[2:]
        result[relative_path] = checksum
    return result


def export_cohort(packet: Path, cohort_query: str, destination: Optional[str] = None) -> dict:
    cohort = read_cohort(packet, cohort_query)
    if destination:
        output = Path(destination).expanduser()
    else:
        root = Path(os.environ.get("LAIA_PHOTO_COHORT_EXPORT_ROOT", DEFAULT_EXPORT_ROOT)).expanduser()
        output = root / packet_id(packet) / cohort["cohort_id"]
    output.mkdir(parents=True, exist_ok=True)
    files_root = output / "files"
    checksums = checksum_map(packet)
    exported = []
    for item in cohort.get("files", []):
        relative_path, source = validate_original_path(packet, item["relative_path"])
        target = files_root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        exported.append(
            {
                "relative_path": relative_path,
                "exported_path": str(target.relative_to(output)),
                "sha256": checksums.get(relative_path, ""),
            }
        )
    now = utc_now()
    manifest = {
        "export_type": "laia.photo_cohort",
        "export_version": "0.1",
        "exported_at": now,
        "source_packet_id": packet_id(packet),
        "source_packet_path": str(packet),
        "cohort": {key: value for key, value in cohort.items() if key not in {"files", "history"}},
        "file_count": len(exported),
        "files": exported,
    }
    manifest_path = output / "cohort_manifest.json"
    _write_json(manifest_path, manifest)
    report_path = output / "cohort_report.md"
    report_path.write_text(
        "\n".join(
            [
                f"# Photo Cohort Export: {cohort['name']}",
                "",
                f"- Source packet: {packet_id(packet)}",
                f"- Cohort ID: {cohort['cohort_id']}",
                f"- Status: {cohort.get('status', '')}",
                f"- Subject: {cohort.get('subject_id') or 'none'}",
                f"- Parent: {cohort.get('parent_cohort_id') or 'none'}",
                f"- File count: {len(exported)}",
                f"- Exported at: {now}",
                "",
                "## Files",
                "",
                *[
                    f"- `{item['relative_path']}`"
                    + (f" — `{item['sha256']}`" if item.get("sha256") else "")
                    for item in exported
                ],
                "",
            ]
        ),
        encoding="utf-8",
    )
    cohort["history"].append(
        {"event": "export_created", "timestamp": now, "destination": str(output), "file_count": len(exported)}
    )
    write_cohort(packet, cohort)
    return {
        "destination": str(output),
        "manifest": str(manifest_path),
        "report": str(report_path),
        "file_count": len(exported),
    }


def latest_cohort_export_path(packet: Path, cohort: dict) -> str:
    for event in reversed(cohort.get("history", [])):
        if event.get("event") == "export_created" and event.get("destination"):
            return str(Path(event["destination"]).expanduser())
    root = Path(os.environ.get("LAIA_PHOTO_COHORT_EXPORT_ROOT", DEFAULT_EXPORT_ROOT)).expanduser()
    candidate = root / packet_id(packet) / cohort["cohort_id"]
    return str(candidate) if candidate.exists() else ""


def append_cohort_history_event(packet: Path, cohort: dict, event: dict) -> dict:
    cohort.setdefault("history", []).append(event)
    return write_cohort(packet, cohort)


def photo_registry_metadata(packet: Path) -> dict:
    subjects = read_subjects(packet).get("subjects", []) if subjects_path(packet).exists() else []
    index = read_cohort_index(packet).get("cohorts", []) if cohorts_index_path(packet).exists() else []
    subject_names = [str(item.get("name", "")) for item in subjects if item.get("name")]
    cohort_summaries = []
    for entry in index:
        project_links = read_cohort_project_links(packet, str(entry.get("cohort_id", ""))).get("links", [])
        cohort_summaries.append(
            {
                "cohort_id": str(entry.get("cohort_id", "")),
                "name": str(entry.get("name", "")),
                "status": str(entry.get("status", "")),
                "file_count": int(entry.get("file_count", 0) or 0),
                "project_links": [
                    {
                        "project_id": str(link.get("project_id", "")),
                        "project_name": str(link.get("project_name", "")),
                        "linked_at": str(link.get("linked_at", "")),
                    }
                    for link in project_links
                    if link.get("project_id")
                ],
            }
        )
    return {
        "photo_subject_count": len(subject_names),
        "photo_subjects": subject_names,
        "photo_cohort_count": len(cohort_summaries),
        "photo_cohorts": cohort_summaries,
    }
