import csv
import json
import os
import platform
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

try:
    from packets.standard import (
        STANDARD_REQUIRED_ITEMS,
        count_checksum_entries,
        checksum_path,
        read_packet_manifest,
        read_review_sidecar,
        selects_path,
        validate_required_items,
    )
except ModuleNotFoundError:
    from core.packets.standard import (
        STANDARD_REQUIRED_ITEMS,
        count_checksum_entries,
        checksum_path,
        read_packet_manifest,
        read_review_sidecar,
        selects_path,
        validate_required_items,
    )


DEFAULT_PHOTO_PACKET_ROOT = Path("/Volumes/Public/LAIA/packets/photo_ingest")
DEFAULT_PHOTO_CATALOG_ROOT = Path("/Volumes/Public/LAIA/catalogs/photo_ingest")
DEFAULT_PAPER_PACKET_ROOT = Path("~/LAIA/Inbox/Ingest/Scans").expanduser()
DEFAULT_PACKET_EXPORT_ROOT = Path("~/LAIA/exports/packets").expanduser()
DEFAULT_PACKET_PROJECT_ROOT = Path("~/LAIA/projects").expanduser()
DEFAULT_PACKET_PROMOTION_ROOT = Path("~/LAIA/promoted").expanduser()
DEFAULT_REGISTRY_DB_NAME = "packet_registry.db"
PAPER_REQUIRED_ITEMS = (
    "originals",
    "metadata",
    "logs",
    "review",
    "checksums.sha256",
    "packet_manifest.json",
    "ingest_report.md",
)
CSV_EXPORT_COLUMNS = (
    "job_id",
    "packet_type",
    "packet_version",
    "packet_path",
    "source",
    "asset_count",
    "packet_size",
    "created_at",
    "review_status",
    "select_count",
    "verification_status",
    "missing_required",
)
READY_REVIEW_STATUSES = {"reviewed", "approved", "finalized", "exported", "published"}
EARLY_STATUSES = {"new", "in_review", "classified", "extracted", "summarized"}
DONE_STATUSES = {"reviewed", "approved", "finalized", "exported", "published"}
SUPPORTED_DESTINATION_TYPES = {"archive", "project", "export", "catalog", "review", "hold"}
SUPPORTED_OUTPUT_REVIEW_STATUSES = {"new", "reviewed", "needs_work"}
SUPPORTED_PROMOTION_TYPES = {"project", "archive", "catalog", "publication", "hold"}


@dataclass(frozen=True)
class PacketRoot:
    name: str
    path: Path
    depth: int = 2


@dataclass(frozen=True)
class RegistryConfig:
    db_path: Path
    roots: Sequence[PacketRoot]


def config_from_env() -> RegistryConfig:
    photo_packet_root = Path(os.environ.get("LAIA_PHOTO_PACKET_ROOT", DEFAULT_PHOTO_PACKET_ROOT)).expanduser()
    paper_packet_root = Path(os.environ.get("LAIA_PAPER_PACKET_ROOT", DEFAULT_PAPER_PACKET_ROOT)).expanduser()
    photo_catalog_root = Path(os.environ.get("LAIA_PHOTO_CATALOG_ROOT", DEFAULT_PHOTO_CATALOG_ROOT)).expanduser()
    db_path = Path(
        os.environ.get("LAIA_PACKET_REGISTRY_DB", photo_catalog_root / DEFAULT_REGISTRY_DB_NAME)
    ).expanduser()

    roots_env = os.environ.get("LAIA_PACKET_ROOTS", "").strip()
    if roots_env:
        roots = []
        for index, item in enumerate(roots_env.split(os.pathsep), start=1):
            item = item.strip()
            if item:
                roots.append(PacketRoot(name=f"root{index}", path=Path(item).expanduser()))
    else:
        roots = [PacketRoot(name="photo_ingest", path=photo_packet_root)]
        if os.environ.get("LAIA_PAPER_PACKET_ROOT") or paper_packet_root.exists():
            roots.append(PacketRoot(name="paper_ingest", path=paper_packet_root))

    return RegistryConfig(db_path=db_path, roots=tuple(roots))


def registry_schema_sql() -> str:
    return """
CREATE TABLE IF NOT EXISTS packets (
    packet_path TEXT PRIMARY KEY,
    root_name TEXT,
    job_id TEXT,
    packet_type TEXT,
    packet_version TEXT,
    source TEXT,
    asset_count INTEGER,
    packet_size TEXT,
    created_at TEXT,
    review_status TEXT,
    select_count INTEGER,
    verification_status TEXT,
    missing_required_items TEXT,
    workflow_status TEXT,
    classification_status TEXT,
    approval_status TEXT,
    final_status TEXT,
    failure_status TEXT,
    route_status TEXT,
    route_destination_type TEXT,
    route_destination TEXT,
    route_updated_at TEXT,
    route_execution_result TEXT,
    route_execution_output_path TEXT,
    route_executed_at TEXT,
    output_review_status TEXT,
    output_review_note TEXT,
    output_reviewed_at TEXT,
    promotion_status TEXT,
    promotion_destination_type TEXT,
    promotion_destination TEXT,
    promotion_result TEXT,
    promotion_output_path TEXT,
    promoted_at TEXT,
    scanned_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_packets_job_id ON packets(job_id);
CREATE INDEX IF NOT EXISTS idx_packets_packet_type ON packets(packet_type);
CREATE INDEX IF NOT EXISTS idx_packets_created_at ON packets(created_at);
CREATE INDEX IF NOT EXISTS idx_packets_verification_status ON packets(verification_status);
"""


def connect_registry(db_path: Path):
    db_path = Path(db_path).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(registry_schema_sql())
    for sql in [
        "ALTER TABLE packets ADD COLUMN workflow_status TEXT;",
        "ALTER TABLE packets ADD COLUMN classification_status TEXT;",
        "ALTER TABLE packets ADD COLUMN approval_status TEXT;",
        "ALTER TABLE packets ADD COLUMN final_status TEXT;",
        "ALTER TABLE packets ADD COLUMN failure_status TEXT;",
        "ALTER TABLE packets ADD COLUMN route_status TEXT;",
        "ALTER TABLE packets ADD COLUMN route_destination_type TEXT;",
        "ALTER TABLE packets ADD COLUMN route_destination TEXT;",
        "ALTER TABLE packets ADD COLUMN route_updated_at TEXT;",
        "ALTER TABLE packets ADD COLUMN route_execution_result TEXT;",
        "ALTER TABLE packets ADD COLUMN route_execution_output_path TEXT;",
        "ALTER TABLE packets ADD COLUMN route_executed_at TEXT;",
        "ALTER TABLE packets ADD COLUMN output_review_status TEXT;",
        "ALTER TABLE packets ADD COLUMN output_review_note TEXT;",
        "ALTER TABLE packets ADD COLUMN output_reviewed_at TEXT;",
        "ALTER TABLE packets ADD COLUMN promotion_status TEXT;",
        "ALTER TABLE packets ADD COLUMN promotion_destination_type TEXT;",
        "ALTER TABLE packets ADD COLUMN promotion_destination TEXT;",
        "ALTER TABLE packets ADD COLUMN promotion_result TEXT;",
        "ALTER TABLE packets ADD COLUMN promotion_output_path TEXT;",
        "ALTER TABLE packets ADD COLUMN promoted_at TEXT;",
    ]:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass
    return conn


def iter_packet_dirs(root: PacketRoot):
    if not root.path.exists():
        return
    candidates = []
    pattern = "/".join(["*"] * root.depth)
    candidates.extend(p for p in root.path.glob(pattern) if p.is_dir())
    if root.name == "paper_ingest":
        candidates.extend(p for p in root.path.glob("*") if p.is_dir())

    seen = set()
    for packet in sorted(candidates):
        if packet in seen:
            continue
        seen.add(packet)
        if packet.name.isdigit() and len(packet.name) == 4 and not (packet / "packet_manifest.json").exists():
            continue
        yield packet


def count_selects(packet: Path) -> int:
    path = selects_path(packet)
    if not path.exists():
        return 0
    count = 0
    for line in path.read_text(errors="replace").splitlines():
        text = line.strip()
        if text and not text.startswith("#"):
            count += 1
    return count


def manifest_asset_count(manifest: dict) -> Optional[int]:
    for key in ("asset_count", "photo_count", "file_count", "page_count"):
        value = manifest.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    return None


def packet_id_from_manifest(packet: Path, manifest: dict) -> str:
    return str(manifest.get("job_id") or manifest.get("packet_id") or packet.name)


def paper_workflow_state(packet: Path) -> dict:
    path = packet / "metadata" / "paper_workflow_state.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def routing_path(packet: Path) -> Path:
    return Path(packet) / "review" / "routing.json"


def read_routing(packet: Path) -> dict:
    path = routing_path(packet)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_routing(packet: Path, route: dict) -> Path:
    path = routing_path(packet)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(route, indent=2) + "\n", encoding="utf-8")
    return path


def route_packet(packet: Path, destination_type: str, destination: str = "", note: str = "") -> dict:
    if destination_type not in SUPPORTED_DESTINATION_TYPES:
        raise ValueError(f"Invalid destination type: {destination_type}")
    packet = Path(packet).expanduser()
    now = utc_now()
    current = read_routing(packet)
    history = current.get("history") if isinstance(current.get("history"), list) else []
    event = {
        "route_status": "queued",
        "destination_type": destination_type,
        "destination": destination,
        "note": note,
        "created_at": now,
    }
    history.append(event)
    route = {
        "route_status": "queued",
        "destination_type": destination_type,
        "destination": destination,
        "note": note,
        "created_at": current.get("created_at") or now,
        "updated_at": now,
        "history": history,
    }
    write_routing(packet, route)
    return route


def clear_packet_route(packet: Path, note: str = "") -> dict:
    packet = Path(packet).expanduser()
    now = utc_now()
    current = read_routing(packet)
    history = current.get("history") if isinstance(current.get("history"), list) else []
    event = {
        "route_status": "cleared",
        "destination_type": "",
        "destination": "",
        "note": note,
        "created_at": now,
    }
    history.append(event)
    route = {
        "route_status": "cleared",
        "destination_type": "",
        "destination": "",
        "note": note,
        "created_at": current.get("created_at") or now,
        "updated_at": now,
        "history": history,
    }
    write_routing(packet, route)
    return route


def sanitize_folder_name(value: str, fallback: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or fallback


def route_output_root(destination_type: str) -> Path:
    if destination_type == "export":
        return Path(os.environ.get("LAIA_PACKET_EXPORT_ROOT", str(DEFAULT_PACKET_EXPORT_ROOT))).expanduser()
    if destination_type == "project":
        return Path(os.environ.get("LAIA_PACKET_PROJECT_ROOT", str(DEFAULT_PACKET_PROJECT_ROOT))).expanduser()
    raise ValueError(f"No output root for route type: {destination_type}")


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def read_selects_lines(packet: Path) -> List[str]:
    path = selects_path(packet)
    if not path.exists():
        return []
    rows = []
    seen = set()
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if text not in seen:
            seen.add(text)
            rows.append(text)
    return rows


def route_ready_check(row, route: dict) -> Optional[str]:
    destination_type = str(route.get("destination_type", "") or "")
    if destination_type in {"hold", "review"}:
        return None
    if row_value(row, "verification_status", "") != "ok":
        return f"Packet is not verified: {row_value(row, 'verification_status', '')}"
    if row_value(row, "missing_required_items", ""):
        return f"Packet has missing required items: {row_value(row, 'missing_required_items', '')}"
    if not is_ready(row):
        return f"Packet is not ready: review_status={row_value(row, 'review_status', '')}"
    return None


def route_history_summary(route: dict) -> dict:
    history = route.get("history") if isinstance(route.get("history"), list) else []
    return {"count": len(history), "last_status": history[-1].get("route_status", "") if history else ""}


def handoff_data(row, packet: Path, route: dict) -> dict:
    return {
        "job_id": row_value(row, "job_id", packet.name),
        "packet_path": str(packet),
        "packet_type": row_value(row, "packet_type", ""),
        "review_status": row_value(row, "review_status", ""),
        "workflow_status": row_value(row, "workflow_status", ""),
        "asset_count": int(row_value(row, "asset_count", 0) or 0),
        "route_status": route.get("route_status", ""),
        "destination_type": route.get("destination_type", ""),
        "destination": route.get("destination", ""),
        "route_note": route.get("note", ""),
        "route_history": route_history_summary(route),
    }


def write_handoff_report(path: Path, data: dict) -> None:
    lines = [
        "# LAIA Packet Handoff",
        "",
        f"Packet: {data.get('job_id', '')}",
        f"Type: {data.get('packet_type', '')}",
        f"Path: {data.get('packet_path', '')}",
        f"Review: {data.get('review_status', '')}",
        f"Workflow: {data.get('workflow_status', '')}",
        f"Assets: {data.get('asset_count', 0)}",
        f"Destination: {data.get('destination_type', '')} {data.get('destination', '')}".rstrip(),
        f"Note: {data.get('route_note', '')}",
        f"History Count: {data.get('route_history', {}).get('count', 0)}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def execute_export_route(row, packet: Path, route: dict, dry_run: bool = False) -> dict:
    folder_name = sanitize_folder_name(route.get("destination", ""), row_value(row, "job_id", packet.name))
    output = route_output_root("export") / folder_name
    selects = read_selects_lines(packet) if row_value(row, "packet_type", "") == "laia.photo_ingest" else []
    copied = []
    missing = []
    if dry_run:
        return {
            "result": "dry_run",
            "output_path": str(output),
            "note": f"Would export {len(selects)} selected files" if selects else "Would create packet handoff report",
            "copied": copied,
            "missing": missing,
        }
    output.mkdir(parents=True, exist_ok=True)
    originals = packet / "originals"
    for rel in selects:
        src = originals / rel
        if not src.exists() or not src.is_file():
            missing.append(rel)
            continue
        dest = unique_path(output / Path(rel).name)
        shutil.copy2(src, dest)
        copied.append({"source": rel, "exported": dest.name})
    data = handoff_data(row, packet, route)
    data.update({"selected_count": len(selects), "copied_count": len(copied), "missing_selects": missing})
    write_handoff_report(output / "packet_handoff.md", data)
    manifest = dict(data)
    manifest["exported_files"] = copied
    (output / "export_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    if missing and copied:
        result = "partial"
    elif missing and not copied:
        result = "missing"
    else:
        result = "exported" if copied else "handoff_created"
    return {
        "result": result,
        "output_path": str(output),
        "note": f"Copied {len(copied)} selected files" if copied else "Created packet handoff report",
        "copied": copied,
        "missing": missing,
    }


def execute_project_route(row, packet: Path, route: dict, dry_run: bool = False) -> dict:
    folder_name = sanitize_folder_name(route.get("destination", ""), row_value(row, "job_id", packet.name))
    output = route_output_root("project") / folder_name
    if dry_run:
        return {"result": "dry_run", "output_path": str(output), "note": "Would create project packet handoff"}
    output.mkdir(parents=True, exist_ok=True)
    data = handoff_data(row, packet, route)
    write_handoff_report(output / "packet_handoff.md", data)
    (output / "packet_handoff.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return {"result": "handoff_created", "output_path": str(output), "note": "Created project packet handoff"}


def execute_nonmoving_route(route: dict, dry_run: bool = False) -> dict:
    destination_type = str(route.get("destination_type", "") or "")
    notes = {
        "archive": "Archive route acknowledged; packet is archive-ready.",
        "catalog": "Catalog route acknowledged; registry can be refreshed.",
        "review": "Packet returned to review queue.",
        "hold": "Packet placed on hold.",
    }
    note = notes.get(destination_type, f"Route acknowledged: {destination_type}")
    return {"result": "dry_run" if dry_run else "acknowledged", "output_path": "", "note": f"Would {note}" if dry_run else note}


def mark_route_executed(packet: Path, route: dict, result: dict) -> dict:
    now = utc_now()
    history = route.get("history") if isinstance(route.get("history"), list) else []
    event = {
        "route_status": "executed",
        "destination_type": route.get("destination_type", ""),
        "destination": route.get("destination", ""),
        "note": route.get("note", ""),
        "executed_at": now,
        "execution_result": result.get("result", ""),
    }
    history.append(event)
    updated = dict(route)
    updated.update(
        {
            "route_status": "executed",
            "updated_at": now,
            "executed_at": now,
            "execution_result": result.get("result", ""),
            "execution_output_path": result.get("output_path", ""),
            "last_execution_note": result.get("note", ""),
            "history": history,
        }
    )
    write_routing(packet, updated)
    return updated


def execute_packet_route(row, packet: Path, dry_run: bool = False) -> dict:
    packet = Path(packet)
    route = read_routing(packet)
    if not route:
        raise ValueError("No route assigned.")
    if route.get("route_status") != "queued":
        raise ValueError(f"Route is not queued: {route.get('route_status', '')}")
    destination_type = str(route.get("destination_type", "") or "")
    if destination_type not in SUPPORTED_DESTINATION_TYPES:
        raise ValueError(f"Invalid destination type: {destination_type}")
    ready_error = route_ready_check(row, route)
    if ready_error:
        raise ValueError(ready_error)
    if destination_type == "export":
        result = execute_export_route(row, packet, route, dry_run=dry_run)
    elif destination_type == "project":
        result = execute_project_route(row, packet, route, dry_run=dry_run)
    else:
        result = execute_nonmoving_route(route, dry_run=dry_run)
    if not dry_run:
        mark_route_executed(packet, route, result)
    return result


def output_path_from_route(route: dict) -> Path:
    return Path(str(route.get("execution_output_path", "") or "")).expanduser()


def has_executed_output(route: dict) -> bool:
    return route.get("route_status") == "executed" and bool(route.get("execution_output_path"))


def output_file_rows(output_path: Path):
    output_path = Path(output_path)
    if not output_path.exists() or not output_path.is_dir():
        return []
    rows = []
    for file in sorted(p for p in output_path.rglob("*") if p.is_file()):
        rows.append((str(file.relative_to(output_path)), file.stat().st_size))
    return rows


def mark_output_reviewed(packet: Path, status: str = "reviewed", note: str = "") -> dict:
    if status not in SUPPORTED_OUTPUT_REVIEW_STATUSES:
        raise ValueError(f"Invalid output review status: {status}")
    packet = Path(packet).expanduser()
    route = read_routing(packet)
    if not route or not has_executed_output(route):
        raise ValueError("No executed output found.")
    now = utc_now()
    history = route.get("history") if isinstance(route.get("history"), list) else []
    history.append(
        {
            "route_status": "output_reviewed",
            "output_review_status": status,
            "note": note,
            "reviewed_at": now,
        }
    )
    route.update(
        {
            "output_review_status": status,
            "output_review_note": note,
            "output_reviewed_at": now,
            "updated_at": now,
            "history": history,
        }
    )
    write_routing(packet, route)
    return route


def promotion_root() -> Path:
    return Path(os.environ.get("LAIA_PACKET_PROMOTION_ROOT", str(DEFAULT_PACKET_PROMOTION_ROOT))).expanduser()


def promotion_output_root(destination_type: str, destination: str, job_id: str) -> Optional[Path]:
    if destination_type == "project":
        return promotion_root() / "projects" / sanitize_folder_name(destination, job_id)
    if destination_type == "publication":
        return promotion_root() / "publication" / sanitize_folder_name(destination, job_id)
    return None


def copy_output_tree(source: Path, destination: Path) -> int:
    source = Path(source)
    destination = Path(destination)
    count = 0
    for file in sorted(p for p in source.rglob("*") if p.is_file()):
        rel = file.relative_to(source)
        target = unique_path(destination / rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file, target)
        count += 1
    return count


def write_promotion_report(path: Path, data: dict) -> None:
    lines = [
        "# LAIA Packet Promotion",
        "",
        f"Packet: {data.get('packet_id', '')}",
        f"Type: {data.get('packet_type', '')}",
        f"Packet Path: {data.get('packet_path', '')}",
        f"Source Output: {data.get('source_output_path', '')}",
        f"Destination: {data.get('promotion_destination_type', '')} {data.get('promotion_destination', '')}".rstrip(),
        f"Result: {data.get('promotion_result', '')}",
        f"Promoted At: {data.get('promoted_at', '')}",
        f"Files: {data.get('file_count', 0)}",
        f"Route Execution Result: {data.get('route_execution_result', '')}",
        f"Output Review: {data.get('output_review_status', '')}",
        f"Output Review Note: {data.get('output_review_note', '')}",
        f"Promotion Note: {data.get('promotion_note', '')}",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def promotion_record(row, packet: Path, route: dict, destination_type: str, destination: str, note: str, result: dict, promoted_at: str) -> dict:
    return {
        "packet_id": row_value(row, "job_id", packet.name),
        "packet_type": row_value(row, "packet_type", ""),
        "packet_path": str(packet),
        "source_output_path": route.get("execution_output_path", ""),
        "promotion_destination_type": destination_type,
        "promotion_destination": destination,
        "promotion_note": note,
        "promoted_at": promoted_at,
        "file_count": result.get("file_count", 0),
        "route_execution_result": route.get("execution_result", ""),
        "output_review_status": route.get("output_review_status", ""),
        "output_review_note": route.get("output_review_note", ""),
        "promotion_result": result.get("result", ""),
        "promotion_output_path": result.get("output_path", ""),
    }


def validate_promotion(route: dict, destination_type: str) -> None:
    if destination_type not in SUPPORTED_PROMOTION_TYPES:
        raise ValueError(f"Invalid promotion destination type: {destination_type}")
    if route.get("route_status") != "executed":
        raise ValueError("Route must be executed before promotion.")
    status = route.get("output_review_status", "")
    if status in ("", "new"):
        raise ValueError("Output must be reviewed before promotion.")
    if status == "needs_work":
        raise ValueError("Output is marked needs_work and cannot be promoted.")
    if status != "reviewed":
        raise ValueError(f"Output review status is not promotable: {status}")
    if destination_type in {"project", "publication"}:
        output_path = output_path_from_route(route)
        if not output_path.exists() or not output_path.is_dir():
            raise ValueError(f"Execution output path not found: {output_path}")


def promote_packet_output(row, packet: Path, destination_type: str, destination: str = "", note: str = "", dry_run: bool = False) -> dict:
    packet = Path(packet).expanduser()
    route = read_routing(packet)
    validate_promotion(route, destination_type)
    job_id = row_value(row, "job_id", packet.name)
    output = promotion_output_root(destination_type, destination, job_id)
    if dry_run:
        result_name = "dry_run"
        return {
            "status": "dry_run",
            "result": result_name,
            "output_path": str(output or ""),
            "file_count": len(output_file_rows(output_path_from_route(route))) if output else 0,
            "note": "Would promote reviewed route output",
        }
    now = utc_now()
    if destination_type in {"project", "publication"}:
        output.mkdir(parents=True, exist_ok=True)
        file_count = copy_output_tree(output_path_from_route(route), output)
        result = {"status": "promoted", "result": "promoted", "output_path": str(output), "file_count": file_count}
        record = promotion_record(row, packet, route, destination_type, destination, note, result, now)
        (output / "promotion_manifest.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        write_promotion_report(output / "promotion_report.md", record)
    elif destination_type == "archive":
        result = {"status": "promoted", "result": "archive_ready", "output_path": "", "file_count": 0}
    elif destination_type == "catalog":
        result = {"status": "promoted", "result": "catalog_ready", "output_path": "", "file_count": 0}
    elif destination_type == "hold":
        result = {"status": "held", "result": "held", "output_path": "", "file_count": 0}
    else:
        raise ValueError(f"Invalid promotion destination type: {destination_type}")
    history = route.get("history") if isinstance(route.get("history"), list) else []
    history.append(
        {
            "route_status": "promoted",
            "promotion_status": result["status"],
            "promotion_destination_type": destination_type,
            "promotion_destination": destination,
            "promotion_result": result["result"],
            "promotion_output_path": result["output_path"],
            "note": note,
            "promoted_at": now,
        }
    )
    route.update(
        {
            "promotion_status": result["status"],
            "promotion_destination_type": destination_type,
            "promotion_destination": destination,
            "promotion_note": note,
            "promotion_result": result["result"],
            "promotion_output_path": result["output_path"],
            "promoted_at": now,
            "updated_at": now,
            "history": history,
        }
    )
    write_routing(packet, route)
    result["promoted_at"] = now
    return result


def registry_record(root_name: str, packet: Path, required_items: Optional[Iterable[str]] = None) -> Optional[dict]:
    try:
        manifest = read_packet_manifest(packet)
    except (FileNotFoundError, ValueError, json.JSONDecodeError):
        return None

    packet_type = str(manifest.get("packet_type", ""))
    if required_items is None and packet_type == "laia.paper_ingest":
        required_items = PAPER_REQUIRED_ITEMS
    validation = validate_required_items(packet, required_items or STANDARD_REQUIRED_ITEMS)
    try:
        review = read_review_sidecar(packet)
    except Exception:
        review = {"review_status": "unknown"}
    workflow_state = paper_workflow_state(packet) if packet_type == "laia.paper_ingest" else {}
    route = read_routing(packet)

    missing = list(validation.missing)
    return {
        "packet_path": str(packet),
        "root_name": root_name,
        "job_id": packet_id_from_manifest(packet, manifest),
        "packet_type": str(manifest.get("packet_type", "")),
        "packet_version": str(manifest.get("packet_version", "")),
        "source": str(manifest.get("source", "")),
        "asset_count": manifest_asset_count(manifest),
        "packet_size": str(manifest.get("packet_size", "")),
        "created_at": str(manifest.get("created_at", "")),
        "review_status": str(workflow_state.get("review_status") or review.get("review_status", "new")),
        "select_count": count_selects(packet),
        "verification_status": "ok" if not missing else "missing_required_items",
        "missing_required_items": ",".join(missing),
        "workflow_status": str(workflow_state.get("workflow_status", "")),
        "classification_status": str(workflow_state.get("classification_status", "")),
        "approval_status": str(workflow_state.get("approval_status", "")),
        "final_status": str(workflow_state.get("final_status", "")),
        "failure_status": str(workflow_state.get("failure_status", "")),
        "route_status": str(route.get("route_status", "")),
        "route_destination_type": str(route.get("destination_type", "")),
        "route_destination": str(route.get("destination", "")),
        "route_updated_at": str(route.get("updated_at", "")),
        "route_execution_result": str(route.get("execution_result", "")),
        "route_execution_output_path": str(route.get("execution_output_path", "")),
        "route_executed_at": str(route.get("executed_at", "")),
        "output_review_status": str(route.get("output_review_status", "")),
        "output_review_note": str(route.get("output_review_note", "")),
        "output_reviewed_at": str(route.get("output_reviewed_at", "")),
        "promotion_status": str(route.get("promotion_status", "")),
        "promotion_destination_type": str(route.get("promotion_destination_type", "")),
        "promotion_destination": str(route.get("promotion_destination", "")),
        "promotion_result": str(route.get("promotion_result", "")),
        "promotion_output_path": str(route.get("promotion_output_path", "")),
        "promoted_at": str(route.get("promoted_at", "")),
    }


def upsert_registry_record(conn, record: dict) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO packets
        (
            packet_path, root_name, job_id, packet_type, packet_version, source,
            asset_count, packet_size, created_at, review_status, select_count,
            verification_status, missing_required_items, workflow_status,
            classification_status, approval_status, final_status, failure_status,
            route_status, route_destination_type, route_destination, route_updated_at,
            route_execution_result, route_execution_output_path, route_executed_at,
            output_review_status, output_review_note, output_reviewed_at,
            promotion_status, promotion_destination_type, promotion_destination,
            promotion_result, promotion_output_path, promoted_at,
            scanned_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        """,
        (
            record["packet_path"],
            record["root_name"],
            record["job_id"],
            record["packet_type"],
            record["packet_version"],
            record["source"],
            record["asset_count"],
            record["packet_size"],
            record["created_at"],
            record["review_status"],
            record["select_count"],
            record["verification_status"],
            record["missing_required_items"],
            record.get("workflow_status", ""),
            record.get("classification_status", ""),
            record.get("approval_status", ""),
            record.get("final_status", ""),
            record.get("failure_status", ""),
            record.get("route_status", ""),
            record.get("route_destination_type", ""),
            record.get("route_destination", ""),
            record.get("route_updated_at", ""),
            record.get("route_execution_result", ""),
            record.get("route_execution_output_path", ""),
            record.get("route_executed_at", ""),
            record.get("output_review_status", ""),
            record.get("output_review_note", ""),
            record.get("output_reviewed_at", ""),
            record.get("promotion_status", ""),
            record.get("promotion_destination_type", ""),
            record.get("promotion_destination", ""),
            record.get("promotion_result", ""),
            record.get("promotion_output_path", ""),
            record.get("promoted_at", ""),
        ),
    )


def scan_roots(db_path: Path, roots: Sequence[PacketRoot]) -> int:
    conn = connect_registry(db_path)
    conn.execute("DELETE FROM packets")
    count = 0
    for root in roots:
        for packet in iter_packet_dirs(root) or []:
            record = registry_record(root.name, packet)
            if record is None:
                continue
            upsert_registry_record(conn, record)
            count += 1
    conn.commit()
    conn.close()
    return count


def load_registry_rows(db_path: Path) -> List[sqlite3.Row]:
    if not Path(db_path).expanduser().exists():
        raise FileNotFoundError(f"Packet registry not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT *
        FROM packets
        ORDER BY created_at DESC, job_id DESC
        """
    ).fetchall()
    conn.close()
    return rows


def resolve_packet(identifier: str, db_path: Path) -> sqlite3.Row:
    path = Path(identifier).expanduser()
    if not Path(db_path).expanduser().exists():
        raise FileNotFoundError(f"Packet registry not found: {db_path}")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    if path.exists():
        row = conn.execute("SELECT * FROM packets WHERE packet_path = ?", (str(path),)).fetchone()
    else:
        row = conn.execute(
            """
            SELECT *
            FROM packets
            WHERE job_id = ? OR packet_path = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (identifier, identifier),
        ).fetchone()
    conn.close()
    if row is None:
        raise FileNotFoundError(f"Packet not found in registry: {identifier}")
    return row


def direct_packet_record(identifier: str) -> Optional[dict]:
    packet = Path(identifier).expanduser()
    if not packet.is_dir():
        return None
    return registry_record("direct", packet)


def resolve_packet_or_direct(identifier: str, db_path: Path):
    try:
        return resolve_packet(identifier, db_path)
    except FileNotFoundError:
        record = direct_packet_record(identifier)
        if record is None:
            raise
        return record


def print_rows(headers, rows):
    if not rows:
        print("No packets found.")
        return
    widths = [len(h) for h in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(str(value)))
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))


def row_value(row, key: str, default=""):
    try:
        if hasattr(row, "keys") and key not in row.keys():
            return default
    except Exception:
        pass
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def has_attention(row) -> bool:
    failure_status = str(row_value(row, "failure_status", "") or "")
    return (
        row_value(row, "verification_status", "") != "ok"
        or bool(row_value(row, "missing_required_items", ""))
        or (failure_status not in ("", "none"))
        or row_value(row, "review_status", "") == "failed"
        or row_value(row, "workflow_status", "") == "failed"
    )


def is_ready(row) -> bool:
    failure_status = str(row_value(row, "failure_status", "") or "")
    return (
        row_value(row, "verification_status", "") == "ok"
        and not row_value(row, "missing_required_items", "")
        and row_value(row, "review_status", "") in READY_REVIEW_STATUSES
        and failure_status in ("", "none")
    )


def lifecycle_status(row) -> str:
    return str(row_value(row, "workflow_status", "") or row_value(row, "review_status", "") or "unknown")


def queue_sort_key(row):
    status = lifecycle_status(row)
    if has_attention(row):
        bucket = 0
    elif status in EARLY_STATUSES or row_value(row, "review_status", "") in EARLY_STATUSES:
        bucket = 1
    elif status in DONE_STATUSES or row_value(row, "review_status", "") in DONE_STATUSES:
        bucket = 2
    else:
        bucket = 3
    return (bucket, str(row_value(row, "created_at", "")), str(row_value(row, "job_id", "")))


def sorted_queue_rows(rows):
    rows = sorted(rows, key=lambda row: (str(row_value(row, "created_at", "")), str(row_value(row, "job_id", ""))), reverse=True)
    return sorted(rows, key=lambda row: queue_sort_key(row)[0])


def filter_queue_rows(rows, status: Optional[str] = None):
    selected = list(rows)
    if status:
        needle = status.lower()
        selected = [
            row for row in selected
            if str(row_value(row, "review_status", "")).lower() == needle
            or str(row_value(row, "workflow_status", "")).lower() == needle
        ]
    return sorted_queue_rows(selected)


def attention_rows(rows):
    return sorted_queue_rows([row for row in rows if has_attention(row)])


def ready_rows(rows):
    return sorted_queue_rows([row for row in rows if is_ready(row)])


def routed_rows(rows):
    return [row for row in rows if row_value(row, "route_status", "")]


def in_progress_rows(rows):
    selected = []
    for row in rows:
        if has_attention(row) or row_value(row, "verification_status", "") != "ok":
            continue
        review_status = row_value(row, "review_status", "")
        workflow_status = row_value(row, "workflow_status", "")
        if review_status in ("new", "in_review") or workflow_status in ("classified", "extracted", "summarized"):
            selected.append(row)
    return sorted_queue_rows(selected)


def queue_table(rows):
    return [
        (
            row_value(row, "job_id", ""),
            row_value(row, "packet_type", ""),
            row_value(row, "asset_count", "") if row_value(row, "asset_count", "") != "" else "",
            row_value(row, "review_status", ""),
            row_value(row, "workflow_status", ""),
            row_value(row, "verification_status", ""),
            row_value(row, "created_at", ""),
        )
        for row in rows
    ]


def print_queue(rows, title: str, status: Optional[str] = None):
    print(title)
    print()
    print(f"Total packets: {len(rows)}")
    if status:
        print(f"Filter: {status}")
    print()
    if not rows:
        print("No packets found.")
        return
    for group, group_rows in grouped_counts(rows, "review_status"):
        print(f"{group}: {group_rows}")
    print()
    print_rows(
        ["job_id", "packet_type", "assets", "review", "workflow", "verification", "created_at"],
        queue_table(rows),
    )


def type_counts(rows):
    return grouped_counts(rows, "packet_type")


def ready_line(row):
    status = row_value(row, "review_status", "")
    workflow = row_value(row, "workflow_status", "")
    status_text = f"{status}/{workflow}" if workflow else status
    assets = int(row_value(row, "asset_count", 0) or 0)
    selects = int(row_value(row, "select_count", 0) or 0)
    text = f"  - {row_value(row, 'job_id', '')} - {row_value(row, 'packet_type', '')}, {status_text}, {assets} assets"
    if selects:
        text += f", {selects} selects"
    return text


def attention_reason(row):
    reasons = []
    if row_value(row, "verification_status", "") != "ok":
        reasons.append(str(row_value(row, "verification_status", "")))
    if row_value(row, "missing_required_items", ""):
        reasons.append(f"missing_required={row_value(row, 'missing_required_items', '')}")
    failure_status = str(row_value(row, "failure_status", "") or "")
    if failure_status not in ("", "none"):
        reasons.append(f"failure_status={failure_status}")
    if row_value(row, "review_status", "") == "failed" or row_value(row, "workflow_status", "") == "failed":
        reasons.append("status=failed")
    return "; ".join(reasons) or "attention"


def briefing_suggestions(rows, ready, attention, in_progress):
    suggestions = []
    queued_routes = [row for row in rows if row_value(row, "route_status", "") == "queued"]
    executed_routes = [row for row in rows if row_value(row, "route_status", "") == "executed"]
    executed_outputs = [row for row in executed_routes if row_value(row, "route_execution_output_path", "")]
    unreviewed_outputs = [
        row for row in executed_outputs
        if row_value(row, "output_review_status", "") in ("", "new")
    ]
    needs_work_outputs = [row for row in executed_outputs if row_value(row, "output_review_status", "") == "needs_work"]
    reviewed_outputs = [row for row in executed_outputs if row_value(row, "output_review_status", "") == "reviewed"]
    unpromoted_reviewed_outputs = [row for row in reviewed_outputs if not row_value(row, "promotion_status", "")]
    promotions = [row for row in rows if row_value(row, "promotion_status", "")]
    promoted = [row for row in promotions if row_value(row, "promotion_status", "") == "promoted"]
    held_promotions = [row for row in promotions if row_value(row, "promotion_status", "") == "held"]
    unrouted_ready = [row for row in ready if not row_value(row, "route_status", "")]
    all_verified = bool(rows) and all(row_value(row, "verification_status", "") == "ok" for row in rows)
    if attention:
        suggestions.append("Resolve packets needing attention before new ingest.")
    if queued_routes and not executed_routes:
        suggestions.append(f"{len(queued_routes)} routes are queued.")
        suggestions.append("Execute downstream routes or continue ingest.")
    elif executed_routes and not queued_routes:
        suggestions.append(f"{len(executed_routes)} packet routes have been executed.")
    elif queued_routes and executed_routes:
        suggestions.append(f"{len(queued_routes)} routes are queued.")
        suggestions.append(f"{len(executed_routes)} packet routes have been executed.")
        suggestions.append("Execute queued routes; review executed outputs.")
    if needs_work_outputs:
        suggestions.append("Resolve outputs marked needs_work.")
    elif unreviewed_outputs:
        suggestions.append("Review executed route outputs.")
    elif unpromoted_reviewed_outputs:
        suggestions.append("Promote reviewed outputs or continue ingest.")
    elif executed_outputs and all(row_value(row, "output_review_status", "") == "reviewed" and row_value(row, "promotion_status", "") for row in executed_outputs):
        suggestions.append("Promoted outputs are ready for downstream use.")
    elif executed_outputs and all(row_value(row, "output_review_status", "") == "reviewed" for row in executed_outputs):
        suggestions.append("Executed outputs have been reviewed; continue ingest or promote outputs.")
    if promoted:
        suggestions.append(f"{len(promoted)} packet outputs have been promoted.")
    if held_promotions:
        suggestions.append("Review held promotions when ready.")
    if unrouted_ready:
        suggestions.append(f"Assign downstream routes for {len(unrouted_ready)} ready packets.")
    if any(
        row_value(row, "packet_type", "") == "laia.paper_ingest"
        and row_value(row, "review_status", "") == "finalized"
        for row in unrouted_ready
    ):
        suggestions.append("Route or archive finalized paper packets.")
    if any(
        row_value(row, "packet_type", "") == "laia.photo_ingest"
        and row_value(row, "review_status", "") == "reviewed"
        and int(row_value(row, "select_count", 0) or 0) > 0
        for row in unrouted_ready
    ):
        suggestions.append("Review/export photo selects or promote them to a project packet.")
    if in_progress:
        suggestions.append("Continue review for new or in-progress packets.")
    if not rows:
        suggestions.append("Run an ingest or scan packet roots.")
    if all_verified and not attention and ready:
        suggestions.append("Archive is healthy.")
    return suggestions


def registry_briefing(rows) -> str:
    rows = list(rows)
    ready = ready_rows(rows)
    attention = attention_rows(rows)
    in_progress = in_progress_rows(rows)
    verified = sum(1 for row in rows if row_value(row, "verification_status", "") == "ok")
    total_assets = sum(int(row_value(row, "asset_count", 0) or 0) for row in rows)
    recent = sorted(rows, key=lambda row: str(row_value(row, "created_at", "")), reverse=True)[:5]

    lines = [
        "LAIA Packet Briefing",
        "",
        "Archive Health:",
        f"  Packets: {len(rows)}",
        f"  Verified: {verified}",
        f"  Attention: {len(attention)}",
        f"  Ready: {len(ready)}",
        f"  Total assets: {total_assets}",
        "",
        "Packet Types:",
    ]
    if rows:
        for packet_type, count in type_counts(rows):
            lines.append(f"  {packet_type}: {count}")
    else:
        lines.append("  none")

    lines.extend(["", "Ready:"])
    if ready:
        lines.extend(ready_line(row) for row in ready)
    else:
        lines.append("  none")

    route_counts = grouped_counts([row for row in rows if row_value(row, "route_status", "")], "route_status")
    lines.extend(["", "Routes:"])
    if route_counts:
        for status, count in route_counts:
            lines.append(f"  {status}: {count}")
    else:
        lines.append("  none")

    executed_outputs = [
        row for row in rows
        if row_value(row, "route_status", "") == "executed" and row_value(row, "route_execution_output_path", "")
    ]
    if executed_outputs:
        lines.extend(["", "Executed Outputs:"])
        for row in executed_outputs:
            lines.append(f"  - {row_value(row, 'job_id', '')} -> {row_value(row, 'route_execution_output_path', '')}")

        review_counts = {}
        for row in executed_outputs:
            status = row_value(row, "output_review_status", "") or "new"
            review_counts[status] = review_counts.get(status, 0) + 1
        lines.extend(["", "Output Review:"])
        for status in sorted(review_counts):
            lines.append(f"  {status}: {review_counts[status]}")

    promotion_rows = [row for row in rows if row_value(row, "promotion_status", "")]
    if promotion_rows:
        promotion_counts = {}
        for row in promotion_rows:
            status = row_value(row, "promotion_status", "")
            promotion_counts[status] = promotion_counts.get(status, 0) + 1
            result = row_value(row, "promotion_result", "")
            if result and result != status:
                promotion_counts[result] = promotion_counts.get(result, 0) + 1
        lines.extend(["", "Promotions:"])
        for status in sorted(promotion_counts):
            lines.append(f"  {status}: {promotion_counts[status]}")

        promoted_outputs = [row for row in promotion_rows if row_value(row, "promotion_output_path", "")]
        if promoted_outputs:
            lines.extend(["", "Promoted Outputs:"])
            for row in promoted_outputs:
                lines.append(f"  - {row_value(row, 'job_id', '')} -> {row_value(row, 'promotion_output_path', '')}")

    lines.extend(["", "Attention:"])
    if attention:
        for row in attention:
            lines.append(f"  - {row_value(row, 'job_id', '')} - {row_value(row, 'packet_type', '')}: {attention_reason(row)}")
    else:
        lines.append("  none")

    lines.extend(["", "In Progress:"])
    if in_progress:
        for row in in_progress:
            workflow = row_value(row, "workflow_status", "")
            status = f"{row_value(row, 'review_status', '')}/{workflow}" if workflow else row_value(row, "review_status", "")
            lines.append(f"  - {row_value(row, 'job_id', '')} - {row_value(row, 'packet_type', '')}, {status}")
    else:
        lines.append("  none")

    lines.extend(["", "Recent Activity:"])
    if recent:
        for row in recent:
            lines.append(
                f"  - {row_value(row, 'job_id', '')} - {row_value(row, 'packet_type', '')}, "
                f"{row_value(row, 'review_status', '')}, {row_value(row, 'created_at', '')}"
            )
    else:
        lines.append("  none")

    lines.extend(["", "Suggested Next Actions:"])
    for suggestion in briefing_suggestions(rows, ready, attention, in_progress):
        lines.append(f"  - {suggestion}")
    return "\n".join(lines) + "\n"


def command_packets_scan(_args):
    cfg = config_from_env()
    count = scan_roots(cfg.db_path, cfg.roots)
    print("LAIA Packet Registry Scan")
    print()
    print(f"Registry: {cfg.db_path}")
    for root in cfg.roots:
        print(f"Root:     {root.name} {root.path}")
    print(f"Packets:  {count}")


def command_packets_list(_args):
    cfg = config_from_env()
    rows = load_registry_rows(cfg.db_path)
    table = [
        (
            row["job_id"],
            row["packet_type"],
            row["asset_count"] if row["asset_count"] is not None else "",
            row["review_status"],
            row["verification_status"],
            row["created_at"],
        )
        for row in rows
    ]
    print_rows(["job_id", "packet_type", "assets", "review", "verification", "created_at"], table)


def command_packets_queue(args):
    cfg = config_from_env()
    rows = filter_queue_rows(load_registry_rows(cfg.db_path), getattr(args, "status", None))
    print_queue(rows, "LAIA Packet Queue", getattr(args, "status", None))


def command_packets_attention(_args):
    cfg = config_from_env()
    rows = attention_rows(load_registry_rows(cfg.db_path))
    print("LAIA Packet Attention Queue")
    print()
    if not rows:
        print("No packets need attention.")
        return
    table = [
        (
            row_value(row, "job_id", ""),
            row_value(row, "packet_type", ""),
            row_value(row, "verification_status", ""),
            row_value(row, "failure_status", ""),
            row_value(row, "missing_required_items", ""),
        )
        for row in rows
    ]
    print_rows(["job_id", "packet_type", "verification", "failure", "missing_required"], table)


def command_packets_ready(_args):
    cfg = config_from_env()
    rows = ready_rows(load_registry_rows(cfg.db_path))
    print("LAIA Packet Ready Queue")
    print()
    print(f"Ready packets: {len(rows)}")
    print()
    if not rows:
        print("No packets are ready.")
        return
    table = [
        (
            row_value(row, "job_id", ""),
            row_value(row, "packet_type", ""),
            row_value(row, "asset_count", "") if row_value(row, "asset_count", "") != "" else "",
            row_value(row, "review_status", ""),
            row_value(row, "workflow_status", ""),
            row_value(row, "route_status", ""),
            row_value(row, "packet_path", ""),
        )
        for row in rows
    ]
    print_rows(["job_id", "packet_type", "assets", "review", "workflow", "route", "packet_path"], table)


def command_packets_briefing(_args):
    cfg = config_from_env()
    rows = load_registry_rows(cfg.db_path)
    print(registry_briefing(rows), end="")


def lifecycle_checksum_count(packet: Path):
    path = checksum_path(packet)
    if not path.exists():
        return None
    try:
        return count_checksum_entries(path)
    except Exception:
        return None


def timeline_events(row, route: dict):
    events = []
    created_at = row_value(row, "created_at", "")
    if created_at:
        events.append((created_at, "packet created"))
    history = route.get("history") if isinstance(route.get("history"), list) else []
    for event in history:
        status = event.get("route_status", "")
        if status == "queued":
            timestamp = event.get("created_at", "")
            destination = f"{event.get('destination_type', '')} / {event.get('destination', '')}".rstrip(" /")
            label = f"route queued: {destination}" if destination else "route queued"
        elif status == "executed":
            timestamp = event.get("executed_at", "")
            label = f"route executed: {event.get('execution_result', '')}".rstrip()
        elif status == "output_reviewed":
            timestamp = event.get("reviewed_at", "")
            label = f"output reviewed: {event.get('output_review_status', '')}".rstrip()
        elif status == "promoted":
            timestamp = event.get("promoted_at", "")
            destination = f"{event.get('promotion_destination_type', '')} / {event.get('promotion_destination', '')}".rstrip(" /")
            label = f"promoted: {destination}" if destination else "promoted"
        else:
            timestamp = event.get("created_at") or event.get("updated_at") or event.get("executed_at") or event.get("reviewed_at") or event.get("promoted_at") or ""
            label = status or "event"
        if timestamp:
            events.append((timestamp, label))
    if row_value(row, "route_updated_at", "") and not any(label.startswith("route queued") for _, label in events):
        destination = f"{row_value(row, 'route_destination_type', '')} / {row_value(row, 'route_destination', '')}".rstrip(" /")
        events.append((row_value(row, "route_updated_at", ""), f"route {row_value(row, 'route_status', '')}: {destination}".rstrip()))
    if row_value(row, "route_executed_at", "") and not any(label.startswith("route executed") for _, label in events):
        events.append((row_value(row, "route_executed_at", ""), f"route executed: {row_value(row, 'route_execution_result', '')}".rstrip()))
    if row_value(row, "output_reviewed_at", "") and not any(label.startswith("output reviewed") for _, label in events):
        events.append((row_value(row, "output_reviewed_at", ""), f"output reviewed: {row_value(row, 'output_review_status', '')}".rstrip()))
    if row_value(row, "promoted_at", "") and not any(label.startswith("promoted") for _, label in events):
        destination = f"{row_value(row, 'promotion_destination_type', '')} / {row_value(row, 'promotion_destination', '')}".rstrip(" /")
        events.append((row_value(row, "promoted_at", ""), f"promoted: {destination}".rstrip()))
    seen = set()
    clean = []
    for timestamp, label in sorted(events, key=lambda item: item[0]):
        key = (timestamp, label)
        if key not in seen:
            seen.add(key)
            clean.append((timestamp, label))
    return clean


def lifecycle_current_state(row) -> str:
    if has_attention(row):
        return "Current state: needs attention."
    if row_value(row, "promotion_status", ""):
        return "Current state: promoted and ready for downstream use."
    if row_value(row, "output_review_status", "") == "reviewed":
        return "Current state: output reviewed and ready for promotion."
    if row_value(row, "route_status", "") == "executed":
        return "Current state: route executed; output awaiting review."
    if row_value(row, "route_status", "") == "queued":
        return "Current state: route queued; awaiting execution."
    if is_ready(row):
        return "Current state: ready for routing."
    return "Current state: in progress."


def registry_lifecycle(row, packet: Path, route: Optional[dict] = None) -> str:
    route = route if route is not None else read_routing(packet)
    lines = [
        "LAIA Packet Lifecycle",
        "",
        "Packet:",
        f"  job_id: {row_value(row, 'job_id', packet.name)}",
        f"  packet_type: {row_value(row, 'packet_type', '')}",
        f"  packet_version: {row_value(row, 'packet_version', '')}",
        f"  packet_path: {row_value(row, 'packet_path', str(packet))}",
        f"  source: {row_value(row, 'source', '')}",
        f"  asset_count: {row_value(row, 'asset_count', '')}",
        f"  packet_size: {row_value(row, 'packet_size', '')}",
        f"  created_at: {row_value(row, 'created_at', '')}",
        "",
        "Verification:",
        f"  verification_status: {row_value(row, 'verification_status', '')}",
    ]
    if row_value(row, "missing_required_items", ""):
        lines.append(f"  missing_required: {row_value(row, 'missing_required_items', '')}")
    checksum_count = lifecycle_checksum_count(packet)
    if checksum_count is not None:
        lines.append(f"  checksum_count: {checksum_count}")
    lines.extend(["", "Review / Workflow:", f"  review_status: {row_value(row, 'review_status', '')}"])
    for key in ["workflow_status", "classification_status", "approval_status", "final_status", "failure_status"]:
        if row_value(row, key, ""):
            lines.append(f"  {key}: {row_value(row, key, '')}")
    if int(row_value(row, "select_count", 0) or 0):
        lines.append(f"  select_count: {row_value(row, 'select_count', 0)}")
    lines.extend(["", "Route:"])
    if row_value(row, "route_status", ""):
        lines.append(f"  route_status: {row_value(row, 'route_status', '')}")
        lines.append(f"  route_destination_type: {row_value(row, 'route_destination_type', '')}")
        lines.append(f"  route_destination: {row_value(row, 'route_destination', '')}")
        lines.append(f"  route_updated_at: {row_value(row, 'route_updated_at', '')}")
        if route.get("note"):
            lines.append(f"  route_note: {route.get('note', '')}")
    else:
        lines.append("  none")
    lines.extend(["", "Execution:"])
    if row_value(row, "route_execution_result", "") or row_value(row, "route_executed_at", ""):
        lines.append(f"  route_execution_result: {row_value(row, 'route_execution_result', '')}")
        lines.append(f"  route_execution_output_path: {row_value(row, 'route_execution_output_path', '')}")
        lines.append(f"  route_executed_at: {row_value(row, 'route_executed_at', '')}")
    else:
        lines.append("  none")
    lines.extend(["", "Output Review:"])
    if row_value(row, "output_review_status", ""):
        lines.append(f"  output_review_status: {row_value(row, 'output_review_status', '')}")
        lines.append(f"  output_reviewed_at: {row_value(row, 'output_reviewed_at', '')}")
        lines.append(f"  output_review_note: {row_value(row, 'output_review_note', '')}")
    else:
        lines.append("  none")
    lines.extend(["", "Promotion:"])
    if row_value(row, "promotion_status", ""):
        lines.append(f"  promotion_status: {row_value(row, 'promotion_status', '')}")
        lines.append(f"  promotion_destination_type: {row_value(row, 'promotion_destination_type', '')}")
        lines.append(f"  promotion_destination: {row_value(row, 'promotion_destination', '')}")
        lines.append(f"  promotion_result: {row_value(row, 'promotion_result', '')}")
        lines.append(f"  promotion_output_path: {row_value(row, 'promotion_output_path', '')}")
        lines.append(f"  promoted_at: {row_value(row, 'promoted_at', '')}")
        if route.get("promotion_note"):
            lines.append(f"  promotion_note: {route.get('promotion_note', '')}")
    else:
        lines.append("  none")
    lines.extend(["", "Timeline:"])
    events = timeline_events(row, route)
    if events:
        for timestamp, label in events:
            lines.append(f"  - {timestamp} {label}")
    else:
        lines.append("  none")
    lines.extend(["", lifecycle_current_state(row)])
    return "\n".join(lines) + "\n"


def lifecycle_state_label(row) -> str:
    text = lifecycle_current_state(row)
    prefix = "Current state: "
    if text.startswith(prefix):
        text = text[len(prefix):]
    return text.rstrip(".")


def lifecycle_section(values: dict) -> dict:
    return {key: value for key, value in values.items() if value not in ("", None)}


def lifecycle_report_data(row, packet: Path, generated_at: Optional[str] = None, route: Optional[dict] = None) -> dict:
    route = route if route is not None else read_routing(packet)
    generated_at = generated_at or utc_now()
    checksum_count = lifecycle_checksum_count(packet)
    timeline = []
    for timestamp, label in timeline_events(row, route):
        if ": " in label:
            event, detail = label.split(": ", 1)
        else:
            event, detail = label, ""
        timeline.append({"timestamp": timestamp, "event": event, "detail": detail})
    verification = {
        "verification_status": row_value(row, "verification_status", ""),
        "missing_required": row_value(row, "missing_required_items", ""),
    }
    if checksum_count is not None:
        verification["checksum_count"] = checksum_count
    return {
        "report_type": "laia.packet_lifecycle",
        "report_version": "0.1",
        "generated_at": generated_at,
        "packet": lifecycle_section(
            {
                "job_id": row_value(row, "job_id", packet.name),
                "packet_type": row_value(row, "packet_type", ""),
                "packet_version": row_value(row, "packet_version", ""),
                "packet_path": row_value(row, "packet_path", str(packet)),
                "source": row_value(row, "source", ""),
                "asset_count": row_value(row, "asset_count", ""),
                "packet_size": row_value(row, "packet_size", ""),
                "created_at": row_value(row, "created_at", ""),
            }
        ),
        "verification": lifecycle_section(verification),
        "review_workflow": lifecycle_section(
            {
                "review_status": row_value(row, "review_status", ""),
                "workflow_status": row_value(row, "workflow_status", ""),
                "classification_status": row_value(row, "classification_status", ""),
                "approval_status": row_value(row, "approval_status", ""),
                "final_status": row_value(row, "final_status", ""),
                "failure_status": row_value(row, "failure_status", ""),
                "select_count": row_value(row, "select_count", 0) if int(row_value(row, "select_count", 0) or 0) else "",
            }
        ),
        "route": lifecycle_section(
            {
                "route_status": row_value(row, "route_status", ""),
                "route_destination_type": row_value(row, "route_destination_type", ""),
                "route_destination": row_value(row, "route_destination", ""),
                "route_updated_at": row_value(row, "route_updated_at", ""),
                "route_note": route.get("note", ""),
            }
        ),
        "execution": lifecycle_section(
            {
                "route_execution_result": row_value(row, "route_execution_result", ""),
                "route_execution_output_path": row_value(row, "route_execution_output_path", ""),
                "route_executed_at": row_value(row, "route_executed_at", ""),
            }
        ),
        "output_review": lifecycle_section(
            {
                "output_review_status": row_value(row, "output_review_status", ""),
                "output_reviewed_at": row_value(row, "output_reviewed_at", ""),
                "output_review_note": row_value(row, "output_review_note", ""),
            }
        ),
        "promotion": lifecycle_section(
            {
                "promotion_status": row_value(row, "promotion_status", ""),
                "promotion_destination_type": row_value(row, "promotion_destination_type", ""),
                "promotion_destination": row_value(row, "promotion_destination", ""),
                "promotion_result": row_value(row, "promotion_result", ""),
                "promotion_output_path": row_value(row, "promotion_output_path", ""),
                "promoted_at": row_value(row, "promoted_at", ""),
                "promotion_note": route.get("promotion_note", ""),
            }
        ),
        "timeline": timeline,
        "current_state": lifecycle_state_label(row),
    }


def lifecycle_report_markdown(row, packet: Path, generated_at: Optional[str] = None, route: Optional[dict] = None) -> str:
    route = route if route is not None else read_routing(packet)
    generated_at = generated_at or utc_now()
    body = registry_lifecycle(row, packet, route=route)
    body = body.replace("LAIA Packet Lifecycle\n\n", "", 1)
    return f"# LAIA Packet Lifecycle Report\n\nGenerated At: {generated_at}\n\n{body}"


def lifecycle_output_dir(packet: Path, output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser()
    return Path(packet).expanduser() / "lifecycle"


def write_lifecycle_reports(row, packet: Path, report_format: str = "both", output_dir: Optional[str] = None) -> dict:
    if report_format not in {"md", "json", "both"}:
        raise ValueError(f"Invalid lifecycle report format: {report_format}")
    route = read_routing(packet)
    generated_at = utc_now()
    destination = lifecycle_output_dir(packet, output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    paths = {"generated_at": generated_at, "output_dir": str(destination), "md": "", "json": ""}
    if report_format in {"md", "both"}:
        md_path = destination / "lifecycle_report.md"
        md_path.write_text(lifecycle_report_markdown(row, packet, generated_at=generated_at, route=route), encoding="utf-8")
        paths["md"] = str(md_path)
    if report_format in {"json", "both"}:
        json_path = destination / "lifecycle_report.json"
        data = lifecycle_report_data(row, packet, generated_at=generated_at, route=route)
        json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        paths["json"] = str(json_path)
    return paths


def lifecycle_report_files(packet: Path) -> dict:
    folder = Path(packet) / "lifecycle"
    md_path = folder / "lifecycle_report.md"
    json_path = folder / "lifecycle_report.json"
    generated_at = ""
    if json_path.exists():
        try:
            generated_at = json.loads(json_path.read_text(encoding="utf-8")).get("generated_at", "")
        except Exception:
            generated_at = ""
    return {
        "md": md_path if md_path.exists() else None,
        "json": json_path if json_path.exists() else None,
        "generated_at": generated_at,
    }


def command_packets_lifecycle(args):
    cfg = config_from_env()
    try:
        row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    print(registry_lifecycle(row, packet), end="")


def command_packets_export_lifecycle(args):
    cfg = config_from_env()
    try:
        row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
        paths = write_lifecycle_reports(
            row,
            packet,
            report_format=getattr(args, "format", "both") or "both",
            output_dir=getattr(args, "output_dir", None),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    written = [path for key, path in paths.items() if key in {"md", "json"} and path]
    print("LAIA Packet Lifecycle Export")
    print()
    print(f"Packet:          {row_value(row, 'job_id', packet.name)}")
    print(f"Output Directory: {paths['output_dir']}")
    print(f"Reports Written:  {len(written)}")
    for path in written:
        print(f"  {path}")


def command_packets_export_lifecycles(args):
    cfg = config_from_env()
    rows = load_registry_rows(cfg.db_path)
    report_format = getattr(args, "format", "both") or "both"
    output_root = getattr(args, "output_root", None)
    packets = 0
    reports = 0
    try:
        for row in rows:
            packet = Path(row_value(row, "packet_path", ""))
            output_dir = None
            if output_root:
                output_dir = str(Path(output_root).expanduser() / sanitize_folder_name(row_value(row, "job_id", packet.name), packet.name))
            paths = write_lifecycle_reports(row, packet, report_format=report_format, output_dir=output_dir)
            packets += 1
            reports += sum(1 for key in ("md", "json") if paths.get(key))
    except ValueError as exc:
        raise SystemExit(str(exc))
    print("LAIA Packet Lifecycle Export")
    print()
    print(f"Packets Exported: {packets}")
    print(f"Reports Written:  {reports}")
    if output_root:
        print(f"Output Root:      {Path(output_root).expanduser()}")


def command_packets_lifecycle_files(args):
    cfg = config_from_env()
    try:
        row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    except FileNotFoundError as exc:
        raise SystemExit(str(exc))
    files = lifecycle_report_files(packet)
    print("LAIA Packet Lifecycle Files")
    print()
    print(f"Packet: {row_value(row, 'job_id', packet.name)}")
    if not files["md"] and not files["json"]:
        print("No lifecycle reports found.")
        return
    if files["md"]:
        print(f"Markdown: {files['md']}")
    if files["json"]:
        print(f"JSON:     {files['json']}")
    if files["generated_at"]:
        print(f"Generated At: {files['generated_at']}")


def print_packet_record(row):
    print("LAIA Packet")
    print()
    print(f"Job ID:              {row['job_id']}")
    print(f"Packet Type:         {row['packet_type']}")
    print(f"Packet Version:      {row['packet_version']}")
    print(f"Packet Path:         {row['packet_path']}")
    print(f"Source:              {row['source']}")
    print(f"Asset Count:         {row['asset_count'] if row['asset_count'] is not None else ''}")
    print(f"Packet Size:         {row['packet_size']}")
    print(f"Created At:          {row['created_at']}")
    print(f"Review Status:       {row['review_status']}")
    if "workflow_status" in row.keys():
        print(f"Workflow Status:     {row['workflow_status']}")
        print(f"Classification:      {row['classification_status']}")
        print(f"Approval Status:     {row['approval_status']}")
        print(f"Final Status:        {row['final_status']}")
        print(f"Failure Status:      {row['failure_status']}")
    if "route_status" in row.keys():
        print(f"Route Status:        {row['route_status']}")
        print(f"Route Type:          {row['route_destination_type']}")
        print(f"Route Destination:   {row['route_destination']}")
        print(f"Route Updated At:    {row['route_updated_at']}")
    print(f"Select Count:        {row['select_count']}")
    print(f"Verification Status: {row['verification_status']}")
    print(f"Missing Required:    {row['missing_required_items']}")


def grouped_counts(rows, key: str):
    counts = {}
    for row in rows:
        value = row[key] or "unknown"
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def registry_report(db_path: Path, rows) -> str:
    total = len(rows)
    verified = sum(1 for row in rows if row["verification_status"] == "ok")
    missing = sum(1 for row in rows if row["verification_status"] != "ok")
    total_assets = sum(int(row["asset_count"] or 0) for row in rows)
    with_selects = sum(1 for row in rows if int(row["select_count"] or 0) > 0)
    root_counts = grouped_counts(rows, "root_name") if rows else []
    attention = [row for row in rows if row["verification_status"] != "ok"]

    lines = [
        "LAIA Packet Registry Report",
        "",
        f"Registry: {db_path}",
        "",
        "Summary:",
        f"  Packets: {total}",
        f"  Verified: {verified}",
        f"  Missing required: {missing}",
        f"  Total assets: {total_assets}",
        f"  Packets with selects: {with_selects}",
        "",
        "By type:",
    ]

    type_counts = grouped_counts(rows, "packet_type")
    if type_counts:
        for packet_type, count in type_counts:
            lines.append(f"  {packet_type}: {count}")
    else:
        lines.append("  none")

    lines.extend(["", "By review status:"])
    review_counts = grouped_counts(rows, "review_status")
    if review_counts:
        for status, count in review_counts:
            lines.append(f"  {status}: {count}")
    else:
        lines.append("  none")

    lines.extend(["", "By route status:"])
    route_counts = grouped_counts([row for row in rows if row_value(row, "route_status", "")], "route_status")
    if route_counts:
        for status, count in route_counts:
            lines.append(f"  {status}: {count}")
    else:
        lines.append("  none")

    lines.extend(["", "By root:"])
    if root_counts:
        for root_name, count in root_counts:
            lines.append(f"  {root_name}: {count}")
    else:
        lines.append("  none")

    lines.extend(["", "Needs attention:"])
    if attention:
        for row in attention:
            lines.append(
                f"  {row['job_id']} ({row['verification_status']}): "
                f"{row['missing_required_items'] or row['packet_path']}"
            )
    else:
        lines.append("  none")

    return "\n".join(lines) + "\n"


def export_csv_path(destination: Optional[str], db_path: Path) -> Path:
    if not destination:
        return Path(db_path).expanduser().parent / "packet_registry_export.csv"
    path = Path(destination).expanduser()
    if path.exists() and path.is_dir():
        return path / "packet_registry_export.csv"
    if str(destination).endswith(("/", os.sep)):
        return path / "packet_registry_export.csv"
    return path


def export_registry_csv(rows, destination: Path) -> Path:
    destination = Path(destination).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_EXPORT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "job_id": row["job_id"],
                    "packet_type": row["packet_type"],
                    "packet_version": row["packet_version"],
                    "packet_path": row["packet_path"],
                    "source": row["source"],
                    "asset_count": row["asset_count"] if row["asset_count"] is not None else "",
                    "packet_size": row["packet_size"],
                    "created_at": row["created_at"],
                    "review_status": row["review_status"],
                    "select_count": row["select_count"],
                    "verification_status": row["verification_status"],
                    "missing_required": row["missing_required_items"],
                }
            )
    return destination


def command_packets_inspect(args):
    cfg = config_from_env()
    row = resolve_packet_or_direct(args.identifier, cfg.db_path)
    print_packet_record(row)


def command_packets_verify(args):
    cfg = config_from_env()
    row = resolve_packet_or_direct(args.identifier, cfg.db_path)
    packet = Path(row["packet_path"])
    record = registry_record(row["root_name"], packet)
    if record is None:
        raise SystemExit(f"Packet could not be read: {packet}")

    conn = connect_registry(cfg.db_path)
    upsert_registry_record(conn, record)
    conn.commit()
    conn.close()

    print("LAIA Packet Verification")
    print()
    print(f"Packet:              {packet}")
    print(f"Verification Status: {record['verification_status']}")
    print(f"Missing Required:    {record['missing_required_items']}")
    if record["verification_status"] != "ok":
        raise SystemExit(2)


def command_packets_status(_args):
    cfg = config_from_env()
    rows = load_registry_rows(cfg.db_path)
    total = len(rows)
    ok = sum(1 for row in rows if row["verification_status"] == "ok")
    missing = total - ok
    reviewed = sum(1 for row in rows if row["review_status"] == "reviewed")
    selected = sum(1 for row in rows if row["select_count"] and int(row["select_count"]) > 0)

    print("LAIA Packet Registry Status")
    print()
    print(f"Registry: {cfg.db_path}")
    print(f"Packets:  {total}")
    print(f"Verified: {ok}")
    print(f"Missing:  {missing}")
    print(f"Reviewed: {reviewed}")
    print(f"Selected: {selected}")


def command_packets_report(_args):
    cfg = config_from_env()
    rows = load_registry_rows(cfg.db_path)
    print(registry_report(cfg.db_path, rows), end="")


def command_packets_export_csv(args):
    cfg = config_from_env()
    rows = load_registry_rows(cfg.db_path)
    destination = export_csv_path(getattr(args, "destination", None), cfg.db_path)
    path = export_registry_csv(rows, destination)
    print("LAIA Packet Registry CSV Export")
    print()
    print(f"Registry: {cfg.db_path}")
    print(f"Export:   {path}")
    print(f"Rows:     {len(rows)}")


def command_packets_open(args):
    cfg = config_from_env()
    row = resolve_packet_or_direct(args.identifier, cfg.db_path)
    packet = Path(row["packet_path"])
    if platform.system() == "Darwin":
        subprocess.run(["open", str(packet)], check=False)
    else:
        print(packet)


def route_row_for_identifier(identifier: str, db_path: Path):
    row = resolve_packet_or_direct(identifier, db_path)
    return row, Path(row["packet_path"])


def command_packets_route(args):
    cfg = config_from_env()
    destination_type = getattr(args, "destination_type", "")
    try:
        row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
        route = route_packet(
            packet,
            destination_type,
            destination=getattr(args, "destination", "") or "",
            note=getattr(args, "note", "") or "",
        )
    except ValueError as exc:
        raise SystemExit(str(exc))
    print("LAIA Packet Route")
    print()
    print(f"Packet:      {row_value(row, 'job_id', packet.name)}")
    print(f"Path:        {packet}")
    print(f"Status:      {route.get('route_status', '')}")
    print(f"Destination: {route.get('destination_type', '')} {route.get('destination', '')}".rstrip())
    print(f"Updated:     {route.get('updated_at', '')}")


def command_packets_route_status(args):
    cfg = config_from_env()
    row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    route = read_routing(packet)
    print("LAIA Packet Route Status")
    print()
    print(f"Packet: {row_value(row, 'job_id', packet.name)}")
    if not route:
        print("No route assigned.")
        return
    history = route.get("history") if isinstance(route.get("history"), list) else []
    print(f"Route Status:     {route.get('route_status', '')}")
    print(f"Destination Type: {route.get('destination_type', '')}")
    print(f"Destination:      {route.get('destination', '')}")
    print(f"Note:             {route.get('note', '')}")
    print(f"Updated At:       {route.get('updated_at', '')}")
    print(f"History Count:    {len(history)}")


def command_packets_routes(args):
    cfg = config_from_env()
    rows = [row for row in load_registry_rows(cfg.db_path) if row_value(row, "route_status", "")]
    status = getattr(args, "status", None)
    if status:
        rows = [row for row in rows if row_value(row, "route_status", "") == status]
    print("LAIA Packet Routes")
    print()
    if status:
        print(f"Status: {status}")
        print()
    if not rows:
        print("No routed packets.")
        return
    table = [
        (
            row_value(row, "job_id", ""),
            row_value(row, "packet_type", ""),
            row_value(row, "review_status", ""),
            row_value(row, "route_status", ""),
            row_value(row, "route_destination_type", ""),
            row_value(row, "route_destination", ""),
            row_value(row, "route_execution_result", ""),
            row_value(row, "route_updated_at", ""),
        )
        for row in rows
    ]
    print_rows(["job_id", "packet_type", "review", "route", "type", "destination", "result", "updated_at"], table)


def command_packets_clear_route(args):
    cfg = config_from_env()
    row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    route = clear_packet_route(packet, note=getattr(args, "note", "") or "")
    print("LAIA Packet Route Cleared")
    print()
    print(f"Packet:  {row_value(row, 'job_id', packet.name)}")
    print(f"Path:    {packet}")
    print(f"Status:  {route.get('route_status', '')}")
    print(f"Updated: {route.get('updated_at', '')}")


def command_packets_execute_route(args):
    cfg = config_from_env()
    try:
        row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
        result = execute_packet_route(row, packet, dry_run=getattr(args, "dry_run", False))
    except ValueError as exc:
        raise SystemExit(str(exc))
    print("LAIA Packet Route Execution")
    print()
    print(f"Packet:  {row_value(row, 'job_id', packet.name)}")
    print(f"Path:    {packet}")
    print(f"Mode:    {'dry-run' if getattr(args, 'dry_run', False) else 'execute'}")
    print(f"Result:  {result.get('result', '')}")
    if result.get("output_path"):
        print(f"Output:  {result.get('output_path')}")
    if result.get("note"):
        print(f"Note:    {result.get('note')}")
    if result.get("missing"):
        print(f"Missing: {', '.join(result.get('missing', []))}")


def command_packets_execute_routes(args):
    cfg = config_from_env()
    rows = [row for row in load_registry_rows(cfg.db_path) if row_value(row, "route_status", "") == "queued"]
    print("LAIA Packet Route Execution")
    print()
    print(f"Queued routes: {len(rows)}")
    if not rows:
        return
    executed = 0
    failed = 0
    for row in rows:
        packet = Path(row_value(row, "packet_path", ""))
        try:
            result = execute_packet_route(row, packet, dry_run=getattr(args, "dry_run", False))
            executed += 1
            print(f"{row_value(row, 'job_id', packet.name)}: {result.get('result', '')}")
        except ValueError as exc:
            failed += 1
            print(f"{row_value(row, 'job_id', packet.name)}: failed - {exc}")
    print()
    print(f"{'Would execute' if getattr(args, 'dry_run', False) else 'Executed'}: {executed}")
    print(f"Failed:   {failed}")


def command_packets_route_history(args):
    cfg = config_from_env()
    row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    route = read_routing(packet)
    print("LAIA Packet Route History")
    print()
    print(f"Packet: {row_value(row, 'job_id', packet.name)}")
    if not route:
        print("No route assigned.")
        return
    history = route.get("history") if isinstance(route.get("history"), list) else []
    if not history:
        print("No route history.")
        return
    for index, event in enumerate(history, start=1):
        timestamp = event.get("executed_at") or event.get("created_at") or event.get("updated_at") or ""
        destination = f"{event.get('destination_type', '')} {event.get('destination', '')}".rstrip()
        result = event.get("execution_result", "")
        result_text = f" result={result}" if result else ""
        print(f"{index}. {event.get('route_status', '')} {destination} {timestamp}{result_text}".rstrip())
        if event.get("note"):
            print(f"   note: {event.get('note')}")


def command_packets_output(args):
    cfg = config_from_env()
    row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    route = read_routing(packet)
    print("LAIA Packet Output")
    print()
    print(f"Packet: {row_value(row, 'job_id', packet.name)}")
    print(f"Path:   {packet}")
    if not has_executed_output(route):
        print("No executed output found.")
        return
    output_path = output_path_from_route(route)
    file_count = len(output_file_rows(output_path)) if output_path.exists() else 0
    print(f"Route Status:         {route.get('route_status', '')}")
    print(f"Destination Type:     {route.get('destination_type', '')}")
    print(f"Destination:          {route.get('destination', '')}")
    print(f"Execution Result:     {route.get('execution_result', '')}")
    print(f"Execution Output:     {output_path}")
    print(f"Executed At:          {route.get('executed_at', '')}")
    if route.get("output_review_status"):
        print(f"Output Review Status: {route.get('output_review_status', '')}")
    if route.get("output_reviewed_at"):
        print(f"Output Reviewed At:   {route.get('output_reviewed_at', '')}")
    print(f"Output File Count:    {file_count}")


def command_packets_outputs(args):
    cfg = config_from_env()
    rows = [
        row for row in load_registry_rows(cfg.db_path)
        if row_value(row, "route_status", "") == "executed" and row_value(row, "route_execution_output_path", "")
    ]
    status = getattr(args, "status", None)
    destination_type = getattr(args, "destination_type", None)
    if status:
        rows = [row for row in rows if (row_value(row, "output_review_status", "") or "new") == status]
    if destination_type:
        rows = [row for row in rows if row_value(row, "route_destination_type", "") == destination_type]
    print("LAIA Packet Outputs")
    print()
    if not rows:
        print("No executed outputs.")
        return
    table = [
        (
            row_value(row, "job_id", ""),
            row_value(row, "packet_type", ""),
            row_value(row, "route_destination_type", ""),
            row_value(row, "route_execution_result", ""),
            row_value(row, "output_review_status", "") or "new",
            row_value(row, "route_execution_output_path", ""),
        )
        for row in rows
    ]
    print_rows(["job_id", "packet_type", "route_type", "result", "output_review", "output_path"], table)


def command_packets_output_files(args):
    cfg = config_from_env()
    row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    route = read_routing(packet)
    print("LAIA Packet Output Files")
    print()
    print(f"Packet: {row_value(row, 'job_id', packet.name)}")
    if not has_executed_output(route):
        print("No executed output found.")
        return
    output_path = output_path_from_route(route)
    print(f"Output: {output_path}")
    if not output_path.exists() or not output_path.is_dir():
        print("Output path does not exist.")
        return
    rows = output_file_rows(output_path)
    if not rows:
        print("No output files found.")
        return
    print_rows(["path", "bytes"], rows)


def command_packets_review_output(args):
    cfg = config_from_env()
    status = getattr(args, "status", None) or "reviewed"
    try:
        row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
        route = mark_output_reviewed(packet, status=status, note=getattr(args, "note", "") or "")
    except ValueError as exc:
        raise SystemExit(str(exc))
    print("LAIA Packet Output Review")
    print()
    print(f"Packet:   {row_value(row, 'job_id', packet.name)}")
    print(f"Status:   {route.get('output_review_status', '')}")
    print(f"Reviewed: {route.get('output_reviewed_at', '')}")
    if route.get("output_review_note"):
        print(f"Note:     {route.get('output_review_note', '')}")


def command_packets_output_history(args):
    cfg = config_from_env()
    row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    route = read_routing(packet)
    print("LAIA Packet Output History")
    print()
    print(f"Packet: {row_value(row, 'job_id', packet.name)}")
    if not route:
        print("No route assigned.")
        return
    history = route.get("history") if isinstance(route.get("history"), list) else []
    if not history:
        print("No output history.")
        return
    for index, event in enumerate(history, start=1):
        timestamp = event.get("reviewed_at") or event.get("executed_at") or event.get("created_at") or event.get("updated_at") or ""
        text = f"{index}. {event.get('route_status', '')} {timestamp}".rstrip()
        if event.get("output_review_status"):
            text += f" output_review_status={event.get('output_review_status')}"
        if event.get("execution_result"):
            text += f" execution_result={event.get('execution_result')}"
        print(text)
        if event.get("note"):
            print(f"   note: {event.get('note')}")


def command_packets_promote(args):
    cfg = config_from_env()
    try:
        row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
        result = promote_packet_output(
            row,
            packet,
            getattr(args, "destination_type", "") or "",
            destination=getattr(args, "destination", "") or "",
            note=getattr(args, "note", "") or "",
            dry_run=getattr(args, "dry_run", False),
        )
    except ValueError as exc:
        raise SystemExit(str(exc))
    print("LAIA Packet Promotion")
    print()
    print(f"Packet:  {row_value(row, 'job_id', packet.name)}")
    print(f"Mode:    {'dry-run' if getattr(args, 'dry_run', False) else 'promote'}")
    print(f"Status:  {result.get('status', '')}")
    print(f"Result:  {result.get('result', '')}")
    if result.get("output_path"):
        print(f"Output:  {result.get('output_path')}")
    if result.get("note"):
        print(f"Note:    {result.get('note')}")


def command_packets_promotions(args):
    cfg = config_from_env()
    rows = [row for row in load_registry_rows(cfg.db_path) if row_value(row, "promotion_status", "")]
    status = getattr(args, "status", None)
    destination_type = getattr(args, "destination_type", None)
    if status:
        rows = [row for row in rows if row_value(row, "promotion_status", "") == status]
    if destination_type:
        rows = [row for row in rows if row_value(row, "promotion_destination_type", "") == destination_type]
    print("LAIA Packet Promotions")
    print()
    if not rows:
        print("No promotions recorded.")
        return
    table = [
        (
            row_value(row, "job_id", ""),
            row_value(row, "packet_type", ""),
            row_value(row, "promotion_status", ""),
            row_value(row, "promotion_destination_type", ""),
            row_value(row, "promotion_destination", ""),
            row_value(row, "promotion_result", ""),
            row_value(row, "promoted_at", ""),
        )
        for row in rows
    ]
    print_rows(["job_id", "packet_type", "status", "type", "destination", "result", "promoted_at"], table)


def command_packets_promotion_status(args):
    cfg = config_from_env()
    row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    route = read_routing(packet)
    print("LAIA Packet Promotion Status")
    print()
    print(f"Packet: {row_value(row, 'job_id', packet.name)}")
    if not route.get("promotion_status"):
        print("No promotion recorded.")
        return
    history = route.get("history") if isinstance(route.get("history"), list) else []
    print(f"Promotion Status:      {route.get('promotion_status', '')}")
    print(f"Destination Type:      {route.get('promotion_destination_type', '')}")
    print(f"Destination:           {route.get('promotion_destination', '')}")
    print(f"Promotion Result:      {route.get('promotion_result', '')}")
    if route.get("promotion_output_path"):
        print(f"Promotion Output Path: {route.get('promotion_output_path', '')}")
    print(f"Promoted At:           {route.get('promoted_at', '')}")
    print(f"Promotion Note:        {route.get('promotion_note', '')}")
    print(f"History Count:         {len(history)}")


def command_packets_promotion_files(args):
    cfg = config_from_env()
    row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    route = read_routing(packet)
    print("LAIA Packet Promotion Files")
    print()
    print(f"Packet: {row_value(row, 'job_id', packet.name)}")
    raw_output_path = str(route.get("promotion_output_path", "") or "")
    if not raw_output_path:
        print("Promotion is sidecar-only; no promotion output folder.")
        return
    output_path = Path(raw_output_path).expanduser()
    if not output_path.exists() or not output_path.is_dir():
        print("Promotion output folder not found.")
        return
    rows = output_file_rows(output_path)
    if not rows:
        print("No promotion files found.")
        return
    print(f"Output: {output_path}")
    print_rows(["path", "bytes"], rows)


def command_packets_promotion_history(args):
    cfg = config_from_env()
    row, packet = route_row_for_identifier(args.identifier, cfg.db_path)
    route = read_routing(packet)
    print("LAIA Packet Promotion History")
    print()
    print(f"Packet: {row_value(row, 'job_id', packet.name)}")
    history = route.get("history") if isinstance(route.get("history"), list) else []
    promotion_events = [
        event for event in history
        if event.get("promotion_status") or event.get("route_status") == "promoted"
    ]
    if not promotion_events:
        print("No promotion recorded.")
        return
    for index, event in enumerate(promotion_events, start=1):
        text = f"{index}. {event.get('promotion_status', '')} {event.get('promotion_destination_type', '')} {event.get('promoted_at', '')}".rstrip()
        if event.get("promotion_result"):
            text += f" result={event.get('promotion_result')}"
        print(text)
        if event.get("promotion_output_path"):
            print(f"   output: {event.get('promotion_output_path')}")
        if event.get("note"):
            print(f"   note: {event.get('note')}")


def register_packets_subcommands(sub):
    packets_p = sub.add_parser("packets", help="Packet registry commands")
    packets_sub = packets_p.add_subparsers(dest="packets_command")

    packets_sub.add_parser("scan", help="Scan packet roots into the registry").set_defaults(func=command_packets_scan)
    packets_sub.add_parser("list", help="List registered packets").set_defaults(func=command_packets_list)

    queue_p = packets_sub.add_parser("queue", help="Show packet lifecycle queues")
    queue_p.add_argument("--status", default=None)
    queue_p.set_defaults(func=command_packets_queue)

    packets_sub.add_parser("attention", help="Show packets needing operator attention").set_defaults(func=command_packets_attention)
    packets_sub.add_parser("ready", help="Show packets ready for downstream use").set_defaults(func=command_packets_ready)
    packets_sub.add_parser("briefing", help="Show packet operator briefing").set_defaults(func=command_packets_briefing)

    lifecycle_p = packets_sub.add_parser("lifecycle", help="Show packet lifecycle summary")
    lifecycle_p.add_argument("identifier")
    lifecycle_p.set_defaults(func=command_packets_lifecycle)

    export_lifecycle_p = packets_sub.add_parser("export-lifecycle", help="Export packet lifecycle report files")
    export_lifecycle_p.add_argument("identifier")
    export_lifecycle_p.add_argument("--format", choices=["md", "json", "both"], default="both")
    export_lifecycle_p.add_argument("--output-dir", default=None)
    export_lifecycle_p.set_defaults(func=command_packets_export_lifecycle)

    export_lifecycles_p = packets_sub.add_parser("export-lifecycles", help="Export lifecycle reports for all registered packets")
    export_lifecycles_p.add_argument("--format", choices=["md", "json", "both"], default="both")
    export_lifecycles_p.add_argument("--output-root", default=None)
    export_lifecycles_p.set_defaults(func=command_packets_export_lifecycles)

    lifecycle_files_p = packets_sub.add_parser("lifecycle-files", help="Show packet lifecycle report files")
    lifecycle_files_p.add_argument("identifier")
    lifecycle_files_p.set_defaults(func=command_packets_lifecycle_files)

    inspect_p = packets_sub.add_parser("inspect", help="Inspect a registered packet")
    inspect_p.add_argument("identifier")
    inspect_p.set_defaults(func=command_packets_inspect)

    verify_p = packets_sub.add_parser("verify", help="Verify a registered packet")
    verify_p.add_argument("identifier")
    verify_p.set_defaults(func=command_packets_verify)

    packets_sub.add_parser("status", help="Show packet registry status").set_defaults(func=command_packets_status)
    packets_sub.add_parser("report", help="Show packet registry archive health report").set_defaults(func=command_packets_report)

    export_p = packets_sub.add_parser("export-csv", help="Export packet registry rows to CSV")
    export_p.add_argument("destination", nargs="?")
    export_p.set_defaults(func=command_packets_export_csv)

    open_p = packets_sub.add_parser("open", help="Open a packet folder")
    open_p.add_argument("identifier")
    open_p.set_defaults(func=command_packets_open)

    route_p = packets_sub.add_parser("route", help="Queue a packet for downstream routing")
    route_p.add_argument("identifier")
    route_p.add_argument("--to", dest="destination_type", required=True, choices=sorted(SUPPORTED_DESTINATION_TYPES))
    route_p.add_argument("--destination", default="")
    route_p.add_argument("--note", default="")
    route_p.set_defaults(func=command_packets_route)

    route_status_p = packets_sub.add_parser("route-status", help="Show packet routing sidecar")
    route_status_p.add_argument("identifier")
    route_status_p.set_defaults(func=command_packets_route_status)

    routes_p = packets_sub.add_parser("routes", help="List routed packets")
    routes_p.add_argument("--status", default=None)
    routes_p.set_defaults(func=command_packets_routes)

    clear_route_p = packets_sub.add_parser("clear-route", help="Clear a packet route")
    clear_route_p.add_argument("identifier")
    clear_route_p.add_argument("--note", default="")
    clear_route_p.set_defaults(func=command_packets_clear_route)

    execute_route_p = packets_sub.add_parser("execute-route", help="Execute one queued packet route")
    execute_route_p.add_argument("identifier")
    execute_route_p.add_argument("--dry-run", action="store_true")
    execute_route_p.set_defaults(func=command_packets_execute_route)

    execute_routes_p = packets_sub.add_parser("execute-routes", help="Execute all queued packet routes")
    execute_routes_p.add_argument("--dry-run", action="store_true")
    execute_routes_p.set_defaults(func=command_packets_execute_routes)

    route_history_p = packets_sub.add_parser("route-history", help="Show packet route history")
    route_history_p.add_argument("identifier")
    route_history_p.set_defaults(func=command_packets_route_history)

    output_p = packets_sub.add_parser("output", help="Show executed route output details")
    output_p.add_argument("identifier")
    output_p.set_defaults(func=command_packets_output)

    outputs_p = packets_sub.add_parser("outputs", help="List executed route outputs")
    outputs_p.add_argument("--status", choices=sorted(SUPPORTED_OUTPUT_REVIEW_STATUSES), default=None)
    outputs_p.add_argument("--type", dest="destination_type", choices=sorted(SUPPORTED_DESTINATION_TYPES), default=None)
    outputs_p.set_defaults(func=command_packets_outputs)

    output_files_p = packets_sub.add_parser("output-files", help="List files in an executed route output")
    output_files_p.add_argument("identifier")
    output_files_p.set_defaults(func=command_packets_output_files)

    review_output_p = packets_sub.add_parser("review-output", help="Mark an executed route output reviewed")
    review_output_p.add_argument("identifier")
    review_output_p.add_argument("--status", choices=sorted(SUPPORTED_OUTPUT_REVIEW_STATUSES), default="reviewed")
    review_output_p.add_argument("--note", default="")
    review_output_p.set_defaults(func=command_packets_review_output)

    output_history_p = packets_sub.add_parser("output-history", help="Show route execution output review history")
    output_history_p.add_argument("identifier")
    output_history_p.set_defaults(func=command_packets_output_history)

    promote_p = packets_sub.add_parser("promote", help="Promote a reviewed executed route output")
    promote_p.add_argument("identifier")
    promote_p.add_argument("--to", dest="destination_type", required=True, choices=sorted(SUPPORTED_PROMOTION_TYPES))
    promote_p.add_argument("--destination", default="")
    promote_p.add_argument("--note", default="")
    promote_p.add_argument("--dry-run", action="store_true")
    promote_p.set_defaults(func=command_packets_promote)

    promotions_p = packets_sub.add_parser("promotions", help="List packet output promotions")
    promotions_p.add_argument("--status", choices=["promoted", "held", "failed"], default=None)
    promotions_p.add_argument("--type", dest="destination_type", choices=sorted(SUPPORTED_PROMOTION_TYPES), default=None)
    promotions_p.set_defaults(func=command_packets_promotions)

    promotion_status_p = packets_sub.add_parser("promotion-status", help="Show packet promotion details")
    promotion_status_p.add_argument("identifier")
    promotion_status_p.set_defaults(func=command_packets_promotion_status)

    promotion_files_p = packets_sub.add_parser("promotion-files", help="List files in a promotion output")
    promotion_files_p.add_argument("identifier")
    promotion_files_p.set_defaults(func=command_packets_promotion_files)

    promotion_history_p = packets_sub.add_parser("promotion-history", help="Show packet promotion history")
    promotion_history_p.add_argument("identifier")
    promotion_history_p.set_defaults(func=command_packets_promotion_history)
