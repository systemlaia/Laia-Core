import json
import os
import sqlite3
import tempfile
import uuid
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from packets.registry import (
        PacketRoot,
        config_from_env,
        has_attention,
        is_ready,
        lifecycle_state_label,
        load_registry_rows,
        packet_project_link_entry,
        resolve_packet,
        project_registry_root,
        project_slug,
        print_rows,
        read_project_links,
        scan_roots,
        sync_packet_registry_record,
        upsert_packet_project_link,
        write_lifecycle_reports,
        write_project_links,
        row_value,
        utc_now,
    )
except ModuleNotFoundError:
    from core.packets.registry import (
        PacketRoot,
        config_from_env,
        has_attention,
        is_ready,
        lifecycle_state_label,
        load_registry_rows,
        packet_project_link_entry,
        resolve_packet,
        project_registry_root,
        project_slug,
        print_rows,
        read_project_links,
        scan_roots,
        sync_packet_registry_record,
        upsert_packet_project_link,
        write_lifecycle_reports,
        write_project_links,
        row_value,
        utc_now,
    )

PROJECT_JSON = "project.json"
PROJECT_PACKETS_JSON = "packets.json"
PROJECT_ARTIFACTS_JSON = "artifacts.json"
PROJECT_COHORTS_JSON = "cohorts.json"
PROJECT_VIDEO_EVIDENCE_JSON = "video_evidence.json"
PROJECT_MARKDOWN = "project.md"
PROJECT_NOTES_JSON = "notes.json"
PROJECT_NOTES_MARKDOWN = "notes.md"
PROJECT_TASKS_JSON = "tasks.json"
PROJECT_TASKS_MARKDOWN = "tasks.md"
NOTE_STATUSES = {"active", "archived"}
TASK_STATUSES = {"open", "in_progress", "blocked", "complete", "cancelled"}
TASK_PRIORITIES = {"low", "normal", "high", "urgent"}
PRIORITY_RANK = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
QUEUE_STATUS_RANK = {"blocked": 0, "in_progress": 1, "open": 2, "complete": 3, "cancelled": 4}
NEXT_STATUS_RANK = {"in_progress": 0, "open": 1}
CHECKLIST_STATUSES = {"open", "complete"}
ACTION_TYPES = {
    "manual",
    "packet_link",
    "artifact_link",
    "registry_scan",
    "lifecycle_export",
    "project_note",
    "task_log",
    "checklist_complete",
    "receipt_reconcile",
    "photo_edit_prepare",
    "photo_edit_add_source",
    "photo_edit_scan_exports",
    "photo_edit_verify",
    "photo_edit_package",
}
ACTION_STATUSES = {"none", "configured", "dry_run", "executed", "partial", "failed", "blocked"}


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        handle.write(text)
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def project_folder(project_id: str) -> Path:
    return project_registry_root() / project_id


def project_json_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_JSON


def project_packets_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_PACKETS_JSON


def project_artifacts_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_ARTIFACTS_JSON


def project_cohorts_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_COHORTS_JSON


def project_video_evidence_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_VIDEO_EVIDENCE_JSON


def project_markdown_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_MARKDOWN


def project_notes_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_NOTES_JSON


def project_notes_markdown_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_NOTES_MARKDOWN


def project_tasks_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_TASKS_JSON


def project_tasks_markdown_path(project_id: str) -> Path:
    return project_folder(project_id) / PROJECT_TASKS_MARKDOWN


def project_reconciliation_folder(project_id: str) -> Path:
    return project_folder(project_id) / "reconciliation"


def project_task_reports_folder(project_id: str) -> Path:
    return project_folder(project_id) / "task_reports"


def task_report_folder(project_id: str, task_identifier: str) -> Path:
    return project_task_reports_folder(project_id) / task_identifier


def normalize_project_identifier(identifier: str) -> str:
    return project_slug(identifier)


def list_project_ids() -> List[str]:
    root = project_registry_root()
    if not root.exists():
        return []
    return sorted([p.name for p in root.iterdir() if p.is_dir()])


def load_project(project_id: str) -> dict:
    path = project_json_path(project_id)
    if not path.exists():
        raise FileNotFoundError(f"Project record not found: {project_id}")
    return load_json(path)


def find_project(identifier: str) -> str:
    identifier = str(identifier).strip()
    if not identifier:
        raise FileNotFoundError("Project identifier is required.")
    project_id = normalize_project_identifier(identifier)
    candidate = project_folder(project_id)
    if candidate.exists() and candidate.is_dir() and project_json_path(project_id).exists():
        return project_id
    # fallback search by name or id
    for folder in (project_registry_root().glob("*")):
        if not folder.is_dir():
            continue
        record = load_json(folder / PROJECT_JSON)
        if not isinstance(record, dict):
            continue
        if str(record.get("project_id", "")).lower() == identifier.lower():
            return folder.name
        if str(record.get("name", "")).lower() == identifier.lower():
            return folder.name
    raise FileNotFoundError(f"Project not found: {identifier}")


def ensure_project_record(name: str, project_type: str = "project", status: str = "active", notes: str = "") -> dict:
    slug = normalize_project_identifier(name)
    record = load_json(project_json_path(slug))
    now = utc_now()
    if not record:
        record = {
            "project_id": slug,
            "name": name,
            "project_type": project_type,
            "status": status,
            "created_at": now,
            "updated_at": now,
            "notes": notes or "",
        }
    else:
        record["name"] = record.get("name", name)
        record["project_type"] = record.get("project_type", project_type)
        record["status"] = record.get("status", status)
        record["updated_at"] = now
        if notes:
            record["notes"] = notes
        record.setdefault("notes", "")
        record.setdefault("created_at", now)
    write_json(project_json_path(slug), record)
    markdown = project_markdown_path(slug)
    if not markdown.exists():
        markdown.write_text(f"# {record['name']}\n\n", encoding="utf-8")
    return record


def load_project_packets(project_id: str) -> dict:
    return load_json(project_packets_path(project_id)) or {"project_id": project_id, "packets": []}


def load_project_artifacts(project_id: str) -> dict:
    return load_json(project_artifacts_path(project_id)) or {"project_id": project_id, "artifacts": []}


def load_project_cohorts(project_id: str) -> dict:
    data = load_json(project_cohorts_path(project_id))
    if not data:
        data = {"project_id": project_id, "cohorts": []}
    data.setdefault("project_id", project_id)
    data.setdefault("cohorts", [])
    return data


def load_project_video_evidence(project_id: str) -> dict:
    data = load_json(project_video_evidence_path(project_id))
    if not data:
        data = {"project_id": project_id, "videos": []}
    data.setdefault("project_id", project_id)
    data.setdefault("videos", [])
    return data


def load_project_notes(project_id: str) -> dict:
    data = load_json(project_notes_path(project_id))
    if not data:
        data = {"project_id": project_id, "notes": []}
    data.setdefault("project_id", project_id)
    data.setdefault("notes", [])
    return data


def load_project_tasks(project_id: str) -> dict:
    data = load_json(project_tasks_path(project_id))
    if not data:
        data = {"project_id": project_id, "tasks": []}
    data.setdefault("project_id", project_id)
    data.setdefault("tasks", [])
    data["tasks"] = [ensure_task_context(task) for task in data.get("tasks", []) if isinstance(task, dict)]
    return data


def write_project_packets(project_id: str, data: dict) -> None:
    if data.get("project_id") != project_id:
        data["project_id"] = project_id
    write_json(project_packets_path(project_id), data)


def write_project_artifacts(project_id: str, data: dict) -> None:
    if data.get("project_id") != project_id:
        data["project_id"] = project_id
    write_json(project_artifacts_path(project_id), data)


def write_project_cohorts(project_id: str, data: dict) -> None:
    data["project_id"] = project_id
    data.setdefault("cohorts", [])
    write_json(project_cohorts_path(project_id), data)


def note_id() -> str:
    return f"note-{uuid.uuid4().hex[:12]}"


def task_id() -> str:
    return f"task-{uuid.uuid4().hex[:12]}"


def task_note_id() -> str:
    return f"task-note-{uuid.uuid4().hex[:12]}"


def checklist_item_id() -> str:
    return f"check-{uuid.uuid4().hex[:12]}"


def work_log_id() -> str:
    return f"log-{uuid.uuid4().hex[:12]}"


def validate_note_status(status: str) -> str:
    status = status or "active"
    if status not in NOTE_STATUSES:
        raise ValueError(f"Invalid note status: {status}")
    return status


def validate_task_status(status: str) -> str:
    if status not in TASK_STATUSES:
        raise ValueError(f"Invalid task status: {status}")
    return status


def validate_task_priority(priority: str) -> str:
    priority = priority or "normal"
    if priority not in TASK_PRIORITIES:
        raise ValueError(f"Invalid task priority: {priority}")
    return priority


def validate_checklist_status(status: str) -> str:
    if status not in CHECKLIST_STATUSES:
        raise ValueError(f"Invalid checklist status: {status}")
    return status


def ensure_task_context(task: dict) -> dict:
    task.setdefault("work_notes", [])
    task.setdefault("checklist", [])
    task["checklist"] = [ensure_checklist_item_context(item) for item in task.get("checklist", []) if isinstance(item, dict)]
    task.setdefault("work_log", [])
    task.setdefault("linked_packets", [])
    task.setdefault("linked_artifacts", [])
    task.setdefault("started_at", None)
    return task


def ensure_checklist_item_context(item: dict) -> dict:
    item.setdefault("history", [])
    item.setdefault("action", None)
    item.setdefault("action_status", "configured" if item.get("action") else "none")
    item.setdefault("action_result", None)
    item.setdefault("action_executed_at", None)
    item.setdefault("action_history", [])
    if not item["history"]:
        item["history"].append({
            "status": item.get("status", "open"),
            "timestamp": item.get("created_at", ""),
            "event": "created",
        })
    return item


def write_notes_markdown(project_id: str, notes_doc: dict) -> None:
    lines = [f"# Project Notes: {project_id}", ""]
    notes = notes_doc.get("notes", [])
    if not notes:
        lines.append("No notes.")
    for note in notes:
        lines.extend([
            f"## {note.get('note_id', '')}",
            "",
            f"- Status: {note.get('status', '')}",
            f"- Created: {note.get('created_at', '')}",
            f"- Updated: {note.get('updated_at', '')}",
            "",
            str(note.get("text", "")),
            "",
        ])
    project_notes_markdown_path(project_id).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_tasks_markdown(project_id: str, tasks_doc: dict) -> None:
    lines = [f"# Project Tasks: {project_id}", ""]
    tasks = tasks_doc.get("tasks", [])
    if not tasks:
        lines.append("No tasks.")
    for task in tasks:
        task = ensure_task_context(task)
        lines.extend([
            f"## {task.get('title', '')}",
            "",
            f"Task ID: {task.get('task_id', '')}",
            f"Status: {task.get('status', '')}",
            f"Priority: {task.get('priority', 'normal')}",
        ])
        if task.get("description"):
            lines.extend(["", str(task.get("description", ""))])
        if task.get("source_packet_id") or task.get("linked_packets"):
            lines.extend(["", "Linked Packets:"])
            packet_ids = list(dict.fromkeys(([task.get("source_packet_id")] if task.get("source_packet_id") else []) + task.get("linked_packets", [])))
            for packet_id in packet_ids:
                lines.append(f"- {packet_id}")
        if task.get("artifact_path") or task.get("linked_artifacts"):
            lines.extend(["", "Linked Artifacts:"])
            artifact_paths = list(dict.fromkeys(([task.get("artifact_path")] if task.get("artifact_path") else []) + task.get("linked_artifacts", [])))
            for artifact_path in artifact_paths:
                lines.append(f"- {artifact_path}")
        if task.get("checklist"):
            lines.extend(["", "Checklist:"])
            for item in task.get("checklist", []):
                marker = "x" if item.get("status") == "complete" else " "
                lines.append(f"- [{marker}] {item.get('text', '')}")
        active_notes = [note for note in task.get("work_notes", []) if note.get("status") == "active"]
        if active_notes:
            lines.extend(["", "Work Notes:"])
            for note in active_notes:
                lines.append(f"- {note.get('text', '')}")
        if task.get("work_log"):
            lines.extend(["", "Work Log:"])
            for log in task.get("work_log", [])[-5:]:
                lines.append(f"- {log.get('created_at', '')} {log.get('text', '')}")
        lines.append("")
    project_tasks_markdown_path(project_id).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_project_notes(project_id: str, data: dict) -> None:
    if data.get("project_id") != project_id:
        data["project_id"] = project_id
    write_json(project_notes_path(project_id), data)
    write_notes_markdown(project_id, data)


def write_project_tasks(project_id: str, data: dict) -> None:
    if data.get("project_id") != project_id:
        data["project_id"] = project_id
    write_json(project_tasks_path(project_id), data)
    write_tasks_markdown(project_id, data)


def project_notes(project_id: str, status: Optional[str] = None) -> List[dict]:
    notes = load_project_notes(project_id).get("notes", [])
    if status:
        notes = [note for note in notes if note.get("status") == status]
    return notes


def project_tasks(project_id: str, status: Optional[str] = None, priority: Optional[str] = None) -> List[dict]:
    tasks = load_project_tasks(project_id).get("tasks", [])
    if status:
        tasks = [task for task in tasks if task.get("status") == status]
    if priority:
        tasks = [task for task in tasks if task.get("priority") == priority]
    return tasks


def find_note(notes_doc: dict, identifier: str) -> dict:
    for note in notes_doc.get("notes", []):
        if note.get("note_id") == identifier:
            return note
    raise FileNotFoundError(f"Note not found: {identifier}")


def find_task(tasks_doc: dict, identifier: str) -> dict:
    for task in tasks_doc.get("tasks", []):
        if task.get("task_id") == identifier:
            return task
    raise FileNotFoundError(f"Task not found: {identifier}")


def add_project_note(project_id: str, text: str, status: str = "active") -> dict:
    if not text:
        raise ValueError("Note text is required.")
    status = validate_note_status(status)
    notes_doc = load_project_notes(project_id)
    now = utc_now()
    note = {
        "note_id": note_id(),
        "text": text,
        "created_at": now,
        "updated_at": now,
        "status": status,
    }
    notes_doc["notes"].append(note)
    write_project_notes(project_id, notes_doc)
    return note


def update_project_note(project_id: str, identifier: str, text: str) -> dict:
    if not text:
        raise ValueError("Note text is required.")
    notes_doc = load_project_notes(project_id)
    note = find_note(notes_doc, identifier)
    note["text"] = text
    note["updated_at"] = utc_now()
    write_project_notes(project_id, notes_doc)
    return note


def archive_project_note(project_id: str, identifier: str) -> dict:
    notes_doc = load_project_notes(project_id)
    note = find_note(notes_doc, identifier)
    note["status"] = "archived"
    note["updated_at"] = utc_now()
    write_project_notes(project_id, notes_doc)
    return note


def add_project_task(
    project_id: str,
    title: str,
    description: str = "",
    priority: str = "normal",
    source_packet_id: Optional[str] = None,
    artifact_path: Optional[str] = None,
) -> dict:
    if not title:
        raise ValueError("Task title is required.")
    priority = validate_task_priority(priority)
    tasks_doc = load_project_tasks(project_id)
    now = utc_now()
    task = {
        "task_id": task_id(),
        "title": title,
        "description": description or "",
        "status": "open",
        "priority": priority,
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "source_packet_id": source_packet_id,
        "artifact_path": artifact_path,
        "work_notes": [],
        "checklist": [],
        "work_log": [],
        "linked_packets": [],
        "linked_artifacts": [],
    }
    tasks_doc["tasks"].append(task)
    write_project_tasks(project_id, tasks_doc)
    return task


def update_project_task(project_id: str, identifier: str, updates: dict) -> dict:
    tasks_doc = load_project_tasks(project_id)
    task = find_task(tasks_doc, identifier)
    if "priority" in updates and updates["priority"] is not None:
        updates["priority"] = validate_task_priority(updates["priority"])
    for key in ["title", "description", "priority", "source_packet_id", "artifact_path"]:
        if key in updates and updates[key] is not None:
            task[key] = updates[key]
    task["updated_at"] = utc_now()
    write_project_tasks(project_id, tasks_doc)
    return task


def set_project_task_status(project_id: str, identifier: str, status: str, note: str = "") -> dict:
    status = validate_task_status(status)
    tasks_doc = load_project_tasks(project_id)
    task = find_task(tasks_doc, identifier)
    now = utc_now()
    task["status"] = status
    task["updated_at"] = now
    if status == "in_progress":
        if not task.get("started_at"):
            task["started_at"] = now
    if status == "complete":
        task["completed_at"] = now
    elif status == "open":
        task["completed_at"] = None
        task["started_at"] = None
    if note:
        if status == "blocked":
            task["block_note"] = note
        elif status == "complete":
            task["completion_note"] = note
        elif status == "cancelled":
            task["cancel_note"] = note
        else:
            task["note"] = note
    write_project_tasks(project_id, tasks_doc)
    return task


def project_task_summary(project_id: str) -> dict:
    tasks = project_tasks(project_id)
    counts = {status: 0 for status in ["open", "in_progress", "blocked", "complete", "cancelled"]}
    high_open = 0
    for task in tasks:
        status = task.get("status", "")
        if status in counts:
            counts[status] += 1
        if status in ("open", "in_progress", "blocked") and task.get("priority") in ("high", "urgent"):
            high_open += 1
    counts["high_urgent_open"] = high_open
    counts["total"] = len(tasks)
    return counts


def task_with_project(project_id: str, record: dict, task: dict) -> dict:
    row = dict(ensure_task_context(task))
    row["project_id"] = project_id
    row["project_name"] = record.get("name", "")
    row["project_type"] = record.get("project_type", "")
    row["project_status"] = record.get("status", "")
    return row


def all_project_task_rows() -> List[dict]:
    rows = []
    for project_id in list_project_ids():
        try:
            record = load_project(project_id)
            tasks = project_tasks(project_id)
        except Exception:
            continue
        for task in tasks:
            if isinstance(task, dict):
                rows.append(task_with_project(project_id, record, task))
    return rows


def resolve_project_filter(identifier: Optional[str]) -> Optional[str]:
    if not identifier:
        return None
    return find_project(identifier)


def task_text(row: dict) -> str:
    return "\n".join(
        str(row.get(key, ""))
        for key in ["task_id", "title", "description", "project_id", "project_name", "source_packet_id", "artifact_path", "block_note"]
    ).lower()


def checklist_progress(task: dict) -> str:
    task = ensure_task_context(task)
    total = len(task.get("checklist", []))
    complete = sum(1 for item in task.get("checklist", []) if item.get("status") == "complete")
    return f"{complete}/{total}"


def next_open_checklist_item(task: dict) -> Optional[dict]:
    task = ensure_task_context(task)
    for item in task.get("checklist", []):
        if item.get("status") == "open":
            return item
    return None


def task_suggested_next_step(task: dict) -> str:
    item = next_open_checklist_item(task)
    if item:
        action = item.get("action") or {}
        if action.get("action_type") and action.get("action_type") != "manual":
            return f"Run action: {action.get('action_type')}"
        return item.get("text", "")
    task = ensure_task_context(task)
    if task.get("checklist") and all(item.get("status") == "complete" for item in task.get("checklist", [])):
        return "Checklist complete."
    if task.get("description"):
        return task.get("description", "")
    return "Add a checklist item or work note."


def latest_work_log(task: dict) -> Optional[dict]:
    task = ensure_task_context(task)
    logs = task.get("work_log", [])
    return logs[-1] if logs else None


def filter_task_rows(rows: List[dict], filters: dict, default_active: bool = False) -> List[dict]:
    project_id = resolve_project_filter(filters.get("project"))
    text = str(filters.get("text", "") or "").lower()
    results = []
    for row in rows:
        if default_active and row.get("status") not in ("open", "in_progress", "blocked"):
            continue
        if project_id and row.get("project_id") != project_id:
            continue
        if filters.get("status") and row.get("status") != filters["status"]:
            continue
        if filters.get("priority") and row.get("priority") != filters["priority"]:
            continue
        if text and text not in task_text(row):
            continue
        results.append(row)
    return results


def sort_queue_rows(rows: List[dict]) -> List[dict]:
    return sorted(
        rows,
        key=lambda row: (
            PRIORITY_RANK.get(row.get("priority", "normal"), 99),
            QUEUE_STATUS_RANK.get(row.get("status", ""), 99),
            str(row.get("created_at") or row.get("updated_at") or ""),
            str(row.get("task_id", "")),
        ),
    )


def sort_next_rows(rows: List[dict]) -> List[dict]:
    return sorted(
        rows,
        key=lambda row: (
            PRIORITY_RANK.get(row.get("priority", "normal"), 99),
            NEXT_STATUS_RANK.get(row.get("status", ""), 99),
            str(row.get("created_at") or ""),
            str(row.get("task_id", "")),
        ),
    )


def project_queue_rows(filters: Optional[dict] = None) -> List[dict]:
    filters = filters or {}
    rows = filter_task_rows(all_project_task_rows(), filters, default_active=not bool(filters.get("status")))
    rows = sort_queue_rows(rows)
    limit = filters.get("limit")
    if limit:
        rows = rows[: int(limit)]
    return rows


def actionable_task_rows(project: Optional[str] = None) -> List[dict]:
    filters = {"project": project} if project else {}
    rows = filter_task_rows(all_project_task_rows(), filters, default_active=False)
    rows = [row for row in rows if row.get("status") in ("open", "in_progress")]
    return sort_next_rows(rows)


def queue_summary_data(rows: Optional[List[dict]] = None) -> dict:
    rows = rows if rows is not None else all_project_task_rows()
    counts = {status: 0 for status in ["open", "in_progress", "blocked", "complete", "cancelled"]}
    urgent_open = 0
    high_open = 0
    actionable_projects = set()
    open_checklist_items = 0
    tasks_with_work_logs = 0
    for row in rows:
        row = ensure_task_context(row)
        status = row.get("status", "")
        if status in counts:
            counts[status] += 1
        open_checklist_items += sum(1 for item in row.get("checklist", []) if item.get("status") == "open")
        if row.get("work_log"):
            tasks_with_work_logs += 1
        if status in ("open", "in_progress"):
            actionable_projects.add(row.get("project_id", ""))
            if row.get("priority") == "urgent":
                urgent_open += 1
            elif row.get("priority") == "high":
                high_open += 1
    counts["urgent_open"] = urgent_open
    counts["high_open"] = high_open
    counts["projects_with_actionable_tasks"] = len([project for project in actionable_projects if project])
    counts["actionable"] = counts["open"] + counts["in_progress"]
    counts["open_checklist_items"] = open_checklist_items
    counts["tasks_with_work_logs"] = tasks_with_work_logs
    return counts


def find_task_global(identifier: str) -> dict:
    matches = []
    for row in all_project_task_rows():
        if row.get("task_id") == identifier:
            matches.append(row)
    if len(matches) > 1:
        projects = ", ".join(sorted(row.get("project_id", "") for row in matches))
        raise ValueError(f"Duplicate task ID found across projects: {identifier} ({projects})")
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Task not found: {identifier}")


def resolve_task_location(task_identifier: str, project: Optional[str] = None):
    if project:
        project_id = find_project(project)
        tasks_doc = load_project_tasks(project_id)
        task = find_task(tasks_doc, task_identifier)
        record = load_project(project_id)
        return project_id, record, tasks_doc, task
    row = find_task_global(task_identifier)
    project_id = row.get("project_id", "")
    tasks_doc = load_project_tasks(project_id)
    task = find_task(tasks_doc, task_identifier)
    record = load_project(project_id)
    return project_id, record, tasks_doc, task


def find_task_note(task: dict, note_identifier: str) -> dict:
    for note in ensure_task_context(task).get("work_notes", []):
        if note.get("note_id") == note_identifier:
            return note
    raise FileNotFoundError(f"Task note not found: {note_identifier}")


def find_checklist_item(task: dict, item_identifier: str) -> dict:
    for item in ensure_task_context(task).get("checklist", []):
        if item.get("item_id") == item_identifier:
            return item
    raise FileNotFoundError(f"Checklist item not found: {item_identifier}")


def add_task_work_note(task_identifier: str, text: str, project: Optional[str] = None, status: str = "active") -> dict:
    if not text:
        raise ValueError("Task note text is required.")
    status = validate_note_status(status)
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    now = utc_now()
    note = {"note_id": task_note_id(), "text": text, "created_at": now, "updated_at": now, "status": status}
    ensure_task_context(task)["work_notes"].append(note)
    task["updated_at"] = now
    write_project_tasks(project_id, tasks_doc)
    result = dict(note)
    result.update({"task_id": task.get("task_id", ""), "project_id": project_id, "project_name": record.get("name", "")})
    return result


def task_work_notes(task_identifier: str, project: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
    _project_id, _record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    notes = ensure_task_context(task).get("work_notes", [])
    if status:
        notes = [note for note in notes if note.get("status") == status]
    return notes


def update_task_work_note(task_identifier: str, note_identifier: str, text: str, project: Optional[str] = None) -> dict:
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    note = find_task_note(task, note_identifier)
    note["text"] = text
    note["updated_at"] = utc_now()
    task["updated_at"] = note["updated_at"]
    write_project_tasks(project_id, tasks_doc)
    result = dict(note)
    result.update({"task_id": task.get("task_id", ""), "project_id": project_id, "project_name": record.get("name", "")})
    return result


def archive_task_work_note(task_identifier: str, note_identifier: str, project: Optional[str] = None) -> dict:
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    note = find_task_note(task, note_identifier)
    note["status"] = "archived"
    note["updated_at"] = utc_now()
    task["updated_at"] = note["updated_at"]
    write_project_tasks(project_id, tasks_doc)
    result = dict(note)
    result.update({"task_id": task.get("task_id", ""), "project_id": project_id, "project_name": record.get("name", "")})
    return result


def add_task_checklist_item(task_identifier: str, text: str, project: Optional[str] = None) -> dict:
    if not text:
        raise ValueError("Checklist text is required.")
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    now = utc_now()
    item = {
        "item_id": checklist_item_id(),
        "text": text,
        "status": "open",
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "history": [{"status": "open", "timestamp": now, "event": "created"}],
    }
    ensure_task_context(task)["checklist"].append(item)
    task["updated_at"] = now
    write_project_tasks(project_id, tasks_doc)
    result = dict(item)
    result.update({"task_id": task.get("task_id", ""), "project_id": project_id, "project_name": record.get("name", "")})
    return result


def task_checklist_items(task_identifier: str, project: Optional[str] = None, status: Optional[str] = None) -> List[dict]:
    _project_id, _record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    items = ensure_task_context(task).get("checklist", [])
    if status:
        status = validate_checklist_status(status)
        items = [item for item in items if item.get("status") == status]
    return items


def update_task_checklist_item(task_identifier: str, item_identifier: str, text: str, project: Optional[str] = None) -> dict:
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    item = find_checklist_item(task, item_identifier)
    item["text"] = text
    item["updated_at"] = utc_now()
    task["updated_at"] = item["updated_at"]
    write_project_tasks(project_id, tasks_doc)
    result = dict(item)
    result.update({"task_id": task.get("task_id", ""), "project_id": project_id, "project_name": record.get("name", "")})
    return result


def set_task_checklist_status(task_identifier: str, item_identifier: str, status: str, project: Optional[str] = None) -> dict:
    status = validate_checklist_status(status)
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    item = find_checklist_item(task, item_identifier)
    now = utc_now()
    ensure_checklist_item_context(item)
    item["status"] = status
    item["updated_at"] = now
    item["completed_at"] = now if status == "complete" else None
    item["history"].append({
        "status": status,
        "timestamp": now,
        "event": "completed" if status == "complete" else "reopened",
    })
    task["updated_at"] = now
    write_project_tasks(project_id, tasks_doc)
    result = dict(item)
    result.update({"task_id": task.get("task_id", ""), "project_id": project_id, "project_name": record.get("name", "")})
    return result


def add_task_work_log(task_identifier: str, text: str, project: Optional[str] = None) -> dict:
    if not text:
        raise ValueError("Work log text is required.")
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    now = utc_now()
    log = {"log_id": work_log_id(), "text": text, "created_at": now}
    ensure_task_context(task)["work_log"].append(log)
    task["updated_at"] = now
    write_project_tasks(project_id, tasks_doc)
    result = dict(log)
    result.update({"task_id": task.get("task_id", ""), "project_id": project_id, "project_name": record.get("name", "")})
    return result


def task_work_logs(task_identifier: str, project: Optional[str] = None) -> List[dict]:
    _project_id, _record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    return ensure_task_context(task).get("work_log", [])


def link_packet_to_task(task_identifier: str, packet_id: str, project: Optional[str] = None) -> dict:
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    if packet_id not in task["linked_packets"]:
        task["linked_packets"].append(packet_id)
    if not task.get("source_packet_id"):
        task["source_packet_id"] = packet_id
    task["updated_at"] = utc_now()
    write_project_tasks(project_id, tasks_doc)
    return task_with_project(project_id, record, task)


def link_artifact_to_task(task_identifier: str, artifact_path: str, project: Optional[str] = None) -> dict:
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    artifact_path = str(Path(artifact_path).expanduser())
    if artifact_path not in task["linked_artifacts"]:
        task["linked_artifacts"].append(artifact_path)
    if not task.get("artifact_path"):
        task["artifact_path"] = artifact_path
    task["updated_at"] = utc_now()
    write_project_tasks(project_id, tasks_doc)
    return task_with_project(project_id, record, task)


def task_context_data(task_identifier: str, project: Optional[str] = None) -> dict:
    project_id, record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    return {
        "task": task_with_project(project_id, record, task),
        "checklist_progress": checklist_progress(task),
        "suggested_next_step": task_suggested_next_step(task),
    }


def task_next_step_data(task_identifier: str, project: Optional[str] = None) -> dict:
    project_id, record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    item = next_open_checklist_item(task)
    no_next = False
    if item:
        step_text = item.get("text", "")
        item_id = item.get("item_id", "")
        action = item.get("action") or {}
    elif task.get("status") in ("complete", "cancelled"):
        step_text = "No next step defined."
        item_id = ""
        action = {}
        no_next = True
    elif task.get("description"):
        step_text = task.get("description", "")
        item_id = ""
        action = {}
    else:
        step_text = "No next step defined."
        item_id = ""
        action = {}
        no_next = True
    return {
        "task_id": task.get("task_id", ""),
        "project_id": project_id,
        "project_name": record.get("name", ""),
        "title": task.get("title", ""),
        "item_id": item_id,
        "step_text": step_text,
        "checklist_progress": checklist_progress(task),
        "task_status": task.get("status", ""),
        "priority": task.get("priority", ""),
        "no_next_step": no_next,
        "action_type": action.get("action_type", ""),
        "action_status": item.get("action_status", "") if item else "",
    }


def active_next_step_data(project: Optional[str] = None) -> Optional[dict]:
    in_progress = project_queue_rows({"status": "in_progress", "project": project})
    if in_progress:
        row = in_progress[0]
        return task_next_step_data(row.get("task_id", ""), row.get("project_id", ""))
    open_rows = [row for row in actionable_task_rows(project) if row.get("status") == "open"]
    if open_rows:
        row = open_rows[0]
        return task_next_step_data(row.get("task_id", ""), row.get("project_id", ""))
    return None


def complete_next_checklist_item(
    task_identifier: str,
    project: Optional[str] = None,
    log_text: Optional[str] = None,
    note_text: Optional[str] = None,
    complete_task: bool = False,
) -> dict:
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    item = next_open_checklist_item(task)
    before_progress = checklist_progress(task)
    if not item:
        return {
            "task": task_with_project(project_id, record, task),
            "mutated": False,
            "message": "No open checklist items.",
            "checklist_progress": before_progress,
            "next_item": None,
        }
    now = utc_now()
    ensure_checklist_item_context(item)
    item["status"] = "complete"
    item["updated_at"] = now
    item["completed_at"] = now
    item["history"].append({"status": "complete", "timestamp": now, "event": "completed"})
    task["updated_at"] = now
    log_entry_text = log_text or f"Completed checklist item: {item.get('text', '')}"
    task["work_log"].append({"log_id": work_log_id(), "text": log_entry_text, "created_at": now})
    if note_text:
        task["work_notes"].append({"note_id": task_note_id(), "text": note_text, "created_at": now, "updated_at": now, "status": "active"})
    next_item = next_open_checklist_item(task)
    completed_task = False
    task_completion_refused = False
    if complete_task:
        if next_item:
            task_completion_refused = True
        else:
            task["status"] = "complete"
            task["completed_at"] = now
            task["work_log"].append({"log_id": work_log_id(), "text": "Completed final checklist item and completed task.", "created_at": now})
            completed_task = True
    write_project_tasks(project_id, tasks_doc)
    return {
        "task": task_with_project(project_id, record, task),
        "mutated": True,
        "completed_item": dict(item),
        "checklist_progress": checklist_progress(task),
        "next_item": dict(next_item) if next_item else None,
        "log_text": log_entry_text,
        "completed_task": completed_task,
        "task_completion_refused": task_completion_refused,
    }


def task_step_history_data(task_identifier: str, project: Optional[str] = None) -> dict:
    project_id, record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    entries = []
    for item in task.get("checklist", []):
        item = ensure_checklist_item_context(item)
        for event in item.get("history", []):
            row = dict(event)
            row.update({"item_id": item.get("item_id", ""), "text": item.get("text", "")})
            entries.append(row)
    return {"task": task_with_project(project_id, record, task), "history": entries}


def validate_action(action_type: str, parameters: dict) -> dict:
    if action_type not in ACTION_TYPES:
        raise ValueError(f"Unsupported action type: {action_type}")
    parameters = parameters or {}
    if not isinstance(parameters, dict):
        raise ValueError("Action parameters must be an object.")
    required = {
        "packet_link": ["project", "packet_ids"],
        "artifact_link": ["project", "artifact_paths"],
        "lifecycle_export": ["packet_ids"],
        "project_note": ["project", "text"],
        "task_log": ["text"],
        "checklist_complete": ["target_item_id"],
        "receipt_reconcile": ["project", "packet_ids"],
        "photo_edit_prepare": ["project"],
        "photo_edit_add_source": ["project", "packet", "cohort"],
        "photo_edit_scan_exports": ["project"],
        "photo_edit_verify": ["project"],
        "photo_edit_package": ["project"],
    }.get(action_type, [])
    for key in required:
        if key not in parameters or parameters[key] in ("", None, []):
            raise ValueError(f"Missing required action parameter: {key}")
    if action_type in ("packet_link", "lifecycle_export", "receipt_reconcile") and not isinstance(parameters.get("packet_ids", []), list):
        raise ValueError("packet_ids must be a list.")
    if action_type == "artifact_link" and not isinstance(parameters.get("artifact_paths", []), list):
        raise ValueError("artifact_paths must be a list.")
    if action_type == "lifecycle_export" and parameters.get("format", "both") not in ("md", "json", "both"):
        raise ValueError("format must be md, json, or both.")
    return {"action_type": action_type, "parameters": parameters}


def action_history_event(event: str, action_type: str = "", result: Optional[dict] = None, detail: str = "") -> dict:
    return {
        "timestamp": utc_now(),
        "event": event,
        "action_type": action_type,
        "result": result or {},
        "detail": detail,
    }


def set_checklist_action(task_identifier: str, item_identifier: str, action_type: str, parameters: dict, project: Optional[str] = None) -> dict:
    action = validate_action(action_type, parameters)
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    item = find_checklist_item(task, item_identifier)
    ensure_checklist_item_context(item)
    item["action"] = action
    item["action_status"] = "configured"
    item["action_result"] = None
    item["action_executed_at"] = None
    item["action_history"].append(action_history_event("configured", action_type, detail="action configured"))
    task["updated_at"] = utc_now()
    write_project_tasks(project_id, tasks_doc)
    return {"task": task_with_project(project_id, record, task), "item": item}


def clear_checklist_action(task_identifier: str, item_identifier: str, project: Optional[str] = None) -> dict:
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    item = find_checklist_item(task, item_identifier)
    ensure_checklist_item_context(item)
    old_type = (item.get("action") or {}).get("action_type", "")
    item["action"] = None
    item["action_status"] = "none"
    item["action_result"] = None
    item["action_executed_at"] = None
    item["action_history"].append(action_history_event("cleared", old_type, detail="action cleared"))
    task["updated_at"] = utc_now()
    write_project_tasks(project_id, tasks_doc)
    return {"task": task_with_project(project_id, record, task), "item": item}


def checklist_action_data(task_identifier: str, item_identifier: str, project: Optional[str] = None) -> dict:
    project_id, record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    item = find_checklist_item(task, item_identifier)
    ensure_checklist_item_context(item)
    return {"task": task_with_project(project_id, record, task), "item": item}


def action_result(status: str, action_type: str, summary: str, details: Optional[List[dict]] = None, started_at: Optional[str] = None) -> dict:
    completed_at = utc_now()
    return {
        "status": status,
        "action_type": action_type,
        "started_at": started_at or completed_at,
        "completed_at": completed_at,
        "summary": summary,
        "details": details or [],
    }


RECEIPT_RECONCILE_FIELDS = ("merchant", "transaction_date", "subtotal", "tax", "tip", "total", "currency")
RECEIPT_NUMERIC_FIELDS = ("subtotal", "tax", "tip", "total")


def decimal_string(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.01")))


def parse_receipt_decimal(value: Any) -> Optional[Decimal]:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip().replace("$", "").replace(",", "")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        raise ValueError(f"Invalid numeric value: {value}")


def read_receipt_extract(packet: Path) -> tuple[dict, dict]:
    extract_path = Path(packet) / "extract" / "extract.json"
    if not extract_path.exists():
        raise FileNotFoundError(f"Missing extract sidecar: {extract_path}")
    extraction = load_json(extract_path)
    correction = load_json(Path(packet) / "extract" / "correction.json")
    fields = dict(extraction.get("fields") or {})
    corrected_fields = []
    for field, item in (correction.get("corrections") or {}).items():
        if isinstance(item, dict):
            fields[field] = item.get("corrected")
            corrected_fields.append(field)
    return fields, {"corrected_fields": corrected_fields}


def receipt_reconciliation_markdown(report: dict) -> str:
    lines = [
        "# LAIA Receipt Reconciliation",
        "",
        f"Project: {report.get('project_id', '')}",
        f"Generated At: {report.get('generated_at', '')}",
        f"Currency: {report.get('currency', '')}",
        "",
        "Summary:",
        f"- Packets: {report.get('packet_count', 0)}",
        f"- Valid totals: {report.get('valid_total_count', 0)}",
        f"- Missing totals: {report.get('missing_total_count', 0)}",
        f"- Invalid totals: {report.get('invalid_total_count', 0)}",
        f"- Grand total: {report.get('grand_total', '0.00')}",
        "",
        "Receipts:",
        "",
        "| Packet | Merchant | Date | Total | Source |",
        "| --- | --- | --- | --- | --- |",
    ]
    for receipt in report.get("receipts", []):
        lines.append(
            f"| {receipt.get('packet_id', '')} | {receipt.get('merchant', '')} | "
            f"{receipt.get('transaction_date', '')} | {receipt.get('total', '')} | "
            f"{receipt.get('value_source', '')} |"
        )
    lines.extend(["", "Warnings:"])
    if report.get("warnings"):
        for warning in report["warnings"]:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    return "\n".join(lines).rstrip() + "\n"


def receipt_reconciliation_paths(project_id: str, output_name: str) -> tuple[Path, Path]:
    safe_name = project_slug(output_name or "receipt-reconciliation")
    folder = project_reconciliation_folder(project_id)
    return folder / f"{safe_name}.json", folder / f"{safe_name}.md"


def write_receipt_reconciliation_report(project_id: str, report: dict, output_name: str) -> tuple[Path, Path]:
    json_path, md_path = receipt_reconciliation_paths(project_id, output_name)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(receipt_reconciliation_markdown(report), encoding="utf-8")
    return json_path, md_path


def build_receipt_reconciliation(parameters: dict) -> tuple[dict, str]:
    project_id = find_project(parameters["project"])
    cfg = config_from_env()
    currency = str(parameters.get("currency") or "USD")
    warnings = []
    receipts = []
    valid_total_count = 0
    missing_total_count = 0
    invalid_total_count = 0
    resolved_count = 0
    grand_total = Decimal("0.00")
    for packet_id in parameters.get("packet_ids", []):
        try:
            row = resolve_packet(packet_id, cfg.db_path)
        except Exception as exc:
            warnings.append(f"{packet_id}: packet not found ({exc})")
            continue
        resolved_count += 1
        packet_type = row_value(row, "packet_type", "")
        packet_path = Path(row_value(row, "packet_path", ""))
        if packet_type != "laia.paper_ingest":
            warnings.append(f"{packet_id}: unsupported packet type {packet_type}")
            continue
        try:
            fields, meta = read_receipt_extract(packet_path)
        except Exception as exc:
            warnings.append(f"{packet_id}: {exc}")
            missing_total_count += 1
            continue
        receipt = {"packet_id": row_value(row, "job_id", packet_id)}
        for field in RECEIPT_RECONCILE_FIELDS:
            receipt[field] = fields.get(field)
        corrected_fields = meta.get("corrected_fields", [])
        receipt["value_source"] = "corrected" if "total" in corrected_fields else "raw"
        total_value = fields.get("total")
        if total_value is None or str(total_value).strip() == "":
            missing_total_count += 1
            warnings.append(f"{packet_id}: total missing")
            receipt["total"] = ""
            receipts.append(receipt)
            continue
        try:
            parsed_total = parse_receipt_decimal(total_value)
            for field in RECEIPT_NUMERIC_FIELDS:
                if fields.get(field) not in (None, ""):
                    parse_receipt_decimal(fields.get(field))
        except ValueError as exc:
            invalid_total_count += 1
            warnings.append(f"{packet_id}: {exc}")
            receipts.append(receipt)
            continue
        valid_total_count += 1
        grand_total += parsed_total or Decimal("0.00")
        receipt["total"] = decimal_string(parsed_total or Decimal("0.00"))
        receipts.append(receipt)
    if resolved_count == 0:
        raise FileNotFoundError("No receipt packets resolved.")
    report = {
        "report_type": "laia.receipt_reconciliation",
        "report_version": "0.1",
        "project_id": project_id,
        "generated_at": utc_now(),
        "currency": currency,
        "packet_count": resolved_count,
        "valid_total_count": valid_total_count,
        "missing_total_count": missing_total_count,
        "invalid_total_count": invalid_total_count,
        "grand_total": decimal_string(grand_total),
        "receipts": receipts,
        "warnings": warnings,
    }
    status = "partial" if warnings or missing_total_count or invalid_total_count else "executed"
    return report, status


def dry_run_action_plan(action_type: str, parameters: dict) -> dict:
    details = []
    if action_type == "packet_link":
        details = [{"operation": "link_packet", "target": packet_id, "project": parameters.get("project", "")} for packet_id in parameters.get("packet_ids", [])]
    elif action_type == "artifact_link":
        details = [{"operation": "link_artifact", "target": path, "project": parameters.get("project", "")} for path in parameters.get("artifact_paths", [])]
    elif action_type == "registry_scan":
        details = [{"operation": "registry_scan", "target": root} for root in parameters.get("roots", ["configured roots"])]
    elif action_type == "lifecycle_export":
        details = [{"operation": "lifecycle_export", "target": packet_id, "format": parameters.get("format", "both")} for packet_id in parameters.get("packet_ids", [])]
    elif action_type == "project_note":
        details = [{"operation": "project_note", "project": parameters.get("project", ""), "text": parameters.get("text", "")}]
    elif action_type == "task_log":
        details = [{"operation": "task_log", "text": parameters.get("text", "")}]
    elif action_type == "checklist_complete":
        details = [{"operation": "checklist_complete", "target": parameters.get("target_item_id", "")}]
    elif action_type == "receipt_reconcile":
        details = [{"operation": "receipt_reconcile", "target": packet_id, "project": parameters.get("project", "")} for packet_id in parameters.get("packet_ids", [])]
    elif action_type in {"photo_edit_prepare", "photo_edit_add_source", "photo_edit_scan_exports", "photo_edit_verify", "photo_edit_package"}:
        details = [{"operation": action_type, "project": parameters.get("project", "")}]
    elif action_type == "manual":
        details = [{"operation": "manual"}]
    return action_result("dry_run", action_type, f"Dry run for {action_type}.", details)


def execute_action_impl(action_type: str, parameters: dict, task_identifier: str, project_id: str, task: dict) -> dict:
    started_at = utc_now()
    details = []
    if action_type == "manual":
        return action_result("blocked", action_type, "Manual action; operator completion required.", started_at=started_at)
    if action_type == "packet_link":
        target_project = find_project(parameters["project"])
        target_record = load_project(target_project)
        successes = 0
        for packet_id in parameters.get("packet_ids", []):
            try:
                row = resolve_packet(packet_id, config_from_env().db_path)
                packet_path = Path(row_value(row, "packet_path", ""))
                linked_at = utc_now()
                packet_info = {"job_id": row_value(row, "job_id", packet_id), "packet_type": row_value(row, "packet_type", ""), "packet_path": row_value(row, "packet_path", "")}
                add_packet_to_project(target_project, packet_info, linked_at)
                artifact = parameters.get("artifact")
                if artifact:
                    add_artifact_to_project(target_project, artifact, packet_info["job_id"], linked_at, parameters.get("artifact_type", "promoted_output"))
                if packet_path.exists():
                    entry = packet_project_link_entry(packet_path, target_project, target_record.get("name", target_project), target_record.get("project_type", "project"), project_folder(target_project), artifact, linked_at)
                    upsert_packet_project_link(packet_path, entry)
                    sync_packet_registry_record(packet_path, config_from_env().db_path)
                successes += 1
                details.append({"target": packet_id, "status": "linked"})
            except Exception as exc:
                details.append({"target": packet_id, "status": "failed", "error": str(exc)})
        status = "executed" if successes == len(parameters.get("packet_ids", [])) else ("partial" if successes else "failed")
        return action_result(status, action_type, f"Linked {successes} packet to project {target_project}.", details, started_at)
    if action_type == "artifact_link":
        target_project = find_project(parameters["project"])
        source_packet_id = parameters.get("source_packet_id", "")
        artifact_type = parameters.get("artifact_type", "promoted_output")
        successes = 0
        for artifact_path in parameters.get("artifact_paths", []):
            try:
                add_artifact_to_project(target_project, artifact_path, source_packet_id, utc_now(), artifact_type)
                details.append({"target": artifact_path, "status": "linked", "artifact_type": artifact_type})
                successes += 1
            except Exception as exc:
                details.append({"target": artifact_path, "status": "failed", "error": str(exc)})
        status = "executed" if successes == len(parameters.get("artifact_paths", [])) else ("partial" if successes else "failed")
        return action_result(status, action_type, f"Linked {successes} artifact to project {target_project}.", details, started_at)
    if action_type == "registry_scan":
        cfg = config_from_env()
        roots = cfg.roots
        if parameters.get("roots"):
            roots = tuple(PacketRoot(name=f"root{index}", path=Path(root).expanduser()) for index, root in enumerate(parameters["roots"], start=1))
        count = scan_roots(cfg.db_path, roots)
        return action_result("executed", action_type, f"Scanned packet roots; indexed {count} packets.", [{"indexed": count}], started_at)
    if action_type == "lifecycle_export":
        cfg = config_from_env()
        fmt = parameters.get("format", "both")
        output_root = parameters.get("output_root")
        successes = 0
        for packet_id in parameters.get("packet_ids", []):
            try:
                row = resolve_packet(packet_id, cfg.db_path)
                packet = Path(row_value(row, "packet_path", ""))
                output_dir = str(Path(output_root).expanduser() / packet_id) if output_root else None
                paths = write_lifecycle_reports(row, packet, report_format=fmt, output_dir=output_dir)
                details.append({"target": packet_id, "status": "exported", "output_dir": str(paths.get("output_dir", ""))})
                successes += 1
            except Exception as exc:
                details.append({"target": packet_id, "status": "failed", "error": str(exc)})
        status = "executed" if successes == len(parameters.get("packet_ids", [])) else ("partial" if successes else "failed")
        return action_result(status, action_type, f"Exported lifecycle reports for {successes} packets.", details, started_at)
    if action_type == "project_note":
        project_note = add_project_note(find_project(parameters["project"]), parameters["text"], parameters.get("status", "active"))
        return action_result("executed", action_type, f"Added project note {project_note['note_id']}.", [{"note_id": project_note["note_id"]}], started_at)
    if action_type == "task_log":
        log = {"log_id": work_log_id(), "text": parameters["text"], "created_at": utc_now()}
        ensure_task_context(task)["work_log"].append(log)
        return action_result("executed", action_type, f"Added task log {log['log_id']}.", [{"log_id": log["log_id"]}], started_at)
    if action_type == "checklist_complete":
        target_item_id = parameters["target_item_id"]
        if target_item_id == parameters.get("_current_item_id"):
            return action_result("failed", action_type, "Refusing to complete current checklist item recursively.", started_at=started_at)
        item = find_checklist_item(task, target_item_id)
        if item.get("status") == "complete":
            return action_result("executed", action_type, f"Checklist item already complete: {target_item_id}.", [{"target": target_item_id, "status": "already_complete"}], started_at)
        now = utc_now()
        ensure_checklist_item_context(item)
        item["status"] = "complete"
        item["updated_at"] = now
        item["completed_at"] = now
        item["history"].append({"status": "complete", "timestamp": now, "event": "completed"})
        return action_result("executed", action_type, f"Completed checklist item {target_item_id}.", [{"target": target_item_id, "status": "complete"}], started_at)
    if action_type == "receipt_reconcile":
        report, status = build_receipt_reconciliation(parameters)
        output_name = parameters.get("output_name") or "receipt-reconciliation"
        json_path, md_path = write_receipt_reconciliation_report(report["project_id"], report, output_name)
        details = [{
            "json_path": str(json_path),
            "md_path": str(md_path),
            "packet_count": report.get("packet_count", 0),
            "grand_total": report.get("grand_total", "0.00"),
            "warnings": report.get("warnings", []),
        }]
        if status == "executed":
            summary = f"Reconciled {report.get('packet_count', 0)} receipt packets. Grand total: ${report.get('grand_total', '0.00')}."
        else:
            summary = f"Receipt reconciliation report created with {len(report.get('warnings', []))} warnings."
        return action_result(status, action_type, summary, details, started_at)
    if action_type in {"photo_edit_prepare", "photo_edit_add_source", "photo_edit_scan_exports", "photo_edit_verify", "photo_edit_package"}:
        try:
            from projects import sale_items
        except (ImportError, ModuleNotFoundError):
            from core.projects import sale_items
        target = parameters["project"]
        if action_type == "photo_edit_prepare":
            result = sale_items.prepare_photo_edit(
                target,
                cohort=parameters.get("cohort"),
                copy_mode=parameters.get("copy_mode", "copy"),
            )
            detail = {"workspace": result["manifest"]["workspace_path"], "copied": result["copied"]}
        elif action_type == "photo_edit_add_source":
            result = sale_items.add_photo_edit_source(
                target,
                packet=parameters["packet"],
                cohort=parameters["cohort"],
                copy_mode=parameters.get("copy_mode", "copy"),
            )
            detail = result
        elif action_type == "photo_edit_scan_exports":
            result = sale_items.scan_exports(target)
            detail = result
        elif action_type == "photo_edit_verify":
            result = sale_items.verify_photo_edit(target)
            detail = result
            if not result["success"]:
                return action_result("failed", action_type, "Photo edit verification failed.", [detail], started_at)
        else:
            result = sale_items.package_photos(target)
            detail = result
        return action_result("executed", action_type, f"Executed {action_type}.", [detail], started_at)
    return action_result("failed", action_type, f"Unsupported action type: {action_type}.", started_at=started_at)


def action_work_log_text(result: dict) -> str:
    action_type = result.get("action_type", "")
    summary = result.get("summary", "")
    if action_type == "receipt_reconcile":
        return summary
    if result.get("status") == "executed":
        return f"Executed checklist action {action_type}: {summary}"
    if result.get("status") == "partial":
        return f"Checklist action {action_type} partially completed: {summary}"
    return f"Checklist action {action_type} failed: {summary}"


def complete_checklist_item_in_place(item: dict, now: str) -> None:
    ensure_checklist_item_context(item)
    item["status"] = "complete"
    item["updated_at"] = now
    item["completed_at"] = now
    item["history"].append({"status": "complete", "timestamp": now, "event": "completed"})


def run_checklist_action(
    task_identifier: str,
    item_identifier: str,
    project: Optional[str] = None,
    dry_run: bool = False,
    complete_on_success: bool = True,
) -> dict:
    project_id, record, tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    item = find_checklist_item(task, item_identifier)
    item = ensure_checklist_item_context(item)
    action = item.get("action")
    if item.get("status") != "open":
        return {
            "task": task_with_project(project_id, record, task),
            "item": dict(item),
            "mutated": False,
            "message": "Checklist item is not open.",
            "result": action_result("blocked", (action or {}).get("action_type", ""), "Checklist item is not open."),
        }
    if not action:
        return {
            "task": task_with_project(project_id, record, task),
            "item": dict(item),
            "mutated": False,
            "message": "No action configured.",
            "result": action_result("blocked", "", "No action configured."),
        }
    action = validate_action(action.get("action_type", ""), action.get("parameters", {}))
    action_type = action["action_type"]
    parameters = dict(action.get("parameters", {}))
    parameters["_current_item_id"] = item_identifier
    if action_type == "manual":
        return {
            "task": task_with_project(project_id, record, task),
            "item": dict(item),
            "mutated": False,
            "message": "Manual action; operator completion required.",
            "result": action_result("blocked", action_type, "Manual action; operator completion required."),
        }
    if dry_run:
        result = dry_run_action_plan(action_type, parameters)
        return {
            "task": task_with_project(project_id, record, task),
            "item": dict(item),
            "mutated": False,
            "dry_run": True,
            "result": result,
        }

    try:
        result = execute_action_impl(action_type, parameters, task_identifier, project_id, task)
    except Exception as exc:
        result = action_result("failed", action_type, str(exc), [{"error": str(exc)}])

    now = utc_now()
    item["action_status"] = result.get("status", "failed")
    item["action_result"] = result
    item["action_executed_at"] = result.get("completed_at") or now
    item["action_history"].append(action_history_event("executed", action_type, result=result))
    if result.get("status") in ("executed", "partial", "failed"):
        task["work_log"].append({"log_id": work_log_id(), "text": action_work_log_text(result), "created_at": now})
    completed_item = False
    if result.get("status") == "executed" and complete_on_success:
        complete_checklist_item_in_place(item, now)
        completed_item = True
    task["updated_at"] = now
    write_project_tasks(project_id, tasks_doc)
    return {
        "task": task_with_project(project_id, record, task),
        "item": dict(item),
        "mutated": True,
        "completed_item": completed_item,
        "result": result,
        "checklist_progress": checklist_progress(task),
        "next_item": dict(next_open_checklist_item(task)) if next_open_checklist_item(task) else None,
    }


def run_next_checklist_action(task_identifier: str, project: Optional[str] = None, dry_run: bool = False, complete_on_success: bool = True) -> dict:
    project_id, record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    item = next_open_checklist_item(task)
    if not item:
        return {
            "task": task_with_project(project_id, record, task),
            "item": None,
            "mutated": False,
            "message": "No open checklist items.",
            "result": action_result("blocked", "", "No open checklist items."),
        }
    return run_checklist_action(task_identifier, item.get("item_id", ""), project_id, dry_run=dry_run, complete_on_success=complete_on_success)


def active_run_next_action(project: Optional[str] = None, dry_run: bool = False, complete_on_success: bool = True) -> dict:
    data = active_next_step_data(project)
    if not data:
        return {"task": None, "item": None, "mutated": False, "message": "No actionable project tasks.", "result": action_result("blocked", "", "No actionable project tasks.")}
    if not data.get("item_id"):
        return {"task": data, "item": None, "mutated": False, "message": "No open checklist items.", "result": action_result("blocked", "", "No open checklist items.")}
    return run_checklist_action(data["task_id"], data["item_id"], data["project_id"], dry_run=dry_run, complete_on_success=complete_on_success)


def checklist_action_history_data(task_identifier: str, item_identifier: str, project: Optional[str] = None) -> dict:
    data = checklist_action_data(task_identifier, item_identifier, project)
    item = data["item"]
    return {"task": data["task"], "item": item, "history": item.get("action_history", [])}


def task_report_output_dir(project_id: str, task_identifier: str, output_dir: Optional[str] = None) -> Path:
    if output_dir:
        return Path(output_dir).expanduser()
    return task_report_folder(project_id, task_identifier)


def task_report_paths(project_id: str, task_identifier: str, output_dir: Optional[str] = None) -> dict:
    folder = task_report_output_dir(project_id, task_identifier, output_dir)
    return {
        "output_dir": folder,
        "md": folder / "task_report.md",
        "json": folder / "task_report.json",
    }


def safe_timeline_add(timeline: List[dict], timestamp: Any, event: str, detail: str = "") -> None:
    if not timestamp:
        return
    timeline.append({"timestamp": str(timestamp), "event": event, "detail": str(detail or "")})


def action_entries_from_task(task: dict) -> tuple[dict, List[dict]]:
    entries = []
    configured = executed = partial_attempts = failed_attempts = 0
    for item in ensure_task_context(task).get("checklist", []):
        item = ensure_checklist_item_context(item)
        action = item.get("action")
        if action:
            configured += 1
        if item.get("action_status") == "executed":
            executed += 1
        history = item.get("action_history", [])
        for event in history:
            if not isinstance(event, dict):
                continue
            result = event.get("result") or {}
            status = result.get("status")
            if status == "partial":
                partial_attempts += 1
            elif status == "failed":
                failed_attempts += 1
            entries.append({
                "item_id": item.get("item_id", ""),
                "item_text": item.get("text", ""),
                "event": event.get("event", ""),
                "timestamp": event.get("timestamp", ""),
                "action_type": event.get("action_type", (action or {}).get("action_type", "")),
                "status": status or item.get("action_status", ""),
                "summary": result.get("summary", ""),
                "result": result,
            })
    return {
        "configured": configured,
        "executed": executed,
        "partial_attempts": partial_attempts,
        "failed_attempts": failed_attempts,
    }, entries


def task_report_outcomes(task: dict) -> List[dict]:
    outcomes = []
    for item in ensure_task_context(task).get("checklist", []):
        item = ensure_checklist_item_context(item)
        for event in item.get("action_history", []):
            if not isinstance(event, dict):
                continue
            result = event.get("result") or {}
            action_type = result.get("action_type") or event.get("action_type", "")
            if not action_type or not result:
                continue
            details = result.get("details") or []
            report_paths = []
            grand_total = ""
            warnings = []
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                for key in ("json_path", "md_path", "output_dir"):
                    if detail.get(key):
                        report_paths.append(detail[key])
                if detail.get("grand_total"):
                    grand_total = detail.get("grand_total")
                if detail.get("warnings"):
                    warnings.extend(detail.get("warnings") or [])
            if action_type == "receipt_reconcile":
                outcome_type = "receipt_reconciliation"
            elif action_type.endswith("_export"):
                outcome_type = action_type
            elif action_type in ("packet_link", "artifact_link"):
                outcome_type = action_type
            else:
                outcome_type = action_type
            outcomes.append({
                "outcome_type": outcome_type,
                "status": result.get("status", ""),
                "summary": result.get("summary", ""),
                "report_paths": report_paths,
                "grand_total": grand_total,
                "warnings": warnings,
                "item_id": item.get("item_id", ""),
                "timestamp": result.get("completed_at") or event.get("timestamp", ""),
            })
    return outcomes


def task_report_final_result(task: dict, outcomes: List[dict]) -> str:
    for outcome in reversed(outcomes):
        if outcome.get("outcome_type") == "receipt_reconciliation" and outcome.get("status") == "executed":
            total = outcome.get("grand_total")
            summary = outcome.get("summary", "")
            if total:
                return summary or f"Reconciled receipt packets for ${total}."
            return summary
    if task.get("status") == "complete":
        return f"Completed task {task.get('title', '')}."
    return "Task is still in progress."


def gather_task_report_data(task_identifier: str, project: Optional[str] = None) -> dict:
    project_id, record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    generated_at = utc_now()
    complete_count = sum(1 for item in task.get("checklist", []) if item.get("status") == "complete")
    total_count = len(task.get("checklist", []))
    checklist_items = [dict(ensure_checklist_item_context(item)) for item in task.get("checklist", [])]
    action_counts, action_entries = action_entries_from_task(task)
    outcomes = task_report_outcomes(task)
    timeline = []
    safe_timeline_add(timeline, task.get("created_at"), "task created", task.get("title", ""))
    safe_timeline_add(timeline, task.get("started_at"), "task started", task.get("title", ""))
    for note in task.get("work_notes", []):
        if not isinstance(note, dict):
            continue
        safe_timeline_add(timeline, note.get("created_at"), "note created", note.get("text", ""))
        if note.get("updated_at") and note.get("updated_at") != note.get("created_at"):
            safe_timeline_add(timeline, note.get("updated_at"), "note updated", note.get("note_id", ""))
    for item in checklist_items:
        safe_timeline_add(timeline, item.get("created_at"), "checklist item created", item.get("text", ""))
        for event in item.get("history", []):
            if isinstance(event, dict):
                safe_timeline_add(timeline, event.get("timestamp"), f"checklist item {event.get('event', '')}", item.get("text", ""))
        for event in item.get("action_history", []):
            if isinstance(event, dict):
                result = event.get("result") or {}
                status = result.get("status") or event.get("event", "")
                safe_timeline_add(timeline, event.get("timestamp"), f"action {status}", event.get("action_type", ""))
    for log in task.get("work_log", []):
        if isinstance(log, dict):
            safe_timeline_add(timeline, log.get("created_at"), "work log", log.get("text", ""))
    safe_timeline_add(timeline, task.get("completed_at"), "task completed", task.get("completion_note", ""))
    timeline = sorted(timeline, key=lambda item: item.get("timestamp", ""))
    report = {
        "report_type": "laia.project_task_report",
        "report_version": "0.1",
        "generated_at": generated_at,
        "project": {
            "project_id": project_id,
            "project_name": record.get("name", ""),
            "project_type": record.get("project_type", ""),
            "project_status": record.get("status", ""),
        },
        "task": {
            "task_id": task.get("task_id", ""),
            "title": task.get("title", ""),
            "description": task.get("description", ""),
            "status": task.get("status", ""),
            "priority": task.get("priority", ""),
            "created_at": task.get("created_at"),
            "started_at": task.get("started_at"),
            "completed_at": task.get("completed_at"),
            "updated_at": task.get("updated_at"),
            "completion_note": task.get("completion_note", ""),
        },
        "context": {
            "linked_packets": task.get("linked_packets", []),
            "linked_artifacts": task.get("linked_artifacts", []),
            "source_packet_id": task.get("source_packet_id"),
            "artifact_path": task.get("artifact_path"),
        },
        "notes": task.get("work_notes", []),
        "checklist": {
            "complete": complete_count,
            "total": total_count,
            "items": checklist_items,
        },
        "work_log": task.get("work_log", []),
        "actions": {
            **action_counts,
            "entries": action_entries,
        },
        "outcomes": outcomes,
        "timeline": timeline,
        "summary": {
            "current_state": task.get("status", ""),
            "checklist_progress": f"{complete_count}/{total_count}",
            "successful_actions": action_counts.get("executed", 0),
            "warnings_resolved": action_counts.get("partial_attempts", 0),
            "final_result": task_report_final_result(task, outcomes),
        },
        "warnings": [],
    }
    return report


def render_task_report_markdown(report: dict) -> str:
    project = report.get("project", {})
    task = report.get("task", {})
    checklist = report.get("checklist", {})
    summary = report.get("summary", {})
    lines = [
        "# LAIA Completed Task Report",
        "",
        f"Generated At: {report.get('generated_at', '')}",
        "",
        "## Project",
        "",
        f"- Project ID: {project.get('project_id', '')}",
        f"- Name: {project.get('project_name', '')}",
        f"- Type: {project.get('project_type', '')}",
        f"- Status: {project.get('project_status', '')}",
        "",
        "## Task",
        "",
        f"- Task ID: {task.get('task_id', '')}",
        f"- Title: {task.get('title', '')}",
        f"- Status: {task.get('status', '')}",
        f"- Priority: {task.get('priority', '')}",
        f"- Created: {task.get('created_at') or ''}",
        f"- Started: {task.get('started_at') or ''}",
        f"- Completed: {task.get('completed_at') or ''}",
        f"- Updated: {task.get('updated_at') or ''}",
        "",
        str(task.get("description") or "No description."),
        "",
        "## Completion Summary",
        "",
        f"- Completion note: {task.get('completion_note') or ''}",
        f"- Checklist progress: {summary.get('checklist_progress', '')}",
        f"- Final result: {summary.get('final_result', '')}",
        "",
        "## Linked Context",
        "",
        "Linked packets:",
    ]
    for packet_id in report.get("context", {}).get("linked_packets", []) or []:
        lines.append(f"- {packet_id}")
    if not report.get("context", {}).get("linked_packets"):
        lines.append("- none")
    lines.append("")
    lines.append("Linked artifacts:")
    for artifact_path in report.get("context", {}).get("linked_artifacts", []) or []:
        lines.append(f"- {artifact_path}")
    if not report.get("context", {}).get("linked_artifacts"):
        lines.append("- none")
    lines.extend(["", "## Work Notes", ""])
    if report.get("notes"):
        for note in report["notes"]:
            lines.append(f"- {note.get('created_at', '')} {note.get('note_id', '')}: {note.get('text', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Checklist", ""])
    if checklist.get("items"):
        for item in checklist["items"]:
            marker = "x" if item.get("status") == "complete" else " "
            lines.append(f"- [{marker}] {item.get('text', '')}")
            action = item.get("action") or {}
            result = item.get("action_result") or {}
            if action:
                lines.append(f"  - Action: {action.get('action_type', '')}")
            if result.get("summary"):
                lines.append(f"  - Result: {result.get('summary', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Action History", ""])
    entries = report.get("actions", {}).get("entries", [])
    if entries:
        for entry in entries:
            lines.append(f"- {entry.get('timestamp', '')} {entry.get('action_type', '')} {entry.get('status', '')}: {entry.get('summary', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Work Log", ""])
    if report.get("work_log"):
        for log in report["work_log"]:
            lines.append(f"- {log.get('created_at', '')} {log.get('log_id', '')}: {log.get('text', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Outcomes", ""])
    if report.get("outcomes"):
        for outcome in report["outcomes"]:
            lines.append(f"- {outcome.get('outcome_type', '')} ({outcome.get('status', '')}): {outcome.get('summary', '')}")
            for path in outcome.get("report_paths", []):
                lines.append(f"  - {path}")
    else:
        lines.append("- none")
    lines.extend(["", "## Timeline", ""])
    if report.get("timeline"):
        for event in report["timeline"]:
            lines.append(f"- {event.get('timestamp', '')} {event.get('event', '')}: {event.get('detail', '')}")
    else:
        lines.append("- none")
    lines.extend(["", "## Final State", ""])
    if task.get("status") == "complete":
        lines.append(f"Complete - all {checklist.get('complete', 0)} checklist items finished.")
    else:
        lines.append(f"{task.get('status', 'unknown')} - checklist {summary.get('checklist_progress', '')}.")
    return "\n".join(lines).rstrip() + "\n"


def write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=str(path.parent), delete=False) as handle:
        handle.write(text)
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def write_task_report(task_identifier: str, project: Optional[str] = None, report_format: str = "both", output_dir: Optional[str] = None) -> dict:
    if report_format not in {"md", "json", "both"}:
        raise ValueError("format must be md, json, or both.")
    report = gather_task_report_data(task_identifier, project)
    project_id = report["project"]["project_id"]
    task_id_value = report["task"]["task_id"]
    paths = task_report_paths(project_id, task_id_value, output_dir)
    written = []
    if report_format in ("json", "both"):
        write_text_atomic(paths["json"], json.dumps(report, indent=2) + "\n")
        written.append(str(paths["json"]))
    if report_format in ("md", "both"):
        write_text_atomic(paths["md"], render_task_report_markdown(report))
        written.append(str(paths["md"]))
    return {
        "report": report,
        "output_dir": str(paths["output_dir"]),
        "markdown_path": str(paths["md"]) if paths["md"].exists() else "",
        "json_path": str(paths["json"]) if paths["json"].exists() else "",
        "reports_written": len(written),
        "written": written,
    }


def task_report_files_data(task_identifier: str, project: Optional[str] = None) -> dict:
    project_id, record, _tasks_doc, task = resolve_task_location(task_identifier, project)
    task = ensure_task_context(task)
    paths = task_report_paths(project_id, task.get("task_id", ""))
    data = {
        "project_id": project_id,
        "project_name": record.get("name", ""),
        "task_id": task.get("task_id", ""),
        "title": task.get("title", ""),
        "task_status": task.get("status", ""),
        "checklist_progress": checklist_progress(task),
        "markdown_path": str(paths["md"]) if paths["md"].exists() else "",
        "json_path": str(paths["json"]) if paths["json"].exists() else "",
        "generated_at": "",
    }
    if paths["json"].exists():
        report = load_json(paths["json"])
        data["generated_at"] = report.get("generated_at", "")
    return data


def task_report_exists(project_id: str, task_identifier: str) -> bool:
    paths = task_report_paths(project_id, task_identifier)
    return paths["md"].exists() or paths["json"].exists()


def completed_task_report_rows(project: Optional[str] = None) -> List[dict]:
    project_id_filter = resolve_project_filter(project)
    rows = []
    for project_id in list_project_ids():
        if project_id_filter and project_id != project_id_filter:
            continue
        try:
            record = load_project(project_id)
            tasks = project_tasks(project_id)
        except Exception:
            continue
        for task in tasks:
            task = ensure_task_context(task)
            if task.get("status") != "complete":
                continue
            files = task_report_files_data(task.get("task_id", ""), project_id)
            rows.append({
                "project_id": project_id,
                "project_name": record.get("name", ""),
                "task_id": task.get("task_id", ""),
                "title": task.get("title", ""),
                "task_status": task.get("status", ""),
                "checklist_progress": checklist_progress(task),
                "generated_at": files.get("generated_at", ""),
                "report_path": files.get("markdown_path") or files.get("json_path"),
            })
    return sorted(rows, key=lambda row: (row.get("generated_at", ""), row.get("task_id", "")), reverse=True)


def bulk_export_completed_task_reports(project: Optional[str] = None, report_format: str = "both", output_root: Optional[str] = None) -> dict:
    project_id_filter = resolve_project_filter(project)
    projects_processed = 0
    tasks_exported = 0
    reports_written = 0
    written = []
    for project_id in list_project_ids():
        if project_id_filter and project_id != project_id_filter:
            continue
        projects_processed += 1
        for task in project_tasks(project_id):
            task = ensure_task_context(task)
            if task.get("status") != "complete":
                continue
            output_dir = None
            if output_root:
                output_dir = str(Path(output_root).expanduser() / project_id / task.get("task_id", ""))
            result = write_task_report(task.get("task_id", ""), project_id, report_format, output_dir)
            tasks_exported += 1
            reports_written += result.get("reports_written", 0)
            written.extend(result.get("written", []))
    return {
        "projects_processed": projects_processed,
        "tasks_exported": tasks_exported,
        "reports_written": reports_written,
        "written": written,
    }


def start_next_project_task(project: Optional[str] = None) -> Optional[dict]:
    rows = actionable_task_rows(project)
    if not rows:
        return None
    selected = rows[0]
    if selected.get("status") == "in_progress":
        selected["already_in_progress"] = True
        return selected
    project_id = selected.get("project_id", "")
    tasks_doc = load_project_tasks(project_id)
    task = find_task(tasks_doc, selected.get("task_id", ""))
    now = utc_now()
    task["status"] = "in_progress"
    task["updated_at"] = now
    if not task.get("started_at"):
        task["started_at"] = now
    write_project_tasks(project_id, tasks_doc)
    record = load_project(project_id)
    row = task_with_project(project_id, record, task)
    row["already_in_progress"] = False
    return row


def packet_entry_for_project(project_id: str, packet: Dict[str, Any], linked_at: str) -> dict:
    return {
        "project_id": project_id,
        "job_id": str(packet.get("job_id", "")),
        "packet_type": str(packet.get("packet_type", "")),
        "packet_path": str(packet.get("packet_path", "")),
        "linked_at": linked_at,
        "link_role": "source",
    }


def artifact_entry_for_project(project_id: str, artifact_path: Optional[str], source_packet_id: str, linked_at: str, artifact_type: str = "promoted_output") -> Optional[dict]:
    if not artifact_path:
        return None
    return {
        "project_id": project_id,
        "artifact_type": artifact_type or "promoted_output",
        "artifact_path": str(Path(artifact_path).expanduser()),
        "source_packet_id": source_packet_id,
        "linked_at": linked_at,
    }


def project_packets(project_id: str) -> List[dict]:
    data = load_project_packets(project_id)
    return data.get("packets", [])


def project_artifacts(project_id: str) -> List[dict]:
    data = load_project_artifacts(project_id)
    return data.get("artifacts", [])


def project_cohorts(project_id: str) -> List[dict]:
    return load_project_cohorts(project_id).get("cohorts", [])


def project_video_evidence(project_id: str) -> List[dict]:
    return load_project_video_evidence(project_id).get("videos", [])


def add_video_evidence(project_id: str, video: dict) -> dict:
    data = load_project_video_evidence(project_id)
    existing = next(
        (
            item for item in data["videos"]
            if item.get("packet_id") == video.get("packet_id") and item.get("role") == video.get("role")
        ),
        None,
    )
    if existing is None:
        data["videos"].append(video)
        result = video
    else:
        existing.update(video)
        result = existing
    write_json(project_video_evidence_path(project_id), data)
    return result


def add_cohort_to_project(project_id: str, cohort: dict) -> dict:
    cohorts_doc = load_project_cohorts(project_id)
    cohorts = cohorts_doc.get("cohorts", [])
    packet_id = str(cohort.get("packet_id", ""))
    cohort_id = str(cohort.get("cohort_id", ""))
    existing = next(
        (
            item
            for item in cohorts
            if str(item.get("packet_id", "")) == packet_id
            and str(item.get("cohort_id", "")) == cohort_id
        ),
        None,
    )
    if existing is None:
        cohorts.append(cohort)
        result = cohort
    else:
        existing.update(cohort)
        result = existing
    cohorts_doc["cohorts"] = cohorts
    write_project_cohorts(project_id, cohorts_doc)
    return result


def remove_cohort_from_project(project_id: str, packet_id: str, cohort_id: str) -> bool:
    cohorts_doc = load_project_cohorts(project_id)
    cohorts = cohorts_doc.get("cohorts", [])
    filtered = [
        item
        for item in cohorts
        if not (
            str(item.get("packet_id", "")) == str(packet_id)
            and str(item.get("cohort_id", "")) == str(cohort_id)
        )
    ]
    if len(filtered) == len(cohorts):
        return False
    cohorts_doc["cohorts"] = filtered
    write_project_cohorts(project_id, cohorts_doc)
    return True


def add_packet_to_project(project_id: str, packet: Dict[str, Any], linked_at: str) -> None:
    packets_doc = load_project_packets(project_id)
    packets = packets_doc.get("packets", [])
    packet_id = str(packet.get("job_id", ""))
    existing = next((item for item in packets if item.get("job_id") == packet_id), None)
    entry = packet_entry_for_project(project_id, packet, linked_at)
    if existing:
        existing.update(entry)
    else:
        packets.append(entry)
    packets_doc["project_id"] = project_id
    packets_doc["packets"] = packets
    write_project_packets(project_id, packets_doc)


def add_artifact_to_project(project_id: str, artifact_path: Optional[str], source_packet_id: str, linked_at: str, artifact_type: str = "promoted_output") -> None:
    if not artifact_path:
        return
    artifacts_doc = load_project_artifacts(project_id)
    artifacts = artifacts_doc.get("artifacts", [])
    artifact_path = str(Path(artifact_path).expanduser())
    existing = next((item for item in artifacts if item.get("artifact_path") == artifact_path), None)
    entry = artifact_entry_for_project(project_id, artifact_path, source_packet_id, linked_at, artifact_type)
    if existing:
        existing.update(entry)
    else:
        artifacts.append(entry)
    artifacts_doc["project_id"] = project_id
    artifacts_doc["artifacts"] = artifacts
    write_project_artifacts(project_id, artifacts_doc)


def remove_packet_from_project(project_id: str, job_id: str) -> bool:
    packets_doc = load_project_packets(project_id)
    packets = packets_doc.get("packets", [])
    filtered = [packet for packet in packets if str(packet.get("job_id", "")) != str(job_id)]
    removed = len(filtered) != len(packets)
    if removed:
        packets_doc["packets"] = filtered
        write_project_packets(project_id, packets_doc)
    return removed


def project_record_summary(project_id: str) -> dict:
    record = load_project(project_id)
    packets = project_packets(project_id)
    artifacts = project_artifacts(project_id)
    cohorts = project_cohorts(project_id)
    tasks = project_task_summary(project_id)
    return {
        "project_id": record.get("project_id", project_id),
        "name": record.get("name", ""),
        "project_type": record.get("project_type", ""),
        "status": record.get("status", ""),
        "packet_count": len(packets),
        "cohort_count": len(cohorts),
        "artifact_count": len(artifacts),
        "open_tasks": tasks.get("open", 0),
        "blocked_tasks": tasks.get("blocked", 0),
        "updated_at": record.get("updated_at", ""),
    }


def registry_rows_by_job_id() -> Dict[str, Any]:
    try:
        rows = load_registry_rows(config_from_env().db_path)
    except (FileNotFoundError, sqlite3.Error):
        return {}
    return {str(row_value(row, "job_id", "")): row for row in rows}


def artifact_file_count(path: str) -> Optional[int]:
    artifact_path = Path(path).expanduser()
    if artifact_path.is_file():
        return 1
    if artifact_path.is_dir():
        return sum(1 for item in artifact_path.rglob("*") if item.is_file())
    return None


def artifact_status(artifact: dict) -> dict:
    path = str(artifact.get("artifact_path", ""))
    exists = bool(path) and Path(path).expanduser().exists()
    return {
        "artifact_type": artifact.get("artifact_type", ""),
        "artifact_path": path,
        "source_packet_id": artifact.get("source_packet_id", ""),
        "exists": exists,
        "file_count": artifact_file_count(path) if exists else None,
        "linked_at": artifact.get("linked_at", ""),
    }


def cohort_status_entry(cohort: dict) -> dict:
    cohort_path = Path(str(cohort.get("cohort_path", ""))).expanduser()
    artifact_path = Path(str(cohort.get("artifact_path", ""))).expanduser() if cohort.get("artifact_path") else None
    contact_sheet_path = cohort_path / "contact_sheet.jpg" if cohort_path else Path()
    return {
        **cohort,
        "cohort_exists": bool(str(cohort_path)) and cohort_path.is_dir(),
        "artifact_exists": artifact_path is not None and artifact_path.exists(),
        "contact_sheet_path": str(contact_sheet_path) if str(cohort_path) else "",
        "contact_sheet_exists": bool(str(cohort_path)) and contact_sheet_path.is_file(),
    }


def packet_briefing_entry(packet: dict, row=None) -> dict:
    entry = {
        "job_id": packet.get("job_id", ""),
        "packet_type": packet.get("packet_type", ""),
        "packet_path": packet.get("packet_path", ""),
        "linked_at": packet.get("linked_at", ""),
        "link_role": packet.get("link_role", ""),
        "registry_found": row is not None,
    }
    if row is not None:
        entry.update({
            "packet_type": row_value(row, "packet_type", entry["packet_type"]),
            "review_status": row_value(row, "review_status", ""),
            "workflow_status": row_value(row, "workflow_status", ""),
            "verification_status": row_value(row, "verification_status", ""),
            "missing_required": row_value(row, "missing_required_items", ""),
            "failure_status": row_value(row, "failure_status", ""),
            "route_status": row_value(row, "route_status", ""),
            "output_review_status": row_value(row, "output_review_status", ""),
            "promotion_status": row_value(row, "promotion_status", ""),
            "promoted_at": row_value(row, "promoted_at", ""),
            "lifecycle_state": lifecycle_state_label(row),
            "ready": is_ready(row),
            "attention": has_attention(row),
        })
    else:
        entry.update({
            "review_status": "",
            "workflow_status": "",
            "verification_status": "unknown",
            "missing_required": "",
            "failure_status": "",
            "route_status": "",
            "output_review_status": "",
            "promotion_status": "",
            "promoted_at": "",
            "lifecycle_state": "packet registry row missing",
            "ready": False,
            "attention": True,
        })
    return entry


def project_health(packet_entries: List[dict], artifact_entries: List[dict], cohort_entries: Optional[List[dict]] = None) -> str:
    cohort_entries = cohort_entries or []
    if any(packet.get("attention") for packet in packet_entries):
        return "attention"
    if any(not cohort.get("cohort_exists") for cohort in cohort_entries):
        return "attention"
    if not packet_entries or not artifact_entries:
        return "warning"
    if any(not artifact.get("exists") for artifact in artifact_entries):
        return "warning"
    if any(not cohort.get("artifact_exists") or not cohort.get("contact_sheet_exists") for cohort in cohort_entries):
        return "warning"
    return "healthy"


def project_suggestions(
    record: dict,
    packet_entries: List[dict],
    artifact_entries: List[dict],
    health: str,
    cohort_entries: Optional[List[dict]] = None,
) -> List[str]:
    cohort_entries = cohort_entries or []
    suggestions = []
    project_id = str(record.get("project_id", ""))
    tasks = project_task_summary(project_id)
    task_rows = project_tasks(project_id)
    completed_tasks = [task for task in task_rows if task.get("status") == "complete"]
    missing_reports = [task for task in completed_tasks if not task_report_exists(project_id, task.get("task_id", ""))]
    blocked = [task for task in task_rows if task.get("status") == "blocked"]
    in_progress = sort_next_rows([task_with_project(project_id, record, task) for task in task_rows if task.get("status") == "in_progress"])
    actionable = actionable_task_rows(project_id)
    if any(packet.get("attention") for packet in packet_entries):
        suggestions.append("Resolve packet issues before continuing project work.")
    if any(packet.get("ready") and not packet.get("promotion_status") for packet in packet_entries):
        suggestions.append("Promote reviewed packet output.")
    if any(not artifact.get("exists") for artifact in artifact_entries):
        suggestions.append("Repair or relink missing artifact.")
    if any(not cohort.get("artifact_exists") for cohort in cohort_entries):
        suggestions.append("Re-export or relink the missing cohort artifact.")
    if any(not cohort.get("contact_sheet_exists") for cohort in cohort_entries):
        suggestions.append("Generate the cohort contact sheet.")
    ready_exports = [
        cohort
        for cohort in cohort_entries
        if cohort.get("cohort_status") == "ready" and cohort.get("artifact_exists")
    ]
    if ready_exports:
        suggestions.append(f"Review or continue work with the {ready_exports[0].get('cohort_name', '')} cohort export.")
    if missing_reports:
        suggestions.append("Export completed task reports.")
    if blocked:
        suggestions.append(f"Resolve {len(blocked)} blocked project tasks.")
    elif in_progress:
        suggestions.append(f"Continue {in_progress[0].get('title', '')}.")
        item = next_open_checklist_item(in_progress[0])
        if item:
            action = item.get("action") or {}
            if action.get("action_type") and action.get("action_type") != "manual":
                suggestions.append(f"Run {action.get('action_type')} for {item.get('text', '')}.")
            else:
                suggestions.append(f"Next checklist item: {item.get('text', '')}.")
        elif in_progress[0].get("checklist"):
            suggestions.append(f"Complete or update {in_progress[0].get('title', '')}.")
    elif actionable:
        suggestions.append(f"Start {actionable[0].get('title', '')}.")
    elif health == "healthy":
        suggestions.append("Project has no open tasks; add work or mark project complete.")
    if any(artifact.get("exists") for artifact in artifact_entries):
        suggestions.append("Review or continue work in promoted artifact.")
    if record.get("project_type") == "publication":
        suggestions.append("Review publication staging and prepare next editorial step.")
    else:
        suggestions.append("Continue project work or link additional source packets.")
    if health == "healthy":
        suggestions.append("Project is healthy.")
    return suggestions


def high_priority_actionable_rows(rows: List[dict]) -> List[dict]:
    return [row for row in rows if row.get("status") in ("open", "in_progress") and row.get("priority") in ("urgent", "high")]


def portfolio_suggestions(projects: List[dict], unhealthy: List[dict], missing_artifacts: List[dict], queue_summary: dict, next_task: Optional[dict]) -> List[str]:
    suggestions = []
    all_rows = all_project_task_rows()
    blocked_count = queue_summary.get("blocked", 0)
    in_progress = sort_next_rows([row for row in all_rows if row.get("status") == "in_progress"])
    actionable = actionable_task_rows()
    high_priority = high_priority_actionable_rows(all_rows)
    high_priority_projects = {row.get("project_id", "") for row in high_priority if row.get("project_id", "")}
    if unhealthy:
        suggestions.append("Resolve packet issues in affected projects.")
    if missing_artifacts:
        suggestions.append("Promote or link artifacts for projects missing outputs.")
    if blocked_count:
        suggestions.append(f"Resolve {blocked_count} blocked project tasks.")
    elif in_progress:
        first = in_progress[0]
        suggestions.append(f"Continue {first.get('project_id', '')}/{first.get('title', '')}.")
        item = next_open_checklist_item(first)
        if item:
            action = item.get("action") or {}
            if action.get("action_type") and action.get("action_type") != "manual":
                suggestions.append(f"Run {action.get('action_type')} for {first.get('project_id', '')}/{first.get('title', '')}.")
            else:
                suggestions.append(f"Next checklist item: {item.get('text', '')}.")
        elif first.get("checklist"):
            suggestions.append(f"Complete or update {first.get('project_id', '')}/{first.get('title', '')}.")
        if len(in_progress) > 1:
            suggestions.append(f"{len(in_progress) - 1} more project tasks are in progress.")
    elif actionable and next_task:
        suggestions.append(f"Start {next_task.get('project_id', '')}/{next_task.get('title', '')}.")
    if high_priority:
        suggestions.append(f"{len(high_priority)} high-priority tasks remain across {len(high_priority_projects)} projects.")
    elif actionable:
        suggestions.append(f"{len(actionable)} actionable tasks remain.")
    elif projects:
        suggestions.append("No actionable tasks; add work or close inactive projects.")
    if projects and not unhealthy and not missing_artifacts:
        suggestions.append("Project portfolio is healthy.")
    if any(project["project_type"] == "publication" for project in projects):
        suggestions.append("Review publication staging outputs.")
    if not projects:
        suggestions.append("Create or link a project record.")
    return suggestions


def project_briefing_data(identifier: str) -> dict:
    project_id = find_project(identifier)
    record = load_project(project_id)
    packets = project_packets(project_id)
    artifacts = project_artifacts(project_id)
    cohorts = project_cohorts(project_id)
    videos = project_video_evidence(project_id)
    rows_by_job_id = registry_rows_by_job_id()
    packet_entries = [packet_briefing_entry(packet, rows_by_job_id.get(str(packet.get("job_id", "")))) for packet in packets]
    artifact_entries = [artifact_status(artifact) for artifact in artifacts]
    cohort_entries = [cohort_status_entry(cohort) for cohort in cohorts]
    notes = project_notes(project_id)
    active_notes = [note for note in notes if note.get("status") == "active"]
    latest_notes = sorted(active_notes, key=lambda note: note.get("created_at", ""), reverse=True)[:3]
    tasks = project_task_summary(project_id)
    task_rows = project_tasks(project_id)
    completed_tasks = [task for task in task_rows if task.get("status") == "complete"]
    completed_with_reports = [task for task in completed_tasks if task_report_exists(project_id, task.get("task_id", ""))]
    latest_completed = sorted(completed_tasks, key=lambda task: task.get("completed_at") or task.get("updated_at") or "", reverse=True)
    high_urgent_open = [
        task for task in task_rows
        if task.get("status") in ("open", "in_progress", "blocked") and task.get("priority") in ("high", "urgent")
    ]
    health = project_health(packet_entries, artifact_entries, cohort_entries)
    activity = [
        {"timestamp": record.get("created_at", ""), "event": "project created"},
        {"timestamp": record.get("updated_at", ""), "event": "project updated"},
    ]
    for packet in packet_entries:
        if packet.get("linked_at"):
            activity.append({"timestamp": packet.get("linked_at", ""), "event": f"packet linked: {packet.get('job_id', '')}"})
        if packet.get("promoted_at"):
            activity.append({"timestamp": packet.get("promoted_at", ""), "event": f"packet promoted: {packet.get('job_id', '')}"})
    for artifact in artifact_entries:
        if artifact.get("linked_at"):
            activity.append({"timestamp": artifact.get("linked_at", ""), "event": f"artifact linked: {artifact.get('artifact_type', '')}"})
    for cohort in cohort_entries:
        if cohort.get("linked_at"):
            activity.append(
                {
                    "timestamp": cohort.get("linked_at", ""),
                    "event": f"cohort linked: {cohort.get('cohort_id', '')}",
                }
            )
    activity = sorted([item for item in activity if item.get("timestamp")], key=lambda item: item["timestamp"], reverse=True)
    try:
        from projects.sale_items import sale_briefing
    except (ImportError, ModuleNotFoundError):
        from core.projects.sale_items import sale_briefing
    sale_data = sale_briefing(project_id)
    specific_suggestions = sale_data.get("suggestions", [])
    generic_suggestions = project_suggestions(record, packet_entries, artifact_entries, health, cohort_entries)
    if sale_data.get("sale_item"):
        generic_suggestions = [
            value
            for value in generic_suggestions
            if value
            not in {
                "Review or continue work in promoted artifact.",
                "Continue project work or link additional source packets.",
                "Project has no open tasks; add work or mark project complete.",
            }
            and not value.startswith("Review or continue work with the ")
        ]
    return {
        "project": record,
        "packets": packet_entries,
        "artifacts": artifact_entries,
        "cohorts": cohort_entries,
        "video_evidence": [
            {
                **video,
                "original_exists": Path(video.get("original_path", "")).is_file(),
                "proxy_exists": Path(video.get("proxy_path", "")).is_file(),
            }
            for video in videos
        ],
        "notes": {
            "active_count": len(active_notes),
            "latest": latest_notes,
        },
        "tasks": {
            **tasks,
            "high_urgent_open_tasks": high_urgent_open,
            "completed_task_count": len(completed_tasks),
            "completed_task_reports": len(completed_with_reports),
            "missing_task_reports": len(completed_tasks) - len(completed_with_reports),
            "latest_completed_task": latest_completed[0] if latest_completed else None,
        },
        "health": health,
        "sale_item": sale_data.get("sale_item", {}),
        "listings": sale_data.get("listings", []),
        "offers": sale_data.get("offers", []),
        "photo_edit": sale_data.get("photo_edit", {}),
        "recent_activity": activity[:8],
        "suggested_actions": specific_suggestions + [
            value for value in generic_suggestions if value not in specific_suggestions
        ],
    }


def portfolio_briefing_data() -> dict:
    projects = []
    type_counts: Dict[str, int] = {}
    total_packets = 0
    total_artifacts = 0
    total_cohorts = 0
    missing_cohort_exports = 0
    missing_cohort_contact_sheets = 0
    for project_id in list_project_ids():
        try:
            data = project_briefing_data(project_id)
        except FileNotFoundError:
            continue
        record = data["project"]
        project_type = str(record.get("project_type", ""))
        tasks = data.get("tasks", {})
        type_counts[project_type] = type_counts.get(project_type, 0) + 1
        total_packets += len(data["packets"])
        total_artifacts += len(data["artifacts"])
        total_cohorts += len(data.get("cohorts", []))
        missing_cohort_exports += sum(1 for cohort in data.get("cohorts", []) if not cohort.get("artifact_exists"))
        missing_cohort_contact_sheets += sum(
            1 for cohort in data.get("cohorts", []) if not cohort.get("contact_sheet_exists")
        )
        projects.append({
            "project_id": record.get("project_id", project_id),
            "name": record.get("name", ""),
            "project_type": project_type,
            "status": record.get("status", ""),
            "packet_count": len(data["packets"]),
            "cohort_count": len(data.get("cohorts", [])),
            "artifact_count": len(data["artifacts"]),
            "open_tasks": tasks.get("open", 0),
            "blocked_tasks": tasks.get("blocked", 0),
            "high_urgent_open_tasks": tasks.get("high_urgent_open", 0),
            "health": data["health"],
            "updated_at": record.get("updated_at", ""),
        })
    projects = sorted(projects, key=lambda item: item.get("updated_at", ""), reverse=True)
    unhealthy = [project for project in projects if project["health"] == "attention"]
    missing_artifacts = [project for project in projects if project["artifact_count"] == 0 or project["health"] == "warning"]
    queue_summary = queue_summary_data()
    next_tasks = actionable_task_rows()
    next_task = next_tasks[0] if next_tasks else None
    total_open_tasks = sum(project.get("open_tasks", 0) for project in projects)
    total_blocked_tasks = sum(project.get("blocked_tasks", 0) for project in projects)
    high_priority_projects = sum(1 for project in projects if project.get("high_urgent_open_tasks", 0))
    completed_tasks_total = sum(project_task_summary(project.get("project_id", "")).get("complete", 0) for project in projects)
    completed_report_rows = completed_task_report_rows()
    completed_reports_total = len([row for row in completed_report_rows if row.get("report_path")])
    missing_completed_reports = max(completed_tasks_total - completed_reports_total, 0)
    suggestions = portfolio_suggestions(projects, unhealthy, missing_artifacts, queue_summary, next_task)
    if missing_completed_reports and "Export completed task reports." not in suggestions:
        suggestions.append("Export completed task reports.")
    return {
        "summary": {
            "total_projects": len(projects),
            "active_projects": sum(1 for project in projects if project["status"] == "active"),
            "project_count_by_type": type_counts,
            "total_linked_packets": total_packets,
            "total_linked_cohorts": total_cohorts,
            "total_linked_artifacts": total_artifacts,
            "missing_cohort_exports": missing_cohort_exports,
            "missing_cohort_contact_sheets": missing_cohort_contact_sheets,
            "projects_with_packet_problems": len(unhealthy),
            "projects_with_missing_artifacts": len(missing_artifacts),
            "total_open_tasks": total_open_tasks,
            "total_blocked_tasks": total_blocked_tasks,
            "projects_with_high_priority_tasks": high_priority_projects,
            "completed_tasks": completed_tasks_total,
            "completed_task_reports": completed_reports_total,
            "missing_task_reports": missing_completed_reports,
            "queue": queue_summary,
            "next_task": next_task,
        },
        "projects": projects,
        "suggested_actions": suggestions,
    }


def search_projects(filters: dict) -> List[dict]:
    results = []
    for project_id in list_project_ids():
        try:
            record = load_project(project_id)
        except FileNotFoundError:
            continue
        packets = project_packets(project_id)
        artifacts = project_artifacts(project_id)
        tasks = project_tasks(project_id)
        text_filter = str(filters.get("text", "") or "").lower()
        task_text_filter = str(filters.get("task_text", "") or "").lower()
        if filters.get("type") and str(record.get("project_type", "")).lower() != str(filters["type"]).lower():
            continue
        if filters.get("status") and str(record.get("status", "")).lower() != str(filters["status"]).lower():
            continue
        if filters.get("has_open_tasks") and not any(task.get("status") in ("open", "in_progress") for task in tasks):
            continue
        if filters.get("has_blocked_tasks") and not any(task.get("status") == "blocked" for task in tasks):
            continue
        if filters.get("priority") and not any(task.get("priority") == filters["priority"] for task in tasks):
            continue
        if task_text_filter:
            task_haystack = "\n".join(
                f"{task.get('title', '')}\n{task.get('description', '')}\n{task.get('task_id', '')}"
                for task in tasks
            ).lower()
            if task_text_filter not in task_haystack:
                continue
        if text_filter:
            haystack = "\n".join(
                [str(record.get("project_id", "")), str(record.get("name", "")), str(record.get("project_type", "")), str(record.get("status", "")), str(record.get("notes", ""))]
            )
            haystack += "\n" + "\n".join(str(packet.get("job_id", "")) for packet in packets)
            haystack += "\n" + "\n".join(str(artifact.get("artifact_path", "")) for artifact in artifacts)
            haystack += "\n" + "\n".join(str(task.get("title", "")) for task in tasks)
            if text_filter not in haystack.lower():
                continue
        task_counts = project_task_summary(project_id)
        results.append({
            "project_id": record.get("project_id", ""),
            "name": record.get("name", ""),
            "project_type": record.get("project_type", ""),
            "status": record.get("status", ""),
            "packet_count": len(packets),
            "artifact_count": len(artifacts),
            "open_tasks": task_counts.get("open", 0),
            "blocked_tasks": task_counts.get("blocked", 0),
            "updated_at": record.get("updated_at", ""),
        })
    return sorted(results, key=lambda item: item["updated_at"], reverse=True)


def print_project_record(record: dict) -> None:
    print("LAIA Project Record")
    print()
    print(f"Project ID:   {record.get('project_id', '')}")
    print(f"Name:         {record.get('name', '')}")
    print(f"Type:         {record.get('project_type', '')}")
    print(f"Status:       {record.get('status', '')}")
    print(f"Created At:   {record.get('created_at', '')}")
    print(f"Updated At:   {record.get('updated_at', '')}")
    if record.get("notes"):
        print(f"Notes:        {record.get('notes', '')}")


def command_projects_list(_args):
    rows = [project_record_summary(project_id) for project_id in list_project_ids()]
    print("LAIA Project Records")
    print()
    if not rows:
        print("No project records found.")
        return
    table = [
        (
            row.get("project_id", ""),
            row.get("name", ""),
            row.get("project_type", ""),
            row.get("status", ""),
            row.get("packet_count", ""),
            row.get("cohort_count", ""),
            row.get("artifact_count", ""),
            row.get("open_tasks", ""),
            row.get("blocked_tasks", ""),
            row.get("updated_at", ""),
        )
        for row in rows
    ]
    print_rows(["project_id", "name", "type", "status", "packet_count", "cohort_count", "artifact_count", "open_tasks", "blocked_tasks", "updated_at"], table)


def command_projects_inspect(args):
    project_id = find_project(getattr(args, "identifier", ""))
    record = load_project(project_id)
    packets = project_packets(project_id)
    cohorts = project_cohorts(project_id)
    artifacts = project_artifacts(project_id)
    print_project_record(record)
    print()
    print(f"Linked packets: {len(packets)}")
    if packets:
        print_rows(["job_id", "packet_type", "packet_path", "linked_at", "link_role"], [
            (
                packet.get("job_id", ""),
                packet.get("packet_type", ""),
                packet.get("packet_path", ""),
                packet.get("linked_at", ""),
                packet.get("link_role", ""),
            )
            for packet in packets
        ])
    print()
    print(f"Linked cohorts: {len(cohorts)}")
    if cohorts:
        print_rows(["packet_id", "cohort_id", "cohort_name", "status", "file_count", "artifact_path", "linked_at"], [
            (
                cohort.get("packet_id", ""),
                cohort.get("cohort_id", ""),
                cohort.get("cohort_name", ""),
                cohort.get("cohort_status", ""),
                cohort.get("file_count", 0),
                cohort.get("artifact_path", ""),
                cohort.get("linked_at", ""),
            )
            for cohort in cohorts
        ])
    print()
    print(f"Linked artifacts: {len(artifacts)}")
    if artifacts:
        print_rows(["artifact_type", "artifact_path", "source_packet_id", "linked_at"], [
            (
                artifact.get("artifact_type", ""),
                artifact.get("artifact_path", ""),
                artifact.get("source_packet_id", ""),
                artifact.get("linked_at", ""),
            )
            for artifact in artifacts
        ])


def command_projects_packets(args):
    project_id = find_project(getattr(args, "identifier", ""))
    packets = project_packets(project_id)
    print(f"LAIA Project Packets: {project_id}")
    print()
    if not packets:
        print("No packets linked to this project.")
        return
    print_rows(["job_id", "packet_type", "packet_path", "linked_at"], [
        (
            packet.get("job_id", ""),
            packet.get("packet_type", ""),
            packet.get("packet_path", ""),
            packet.get("linked_at", ""),
        )
        for packet in packets
    ])


def command_projects_artifacts(args):
    project_id = find_project(getattr(args, "identifier", ""))
    artifacts = project_artifacts(project_id)
    print(f"LAIA Project Artifacts: {project_id}")
    print()
    if not artifacts:
        print("No artifacts linked to this project.")
        return
    print_rows(["artifact_type", "artifact_path", "source_packet_id", "linked_at"], [
        (
            artifact.get("artifact_type", ""),
            artifact.get("artifact_path", ""),
            artifact.get("source_packet_id", ""),
            artifact.get("linked_at", ""),
        )
        for artifact in artifacts
    ])


def command_projects_cohorts(args):
    project_id = find_project(getattr(args, "identifier", ""))
    cohorts = project_cohorts(project_id)
    if getattr(args, "json", False):
        print(json.dumps(cohorts, indent=2))
        return
    print(f"LAIA Project Cohorts: {project_id}")
    print()
    if not cohorts:
        print("No cohorts linked to this project.")
        return
    print_rows(["packet_id", "cohort_id", "cohort_name", "status", "file_count", "artifact_path", "linked_at"], [
        (
            cohort.get("packet_id", ""),
            cohort.get("cohort_id", ""),
            cohort.get("cohort_name", ""),
            cohort.get("cohort_status", ""),
            cohort.get("file_count", 0),
            cohort.get("artifact_path", ""),
            cohort.get("linked_at", ""),
        )
        for cohort in cohorts
    ])


def command_projects_cohort(args):
    project_id = find_project(getattr(args, "identifier", ""))
    query = getattr(args, "cohort_id", "")
    matches = [item for item in project_cohorts(project_id) if str(item.get("cohort_id", "")) == query]
    if not matches:
        raise SystemExit(f"Cohort contribution not found: {query}")
    if len(matches) > 1:
        raise SystemExit(f"Cohort ID is ambiguous across packets: {query}")
    cohort = cohort_status_entry(matches[0])
    if getattr(args, "json", False):
        print(json.dumps(cohort, indent=2))
        return
    print("LAIA Project Cohort Contribution")
    print()
    print(f"Project: {project_id}")
    print(f"Source packet: {cohort.get('packet_id', '')}")
    print(f"Packet path: {cohort.get('packet_path', '')}")
    print(f"Cohort: {cohort.get('cohort_name', '')} ({cohort.get('cohort_id', '')})")
    print(f"Cohort path: {cohort.get('cohort_path', '')}")
    print(f"Status: {cohort.get('cohort_status', '')}")
    print(f"File count: {cohort.get('file_count', 0)}")
    print(f"Export path: {cohort.get('artifact_path', '')}")
    print(f"Contact sheet: {cohort.get('contact_sheet_path', '')}")
    print(f"Linked at: {cohort.get('linked_at', '')}")
    print(f"Source exists: {'yes' if Path(cohort.get('packet_path', '')).is_dir() else 'no'}")
    print(f"Cohort exists: {'yes' if cohort.get('cohort_exists') else 'no'}")
    print(f"Export exists: {'yes' if cohort.get('artifact_exists') else 'no'}")
    print(f"Contact sheet exists: {'yes' if cohort.get('contact_sheet_exists') else 'no'}")


def command_projects_search(args):
    filters = {
        "type": getattr(args, "type", None),
        "status": getattr(args, "status", None),
        "text": getattr(args, "text", None),
        "has_open_tasks": getattr(args, "has_open_tasks", False),
        "has_blocked_tasks": getattr(args, "has_blocked_tasks", False),
        "priority": getattr(args, "priority", None),
        "task_text": getattr(args, "task_text", None),
    }
    rows = search_projects(filters)
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
        return
    print("LAIA Project Search")
    print()
    if not rows:
        print("No projects matched.")
        return
    print_rows(["project_id", "name", "type", "status", "packet_count", "artifact_count", "open_tasks", "blocked_tasks", "updated_at"], [
        (
            row.get("project_id", ""),
            row.get("name", ""),
            row.get("project_type", ""),
            row.get("status", ""),
            row.get("packet_count", ""),
            row.get("artifact_count", ""),
            row.get("open_tasks", ""),
            row.get("blocked_tasks", ""),
            row.get("updated_at", ""),
        )
        for row in rows
    ])


def print_portfolio_briefing(data: dict) -> None:
    summary = data["summary"]
    print("LAIA Project Briefing")
    print()
    print("Portfolio Health:")
    print(f"  Projects: {summary.get('total_projects', 0)}")
    print(f"  Active: {summary.get('active_projects', 0)}")
    print(f"  Linked packets: {summary.get('total_linked_packets', 0)}")
    print(f"  Linked cohorts: {summary.get('total_linked_cohorts', 0)}")
    print(f"  Linked artifacts: {summary.get('total_linked_artifacts', 0)}")
    print(f"  Missing cohort exports: {summary.get('missing_cohort_exports', 0)}")
    print(f"  Missing cohort contact sheets: {summary.get('missing_cohort_contact_sheets', 0)}")
    print(f"  Packet problems: {summary.get('projects_with_packet_problems', 0)}")
    print(f"  Missing artifacts: {summary.get('projects_with_missing_artifacts', 0)}")
    print(f"  Open tasks: {summary.get('total_open_tasks', 0)}")
    print(f"  Blocked tasks: {summary.get('total_blocked_tasks', 0)}")
    print(f"  Completed tasks: {summary.get('completed_tasks', 0)}")
    print(f"  Completed task reports: {summary.get('completed_task_reports', 0)}")
    print(f"  Missing task reports: {summary.get('missing_task_reports', 0)}")
    print(f"  Projects with high-priority tasks: {summary.get('projects_with_high_priority_tasks', 0)}")
    queue = summary.get("queue", {})
    print(f"  Actionable tasks: {queue.get('actionable', 0)}")
    print(f"  Active tasks: {queue.get('in_progress', 0)}")
    print(f"  In progress: {queue.get('in_progress', 0)}")
    print(f"  Checklist items open: {queue.get('open_checklist_items', 0)}")
    print(f"  Tasks with recent work logs: {queue.get('tasks_with_work_logs', 0)}")
    next_task = summary.get("next_task")
    if next_task:
        print(f"  Next task: {next_task.get('project_id', '')}/{next_task.get('title', '')}")
    print()
    print("By type:")
    if summary.get("project_count_by_type"):
        for project_type, count in sorted(summary["project_count_by_type"].items()):
            print(f"  {project_type}: {count}")
    else:
        print("  none")
    print()
    print("Projects:")
    if data["projects"]:
        print_rows(["project_id", "name", "type", "status", "packets", "cohorts", "artifacts", "open", "blocked", "health"], [
            (
                project.get("project_id", ""),
                project.get("name", ""),
                project.get("project_type", ""),
                project.get("status", ""),
                project.get("packet_count", 0),
                project.get("cohort_count", 0),
                project.get("artifact_count", 0),
                project.get("open_tasks", 0),
                project.get("blocked_tasks", 0),
                project.get("health", ""),
            )
            for project in data["projects"]
        ])
    else:
        print("  none")
    print()
    print("Suggested Next Actions:")
    for suggestion in data["suggested_actions"]:
        print(f"  - {suggestion}")


def print_project_briefing(data: dict) -> None:
    record = data["project"]
    print("LAIA Project Briefing")
    print()
    print("Project:")
    print(f"  project_id: {record.get('project_id', '')}")
    print(f"  name: {record.get('name', '')}")
    print(f"  type: {record.get('project_type', '')}")
    print(f"  status: {record.get('status', '')}")
    print(f"  created_at: {record.get('created_at', '')}")
    print(f"  updated_at: {record.get('updated_at', '')}")
    print(f"  health: {data.get('health', '')}")
    if record.get("notes"):
        print(f"  notes: {record.get('notes', '')}")
    print()
    sale_item = data.get("sale_item", {})
    print("Sale Item:")
    if sale_item:
        functional = sale_item.get("condition", {}).get("functional", "")
        if functional == "not_applicable":
            functional = "not applicable"
        print(f"  {sale_item.get('title', '')}")
        print(f"  condition: {sale_item.get('condition', {}).get('overall', '')}")
        print(f"  functional: {functional}")
        print(f"  sale status: {sale_item.get('sale', {}).get('status', '')}")
        if sale_item.get("category") == "records":
            record_metadata = sale_item.get("record_metadata", {})
            print("  Record:")
            print(f"    artist: {record_metadata.get('artist', '')}")
            print(f"    title: {record_metadata.get('title', '')}")
            print(f"    label: {record_metadata.get('record_label', '')}")
            print(f"    catalog number: {record_metadata.get('catalog_number', '')}")
            print(f"    media condition: {record_metadata.get('media_condition', '')}")
            print(f"    sleeve condition: {record_metadata.get('sleeve_condition', '')}")
    else:
        print("  none")
    print()
    print("Sales Channels:")
    listings = data.get("listings", [])
    if listings:
        for listing in listings:
            price = listing.get("asking_price")
            price_text = f" at ${price}" if price else ""
            print(f"  {listing.get('channel_name', listing.get('channel', ''))}: {listing.get('status', '')}{price_text}")
    else:
        print("  none")
    print()
    print("Offers:")
    offers = data.get("offers", [])
    if offers:
        for offer in offers:
            note = f" — {offer.get('note', '')}" if offer.get("note") else ""
            print(f"  ${offer.get('amount', '')} {offer.get('status', '')}{note}")
    else:
        print("  none")
    print()
    photo_edit = data.get("photo_edit", {})
    print("Photo Editing:")
    if photo_edit:
        source_ids = {
            source.get("source_id") for source in photo_edit.get("sources", [])[1:] if source.get("source_id")
        }
        category = sale_item.get("category") if sale_item else ""
        hero_role = "cover_front" if category == "records" else "hero"
        recommended_roles = ["cover_back"] if category == "records" else ["rear", "ports"]
        heroes = [
            image for image in photo_edit.get("images", [])
            if image.get("role") == hero_role and image.get("review_status") == "approved"
        ]
        print(f"  sources: {len(photo_edit.get('sources', []))}")
        print(f"  workspace images: {photo_edit.get('image_count', 0)}")
        print(f"  XMP sidecars: {photo_edit.get('edited_count', 0)}")
        print(f"  rendered exports: {photo_edit.get('exported_count', 0)}")
        print(f"  approved: {photo_edit.get('approved_count', 0)}")
        print(
            "  new/unreviewed: "
            + str(
                sum(
                    1
                    for image in photo_edit.get("images", [])
                    if image.get("source_id") in source_ids and image.get("review_status") == "unreviewed"
                )
            )
        )
        print(f"  {hero_role} image: {'approved' if heroes else 'missing'}")
        approved_roles = {
            image.get("role")
            for image in photo_edit.get("images", [])
            if image.get("review_status") == "approved"
        }
        missing_coverage = [role for role in recommended_roles if role not in approved_roles]
        print(f"  verification: {photo_edit.get('status', '').replace('_', ' ')}")
        print(f"  missing coverage: {', '.join(missing_coverage) if missing_coverage else 'none'}")
    else:
        print("  none")
    print()
    print("Photo Evidence:")
    if photo_edit:
        approved_images = [
            image for image in photo_edit.get("images", [])
            if image.get("review_status") == "approved"
        ]
        role_counts = {}
        tag_counts = {}
        for image in approved_images:
            role = image.get("role")
            if role:
                role_counts[role] = role_counts.get(role, 0) + 1
            for tag in image.get("tags", []) or []:
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
        print(f"  Approved photos: {len(approved_images)}")
        print("  Roles:")
        if role_counts:
            for role, count in sorted(role_counts.items()):
                print(f"    {role}: {count}")
        else:
            print("    none")
        print("  Tags:")
        if tag_counts:
            for tag, count in sorted(tag_counts.items()):
                print(f"    {tag}: {count}")
        else:
            print("    none")
    else:
        print("  none")
    print()
    print("Video Evidence:")
    if data.get("video_evidence"):
        for video in data["video_evidence"]:
            print(f"  {video.get('role', '')}")
            print(f"    duration: {float(video.get('duration_seconds', 0)):.1f} seconds")
            print(f"    original: {'exists' if video.get('original_exists') else 'missing'}")
            print(f"    proxy: {'exists' if video.get('proxy_exists') else 'missing'}")
            print(f"    verification: {video.get('verification_status', '')}")
    else:
        print("  none")
    print()
    print("Packet Health:")
    if data["packets"]:
        print_rows(["job_id", "type", "review", "workflow", "verification", "route", "output", "promotion", "state"], [
            (
                packet.get("job_id", ""),
                packet.get("packet_type", ""),
                packet.get("review_status", ""),
                packet.get("workflow_status", ""),
                packet.get("verification_status", ""),
                packet.get("route_status", ""),
                packet.get("output_review_status", ""),
                packet.get("promotion_status", ""),
                packet.get("lifecycle_state", ""),
            )
            for packet in data["packets"]
        ])
    else:
        print("  none")
    print()
    print("Photo Cohorts:")
    if data.get("cohorts"):
        for cohort in data["cohorts"]:
            print(f"  {cohort.get('cohort_id', '')}")
            print(f"    packet: {cohort.get('packet_id', '')}")
            print(f"    files: {cohort.get('file_count', 0)}")
            print(f"    status: {cohort.get('cohort_status', '')}")
            print(f"    export: {'exists' if cohort.get('artifact_exists') else 'missing'}")
            print(f"    contact sheet: {'exists' if cohort.get('contact_sheet_exists') else 'missing'}")
    else:
        print("  none")
    print()
    print("Artifact Status:")
    if data["artifacts"]:
        print_rows(["artifact_type", "artifact_path", "source_packet_id", "exists", "file_count", "linked_at"], [
            (
                artifact.get("artifact_type", ""),
                artifact.get("artifact_path", ""),
                artifact.get("source_packet_id", ""),
                "yes" if artifact.get("exists") else "no",
                "" if artifact.get("file_count") is None else artifact.get("file_count"),
                artifact.get("linked_at", ""),
            )
            for artifact in data["artifacts"]
        ])
    else:
        print("  none")
    print()
    print("Notes:")
    notes = data.get("notes", {})
    print(f"  active: {notes.get('active_count', 0)}")
    latest_notes = notes.get("latest", [])
    if latest_notes:
        for note in latest_notes:
            print(f"  - {note.get('created_at', '')} {note.get('note_id', '')}: {note.get('text', '')}")
    else:
        print("  latest: none")
    print()
    print("Tasks:")
    tasks = data.get("tasks", {})
    print(f"  open: {tasks.get('open', 0)}")
    print(f"  in_progress: {tasks.get('in_progress', 0)}")
    print(f"  blocked: {tasks.get('blocked', 0)}")
    print(f"  complete: {tasks.get('complete', 0)}")
    print()
    print("Completed Work:")
    print(f"  completed tasks: {tasks.get('completed_task_count', 0)}")
    print(f"  task reports: {tasks.get('completed_task_reports', 0)}")
    print(f"  missing reports: {tasks.get('missing_task_reports', 0)}")
    latest_completed = tasks.get("latest_completed_task")
    if latest_completed:
        has_report = "yes" if task_report_exists(record.get("project_id", ""), latest_completed.get("task_id", "")) else "no"
        print(f"  latest: {latest_completed.get('task_id', '')}: {latest_completed.get('title', '')}")
        print(f"  report available: {has_report}")
    else:
        print("  latest: none")
    high_tasks = tasks.get("high_urgent_open_tasks", [])
    if high_tasks:
        print("  urgent/high:")
        for task in high_tasks:
            print(f"    - {task.get('task_id', '')}: {task.get('title', '')}")
    else:
        print("  urgent/high: none")
    active_tasks = [task for task in project_tasks(record.get("project_id", "")) if task.get("status") == "in_progress"]
    if active_tasks:
        print("  active context:")
        for task in active_tasks:
            task = ensure_task_context(task)
            latest = latest_work_log(task)
            item = next_open_checklist_item(task)
            print(f"    - {task.get('title', '')}: checklist {checklist_progress(task)}")
            if latest:
                print(f"      latest log: {latest.get('text', '')}")
            if item:
                print(f"      next: {item.get('text', '')}")
    print()
    print("Recent Activity:")
    if data["recent_activity"]:
        for item in data["recent_activity"]:
            print(f"  - {item.get('timestamp', '')} {item.get('event', '')}")
    else:
        print("  none")
    print()
    print("Suggested Next Actions:")
    for suggestion in data["suggested_actions"]:
        print(f"  - {suggestion}")


def command_projects_briefing(args):
    identifier = getattr(args, "identifier", None)
    if identifier:
        data = project_briefing_data(identifier)
    else:
        data = portfolio_briefing_data()
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    if identifier:
        print_project_briefing(data)
    else:
        print_portfolio_briefing(data)


def command_projects_note(args):
    project_id = find_project(getattr(args, "identifier", ""))
    note = add_project_note(project_id, getattr(args, "text", ""), getattr(args, "status", "active"))
    if getattr(args, "json", False):
        print(json.dumps(note, indent=2))
        return
    print(f"Added note {note['note_id']} to project {project_id}")


def command_projects_notes(args):
    project_id = find_project(getattr(args, "identifier", ""))
    notes = project_notes(project_id, getattr(args, "status", None))
    if getattr(args, "json", False):
        print(json.dumps(notes, indent=2))
        return
    print(f"LAIA Project Notes: {project_id}")
    print()
    if not notes:
        print("No notes found.")
        return
    print_rows(["note_id", "status", "created_at", "text"], [
        (note.get("note_id", ""), note.get("status", ""), note.get("created_at", ""), note.get("text", ""))
        for note in notes
    ])


def command_projects_note_update(args):
    project_id = find_project(getattr(args, "identifier", ""))
    note = update_project_note(project_id, getattr(args, "note_id", ""), getattr(args, "text", ""))
    print(f"Updated note {note['note_id']} in project {project_id}")


def command_projects_note_archive(args):
    project_id = find_project(getattr(args, "identifier", ""))
    note = archive_project_note(project_id, getattr(args, "note_id", ""))
    print(f"Archived note {note['note_id']} in project {project_id}")


def command_projects_task_add(args):
    project_id = find_project(getattr(args, "identifier", ""))
    task = add_project_task(
        project_id,
        getattr(args, "title", ""),
        description=getattr(args, "description", "") or "",
        priority=getattr(args, "priority", "normal"),
        source_packet_id=getattr(args, "source_packet", None),
        artifact_path=getattr(args, "artifact", None),
    )
    print(f"Added task {task['task_id']} to project {project_id}")


def command_projects_tasks(args):
    project_id = find_project(getattr(args, "identifier", ""))
    tasks = project_tasks(project_id, getattr(args, "status", None), getattr(args, "priority", None))
    if getattr(args, "json", False):
        print(json.dumps(tasks, indent=2))
        return
    print(f"LAIA Project Tasks: {project_id}")
    print()
    if not tasks:
        print("No tasks found.")
        return
    print_rows(["task_id", "status", "priority", "title", "updated_at"], [
        (task.get("task_id", ""), task.get("status", ""), task.get("priority", ""), task.get("title", ""), task.get("updated_at", ""))
        for task in tasks
    ])


def print_task_context(data: dict) -> None:
    task = ensure_task_context(data.get("task", {}))
    print("LAIA Project Task Context")
    print()
    print("Task:")
    print(f"  task_id: {task.get('task_id', '')}")
    print(f"  project_id: {task.get('project_id', '')}")
    print(f"  project_name: {task.get('project_name', '')}")
    print(f"  title: {task.get('title', '')}")
    print(f"  status: {task.get('status', '')}")
    print(f"  priority: {task.get('priority', '')}")
    print(f"  created_at: {task.get('created_at', '')}")
    print(f"  updated_at: {task.get('updated_at', '')}")
    print()
    print("Description:")
    print(f"  {task.get('description', '') or 'none'}")
    print()
    print("Linked Packet:")
    packet_ids = list(dict.fromkeys(([task.get("source_packet_id")] if task.get("source_packet_id") else []) + task.get("linked_packets", [])))
    if packet_ids:
        for packet_id in packet_ids:
            print(f"  - {packet_id}")
    else:
        print("  none")
    print()
    print("Linked Artifact:")
    artifact_paths = list(dict.fromkeys(([task.get("artifact_path")] if task.get("artifact_path") else []) + task.get("linked_artifacts", [])))
    if artifact_paths:
        for artifact_path in artifact_paths:
            print(f"  - {artifact_path}")
    else:
        print("  none")
    print()
    print("Checklist:")
    if task.get("checklist"):
        for item in task.get("checklist", []):
            item = ensure_checklist_item_context(item)
            mark = "x" if item.get("status") == "complete" else " "
            print(f"  - [{mark}] {item.get('item_id', '')}: {item.get('text', '')}")
            action = item.get("action") or {}
            if action:
                result = item.get("action_result") or {}
                print(f"      action: {action.get('action_type', '')} ({item.get('action_status', 'none')})")
                if result.get("summary"):
                    print(f"      result: {result.get('summary', '')}")
    else:
        print("  none")
    print()
    print("Work Notes:")
    active_notes = [note for note in task.get("work_notes", []) if note.get("status") == "active"]
    if active_notes:
        for note in active_notes:
            print(f"  - {note.get('note_id', '')}: {note.get('text', '')}")
    else:
        print("  none")
    print()
    print("Work Log:")
    if task.get("work_log"):
        for log in task.get("work_log", []):
            print(f"  - {log.get('created_at', '')} {log.get('log_id', '')}: {log.get('text', '')}")
    else:
        print("  none")
    print()
    print("Suggested Next Step:")
    print(f"  {data.get('suggested_next_step', '')}")


def command_projects_task_show(args):
    project_id = find_project(getattr(args, "identifier", ""))
    task = find_task(load_project_tasks(project_id), getattr(args, "task_id", ""))
    print_task_context(task_context_data(task.get("task_id", ""), project_id))


def command_projects_task_start(args):
    project_id = find_project(getattr(args, "identifier", ""))
    task = set_project_task_status(project_id, getattr(args, "task_id", ""), "in_progress")
    print(f"Started task {task['task_id']} in project {project_id}")


def command_projects_task_block(args):
    project_id = find_project(getattr(args, "identifier", ""))
    task = set_project_task_status(project_id, getattr(args, "task_id", ""), "blocked", getattr(args, "note", "") or "")
    print(f"Blocked task {task['task_id']} in project {project_id}")


def command_projects_task_complete(args):
    project_id = find_project(getattr(args, "identifier", ""))
    task_before = find_task(load_project_tasks(project_id), getattr(args, "task_id", ""))
    open_items = [item for item in ensure_task_context(task_before).get("checklist", []) if item.get("status") == "open"]
    if open_items:
        print(f"Warning: {len(open_items)} checklist items remain open.")
    task = set_project_task_status(project_id, getattr(args, "task_id", ""), "complete", getattr(args, "note", "") or "")
    print(f"Completed task {task['task_id']} in project {project_id}")


def command_projects_task_cancel(args):
    project_id = find_project(getattr(args, "identifier", ""))
    task = set_project_task_status(project_id, getattr(args, "task_id", ""), "cancelled", getattr(args, "note", "") or "")
    print(f"Cancelled task {task['task_id']} in project {project_id}")


def command_projects_task_reopen(args):
    project_id = find_project(getattr(args, "identifier", ""))
    task = set_project_task_status(project_id, getattr(args, "task_id", ""), "open")
    print(f"Reopened task {task['task_id']} in project {project_id}")


def command_projects_task_update(args):
    project_id = find_project(getattr(args, "identifier", ""))
    updates = {
        "title": getattr(args, "title", None),
        "description": getattr(args, "description", None),
        "priority": getattr(args, "priority", None),
        "source_packet_id": getattr(args, "source_packet", None),
        "artifact_path": getattr(args, "artifact", None),
    }
    task = update_project_task(project_id, getattr(args, "task_id", ""), updates)
    print(f"Updated task {task['task_id']} in project {project_id}")


def command_projects_task_summary(args):
    project_id = find_project(getattr(args, "identifier", ""))
    summary = project_task_summary(project_id)
    print(f"LAIA Project Task Summary: {project_id}")
    print()
    print(f"open: {summary.get('open', 0)}")
    print(f"in_progress: {summary.get('in_progress', 0)}")
    print(f"blocked: {summary.get('blocked', 0)}")
    print(f"complete: {summary.get('complete', 0)}")
    print(f"cancelled: {summary.get('cancelled', 0)}")
    print(f"high/urgent open: {summary.get('high_urgent_open', 0)}")


def print_task_detail(row: dict) -> None:
    for key in [
        "task_id",
        "project_id",
        "project_name",
        "title",
        "description",
        "status",
        "priority",
        "source_packet_id",
        "artifact_path",
        "created_at",
        "updated_at",
        "completed_at",
        "started_at",
        "block_note",
        "completion_note",
        "cancel_note",
    ]:
        if key in row and row.get(key) not in ("", None):
            print(f"{key}: {row.get(key)}")


def command_projects_queue(args):
    filters = {
        "status": getattr(args, "status", None),
        "priority": getattr(args, "priority", None),
        "project": getattr(args, "project", None),
        "text": getattr(args, "text", None),
        "limit": getattr(args, "limit", None),
    }
    rows = project_queue_rows(filters)
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
        return
    print("LAIA Project Work Queue")
    print()
    if not rows:
        print("No project tasks matched.")
        return
    print_rows(["task_id", "project_id", "project_name", "status", "priority", "checklist", "title", "updated_at"], [
        (
            row.get("task_id", ""),
            row.get("project_id", ""),
            row.get("project_name", ""),
            row.get("status", ""),
            row.get("priority", ""),
            checklist_progress(row),
            row.get("title", ""),
            row.get("updated_at", ""),
        )
        for row in rows
    ])


def command_projects_next(args):
    rows = actionable_task_rows(getattr(args, "project", None))
    row = rows[0] if rows else None
    if getattr(args, "json", False):
        print(json.dumps(row or {}, indent=2))
        return
    if not row:
        print("No actionable project tasks.")
        return
    print("LAIA Next Project Task")
    print()
    print_task_detail(row)


def command_projects_start_next(args):
    row = start_next_project_task(getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(row or {}, indent=2))
        return
    if not row:
        print("No actionable project tasks.")
        return
    if row.get("already_in_progress"):
        print("LAIA Next Project Task Already In Progress")
    else:
        print("LAIA Started Next Project Task")
    print()
    print(f"task_id: {row.get('task_id', '')}")
    print(f"project_id: {row.get('project_id', '')}")
    print(f"project_name: {row.get('project_name', '')}")
    print(f"title: {row.get('title', '')}")
    print(f"status: {row.get('status', '')}")
    print(f"priority: {row.get('priority', '')}")
    print(f"started_at: {row.get('started_at') or row.get('updated_at', '')}")


def command_projects_blocked(args):
    rows = project_queue_rows({"status": "blocked", "project": getattr(args, "project", None)})
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
        return
    print("LAIA Blocked Project Tasks")
    print()
    if not rows:
        print("No blocked project tasks.")
        return
    print_rows(["task_id", "project_id", "priority", "title", "block_note", "updated_at"], [
        (
            row.get("task_id", ""),
            row.get("project_id", ""),
            row.get("priority", ""),
            row.get("title", ""),
            row.get("block_note", ""),
            row.get("updated_at", ""),
        )
        for row in rows
    ])


def command_projects_in_progress(args):
    rows = project_queue_rows({"status": "in_progress", "project": getattr(args, "project", None)})
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
        return
    print("LAIA In-Progress Project Tasks")
    print()
    if not rows:
        print("No in-progress project tasks.")
        return
    print_rows(["task_id", "project_id", "priority", "title", "updated_at"], [
        (
            row.get("task_id", ""),
            row.get("project_id", ""),
            row.get("priority", ""),
            row.get("title", ""),
            row.get("updated_at", ""),
        )
        for row in rows
    ])


def command_projects_task_find(args):
    row = find_task_global(getattr(args, "task_id", ""))
    print("LAIA Project Task")
    print()
    print_task_detail(row)


def command_projects_queue_summary(_args):
    summary = queue_summary_data()
    print("LAIA Project Queue Summary")
    print()
    print(f"open: {summary.get('open', 0)}")
    print(f"in_progress: {summary.get('in_progress', 0)}")
    print(f"blocked: {summary.get('blocked', 0)}")
    print(f"complete: {summary.get('complete', 0)}")
    print(f"cancelled: {summary.get('cancelled', 0)}")
    print(f"urgent open: {summary.get('urgent_open', 0)}")
    print(f"high open: {summary.get('high_open', 0)}")
    print(f"projects with actionable tasks: {summary.get('projects_with_actionable_tasks', 0)}")


def command_projects_active(args):
    project = getattr(args, "project", None)
    rows = project_queue_rows({"status": "in_progress", "project": project})
    if getattr(args, "json", False):
        if len(rows) == 1:
            print(json.dumps(task_context_data(rows[0]["task_id"], rows[0]["project_id"]), indent=2))
        else:
            print(json.dumps(rows, indent=2))
        return
    if not rows:
        print("No active project tasks.")
        return
    if len(rows) == 1:
        print_task_context(task_context_data(rows[0]["task_id"], rows[0]["project_id"]))
        return
    print("LAIA Active Project Tasks")
    print()
    print_rows(["task_id", "project_id", "project_name", "priority", "checklist", "title", "updated_at"], [
        (row.get("task_id", ""), row.get("project_id", ""), row.get("project_name", ""), row.get("priority", ""), checklist_progress(row), row.get("title", ""), row.get("updated_at", ""))
        for row in rows
    ])


def print_next_step(data: dict) -> None:
    print("LAIA Project Task Next Step")
    print()
    print(f"task_id: {data.get('task_id', '')}")
    print(f"project_id: {data.get('project_id', '')}")
    print(f"title: {data.get('title', '')}")
    print(f"item_id: {data.get('item_id', '')}")
    print(f"step: {data.get('step_text', '')}")
    print(f"checklist_progress: {data.get('checklist_progress', '')}")
    print(f"task_status: {data.get('task_status', '')}")
    print(f"priority: {data.get('priority', '')}")
    if data.get("action_type"):
        print(f"action_type: {data.get('action_type', '')}")
        print(f"action_status: {data.get('action_status', '')}")


def command_projects_task_next_step(args):
    data = task_next_step_data(getattr(args, "task_id", ""), getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print_next_step(data)


def command_projects_active_next(args):
    data = active_next_step_data(getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(data or {}, indent=2))
        return
    if not data:
        print("No actionable project tasks.")
        return
    print_next_step(data)


def print_complete_next_result(result: dict) -> None:
    if not result.get("mutated"):
        print(result.get("message", "No open checklist items."))
        return
    item = result.get("completed_item", {})
    print("LAIA Completed Project Task Step")
    print()
    print(f"completed_item: {item.get('item_id', '')}")
    print(f"completed_text: {item.get('text', '')}")
    print(f"checklist_progress: {result.get('checklist_progress', '')}")
    next_item = result.get("next_item")
    if next_item:
        print(f"next_item: {next_item.get('item_id', '')}")
        print(f"next_text: {next_item.get('text', '')}")
    else:
        print("next_item: none")
    if result.get("completed_task"):
        print("task_status: complete")
    elif result.get("task_completion_refused"):
        print("task_status: in_progress")
        print("task_completion: refused; checklist items remain open")


def command_projects_task_complete_next(args):
    result = complete_next_checklist_item(
        getattr(args, "task_id", ""),
        project=getattr(args, "project", None),
        log_text=getattr(args, "log", None),
        note_text=getattr(args, "note", None),
        complete_task=getattr(args, "complete_task", False),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    print_complete_next_result(result)


def command_projects_active_complete_next(args):
    data = active_next_step_data(getattr(args, "project", None))
    if not data:
        if getattr(args, "json", False):
            print(json.dumps({}, indent=2))
        else:
            print("No actionable project tasks.")
        return
    result = complete_next_checklist_item(
        data["task_id"],
        project=data["project_id"],
        log_text=getattr(args, "log", None),
        note_text=getattr(args, "note", None),
        complete_task=getattr(args, "complete_task", False),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    print_complete_next_result(result)


def command_projects_task_step_history(args):
    data = task_step_history_data(getattr(args, "task_id", ""), getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print(f"LAIA Task Step History: {getattr(args, 'task_id', '')}")
    print()
    rows = data.get("history", [])
    if not rows:
        print("No checklist history found.")
        return
    print_rows(["item_id", "status", "event", "timestamp", "text"], [
        (row.get("item_id", ""), row.get("status", ""), row.get("event", ""), row.get("timestamp", ""), row.get("text", ""))
        for row in rows
    ])


def parse_params_json(value: str) -> dict:
    try:
        data = json.loads(value or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid params JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("Action params JSON must decode to an object.")
    return data


def print_action_item(data: dict) -> None:
    item = data.get("item") or {}
    action = item.get("action") or {}
    if not action:
        print("No action configured.")
        return
    result = item.get("action_result") or {}
    print("LAIA Project Checklist Action")
    print()
    print(f"task_id: {data.get('task', {}).get('task_id', '')}")
    print(f"item_id: {item.get('item_id', '')}")
    print(f"text: {item.get('text', '')}")
    print(f"item_status: {item.get('status', '')}")
    print(f"action_type: {action.get('action_type', '')}")
    print(f"parameters: {json.dumps(action.get('parameters', {}), sort_keys=True)}")
    print(f"action_status: {item.get('action_status', '')}")
    print(f"executed_at: {item.get('action_executed_at') or ''}")
    if result.get("summary"):
        print(f"last_result: {result.get('summary', '')}")
    print(f"history_count: {len(item.get('action_history', []))}")


def print_run_action_result(data: dict) -> None:
    result = data.get("result") or {}
    print("LAIA Project Checklist Action Result")
    print()
    print(f"status: {result.get('status', '')}")
    print(f"action_type: {result.get('action_type', '')}")
    print(f"summary: {result.get('summary', '')}")
    print(f"mutated: {'yes' if data.get('mutated') else 'no'}")
    print(f"completed_item: {'yes' if data.get('completed_item') else 'no'}")
    if data.get("message"):
        print(f"message: {data.get('message', '')}")
    if data.get("checklist_progress"):
        print(f"checklist_progress: {data.get('checklist_progress', '')}")


def command_projects_task_step_action_set(args):
    params = parse_params_json(getattr(args, "params_json", "{}"))
    data = set_checklist_action(getattr(args, "task_id", ""), getattr(args, "item_id", ""), getattr(args, "type", ""), params, getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print_action_item(data)


def command_projects_task_step_action(args):
    data = checklist_action_data(getattr(args, "task_id", ""), getattr(args, "item_id", ""), getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print_action_item(data)


def command_projects_task_step_action_clear(args):
    data = clear_checklist_action(getattr(args, "task_id", ""), getattr(args, "item_id", ""), getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print(f"Cleared action for checklist item {data.get('item', {}).get('item_id', '')}")


def command_projects_task_run_step(args):
    data = run_checklist_action(
        getattr(args, "task_id", ""),
        getattr(args, "item_id", ""),
        getattr(args, "project", None),
        dry_run=getattr(args, "dry_run", False),
        complete_on_success=getattr(args, "complete_on_success", True),
    )
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print_run_action_result(data)


def command_projects_task_run_next(args):
    data = run_next_checklist_action(
        getattr(args, "task_id", ""),
        getattr(args, "project", None),
        dry_run=getattr(args, "dry_run", False),
        complete_on_success=getattr(args, "complete_on_success", True),
    )
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print_run_action_result(data)


def command_projects_active_run_next(args):
    data = active_run_next_action(
        getattr(args, "project", None),
        dry_run=getattr(args, "dry_run", False),
        complete_on_success=getattr(args, "complete_on_success", True),
    )
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print_run_action_result(data)


def command_projects_task_step_action_history(args):
    data = checklist_action_history_data(getattr(args, "task_id", ""), getattr(args, "item_id", ""), getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print(f"LAIA Checklist Action History: {getattr(args, 'item_id', '')}")
    print()
    rows = data.get("history", [])
    if not rows:
        print("No action history found.")
        return
    print_rows(["timestamp", "event", "action_type", "status", "detail"], [
        (
            row.get("timestamp", ""),
            row.get("event", ""),
            row.get("action_type", ""),
            (row.get("result") or {}).get("status", ""),
            row.get("detail", ""),
        )
        for row in rows
    ])


def load_reconciliation_report(project_identifier: str, report_name: Optional[str] = None) -> tuple[dict, Path]:
    project_id = find_project(project_identifier)
    folder = project_reconciliation_folder(project_id)
    if report_name:
        path = folder / f"{project_slug(report_name)}.json"
    else:
        reports = sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True) if folder.exists() else []
        if not reports:
            raise FileNotFoundError(f"No reconciliation reports found for project: {project_id}")
        path = reports[0]
    if not path.exists():
        raise FileNotFoundError(f"Reconciliation report not found: {path}")
    return load_json(path), path


def command_projects_reconciliation(args):
    report, json_path = load_reconciliation_report(getattr(args, "identifier", ""), getattr(args, "report_name", None))
    md_path = json_path.with_suffix(".md")
    if getattr(args, "json", False):
        print(json.dumps({"report": report, "json_path": str(json_path), "md_path": str(md_path)}, indent=2))
        return
    print("LAIA Receipt Reconciliation")
    print()
    print(f"project_id: {report.get('project_id', '')}")
    print(f"packet_count: {report.get('packet_count', 0)}")
    print(f"valid_total_count: {report.get('valid_total_count', 0)}")
    print(f"missing_total_count: {report.get('missing_total_count', 0)}")
    print(f"invalid_total_count: {report.get('invalid_total_count', 0)}")
    print(f"grand_total: {report.get('currency', '')} {report.get('grand_total', '0.00')}")
    print(f"json_path: {json_path}")
    print(f"md_path: {md_path}")
    print("warnings:")
    if report.get("warnings"):
        for warning in report["warnings"]:
            print(f"  - {warning}")
    else:
        print("  none")


def task_report_project_and_id(args) -> tuple[Optional[str], str]:
    values = list(getattr(args, "identifiers", []) or [])
    project = getattr(args, "project", None)
    if len(values) == 2:
        return values[0], values[1]
    if len(values) == 1:
        return project, values[0]
    raise ValueError("Task report command requires TASK_ID or PROJECT TASK_ID.")


def print_task_report_summary(report: dict) -> None:
    project = report.get("project", {})
    task = report.get("task", {})
    summary = report.get("summary", {})
    print("LAIA Project Task Report")
    print()
    print(f"project_id: {project.get('project_id', '')}")
    print(f"project_name: {project.get('project_name', '')}")
    print(f"task_id: {task.get('task_id', '')}")
    print(f"title: {task.get('title', '')}")
    print(f"status: {task.get('status', '')}")
    print(f"priority: {task.get('priority', '')}")
    print(f"checklist_progress: {summary.get('checklist_progress', '')}")
    print(f"successful_actions: {summary.get('successful_actions', 0)}")
    print(f"final_result: {summary.get('final_result', '')}")
    print()
    print("Outcomes:")
    if report.get("outcomes"):
        for outcome in report["outcomes"]:
            print(f"  - {outcome.get('outcome_type', '')}: {outcome.get('summary', '')}")
    else:
        print("  none")


def command_projects_task_report_export(args):
    project, task_id_value = task_report_project_and_id(args)
    result = write_task_report(task_id_value, project, getattr(args, "format", "both"), getattr(args, "output_dir", None))
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    print("LAIA Project Task Report Export")
    print()
    print(f"task_id: {result['report']['task'].get('task_id', '')}")
    print(f"task_status: {result['report']['task'].get('status', '')}")
    print(f"reports_written: {result.get('reports_written', 0)}")
    print(f"output_dir: {result.get('output_dir', '')}")
    if result.get("markdown_path"):
        print(f"markdown_path: {result.get('markdown_path', '')}")
    if result.get("json_path"):
        print(f"json_path: {result.get('json_path', '')}")


def command_projects_task_report(args):
    project, task_id_value = task_report_project_and_id(args)
    report = gather_task_report_data(task_id_value, project)
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
        return
    print_task_report_summary(report)


def command_projects_task_report_files(args):
    project, task_id_value = task_report_project_and_id(args)
    data = task_report_files_data(task_id_value, project)
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    if not data.get("markdown_path") and not data.get("json_path"):
        print("No task reports found.")
        return
    print("LAIA Project Task Report Files")
    print()
    print(f"project_id: {data.get('project_id', '')}")
    print(f"task_id: {data.get('task_id', '')}")
    print(f"task_status: {data.get('task_status', '')}")
    print(f"checklist_progress: {data.get('checklist_progress', '')}")
    print(f"generated_at: {data.get('generated_at', '')}")
    if data.get("markdown_path"):
        print(f"markdown_path: {data.get('markdown_path', '')}")
    if data.get("json_path"):
        print(f"json_path: {data.get('json_path', '')}")


def command_projects_task_reports_export(args):
    result = bulk_export_completed_task_reports(
        getattr(args, "project", None),
        getattr(args, "format", "both"),
        getattr(args, "output_root", None),
    )
    if getattr(args, "json", False):
        print(json.dumps(result, indent=2))
        return
    print("LAIA Completed Task Reports Export")
    print()
    print(f"projects_processed: {result.get('projects_processed', 0)}")
    print(f"tasks_exported: {result.get('tasks_exported', 0)}")
    print(f"reports_written: {result.get('reports_written', 0)}")


def command_projects_task_reports(args):
    rows = completed_task_report_rows(getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(rows, indent=2))
        return
    print("LAIA Completed Task Reports")
    print()
    if not rows:
        print("No completed task reports found.")
        return
    print_rows(["project_id", "task_id", "title", "task_status", "checklist", "generated_at", "report_path"], [
        (
            row.get("project_id", ""),
            row.get("task_id", ""),
            row.get("title", ""),
            row.get("task_status", ""),
            row.get("checklist_progress", ""),
            row.get("generated_at", ""),
            row.get("report_path", ""),
        )
        for row in rows
    ])


def command_projects_task_context(args):
    data = task_context_data(getattr(args, "task_id", ""), getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
        return
    print_task_context(data)


def command_projects_task_note(args):
    note = add_task_work_note(getattr(args, "task_id", ""), getattr(args, "text", ""), getattr(args, "project", None), getattr(args, "status", "active"))
    if getattr(args, "json", False):
        print(json.dumps(note, indent=2))
        return
    print(f"Added task note {note['note_id']} to task {note['task_id']}")


def command_projects_task_notes(args):
    notes = task_work_notes(getattr(args, "task_id", ""), getattr(args, "project", None), getattr(args, "status", None))
    if getattr(args, "json", False):
        print(json.dumps(notes, indent=2))
        return
    print(f"LAIA Task Notes: {getattr(args, 'task_id', '')}")
    print()
    if not notes:
        print("No task notes found.")
        return
    print_rows(["note_id", "status", "created_at", "text"], [
        (note.get("note_id", ""), note.get("status", ""), note.get("created_at", ""), note.get("text", ""))
        for note in notes
    ])


def command_projects_task_note_update(args):
    note = update_task_work_note(getattr(args, "task_id", ""), getattr(args, "note_id", ""), getattr(args, "text", ""), getattr(args, "project", None))
    print(f"Updated task note {note['note_id']} on task {note['task_id']}")


def command_projects_task_note_archive(args):
    note = archive_task_work_note(getattr(args, "task_id", ""), getattr(args, "note_id", ""), getattr(args, "project", None))
    print(f"Archived task note {note['note_id']} on task {note['task_id']}")


def command_projects_task_checklist_add(args):
    item = add_task_checklist_item(getattr(args, "task_id", ""), getattr(args, "text", ""), getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(item, indent=2))
        return
    print(f"Added checklist item {item['item_id']} to task {item['task_id']}")


def command_projects_task_checklist(args):
    items = task_checklist_items(getattr(args, "task_id", ""), getattr(args, "project", None), getattr(args, "status", None))
    if getattr(args, "json", False):
        print(json.dumps(items, indent=2))
        return
    print(f"LAIA Task Checklist: {getattr(args, 'task_id', '')}")
    print()
    if not items:
        print("No checklist items found.")
        return
    print_rows(["item_id", "status", "text", "updated_at"], [
        (item.get("item_id", ""), item.get("status", ""), item.get("text", ""), item.get("updated_at", ""))
        for item in items
    ])


def command_projects_task_checklist_complete(args):
    item = set_task_checklist_status(getattr(args, "task_id", ""), getattr(args, "item_id", ""), "complete", getattr(args, "project", None))
    print(f"Completed checklist item {item['item_id']} on task {item['task_id']}")


def command_projects_task_checklist_reopen(args):
    item = set_task_checklist_status(getattr(args, "task_id", ""), getattr(args, "item_id", ""), "open", getattr(args, "project", None))
    print(f"Reopened checklist item {item['item_id']} on task {item['task_id']}")


def command_projects_task_checklist_update(args):
    item = update_task_checklist_item(getattr(args, "task_id", ""), getattr(args, "item_id", ""), getattr(args, "text", ""), getattr(args, "project", None))
    print(f"Updated checklist item {item['item_id']} on task {item['task_id']}")


def command_projects_task_log(args):
    log = add_task_work_log(getattr(args, "task_id", ""), getattr(args, "text", ""), getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(log, indent=2))
        return
    print(f"Added work log {log['log_id']} to task {log['task_id']}")


def command_projects_task_logs(args):
    logs = task_work_logs(getattr(args, "task_id", ""), getattr(args, "project", None))
    if getattr(args, "json", False):
        print(json.dumps(logs, indent=2))
        return
    print(f"LAIA Task Work Log: {getattr(args, 'task_id', '')}")
    print()
    if not logs:
        print("No work log entries found.")
        return
    print_rows(["log_id", "created_at", "text"], [(log.get("log_id", ""), log.get("created_at", ""), log.get("text", "")) for log in logs])


def command_projects_task_link_packet(args):
    task = link_packet_to_task(getattr(args, "task_id", ""), getattr(args, "packet_id", ""), getattr(args, "project", None))
    print(f"Linked packet {getattr(args, 'packet_id', '')} to task {task['task_id']}")


def command_projects_task_link_artifact(args):
    task = link_artifact_to_task(getattr(args, "task_id", ""), getattr(args, "artifact_path", ""), getattr(args, "project", None))
    print(f"Linked artifact {getattr(args, 'artifact_path', '')} to task {task['task_id']}")


def register_projects_subcommands(sub):
    projects_p = sub.add_parser("projects", help="Project registry commands")
    projects_sub = projects_p.add_subparsers(dest="projects_command")
    try:
        from projects.sale_items import register_sale_item_subcommands
    except (ImportError, ModuleNotFoundError):
        from core.projects.sale_items import register_sale_item_subcommands
    register_sale_item_subcommands(projects_sub)
    try:
        from projects.appraisal_context import register_appraisal_context_subcommands
    except (ImportError, ModuleNotFoundError):
        from core.projects.appraisal_context import register_appraisal_context_subcommands
    register_appraisal_context_subcommands(projects_sub)
    try:
        from projects.record_visual_identification import register_record_visual_identification_subcommands
    except (ImportError, ModuleNotFoundError):
        from core.projects.record_visual_identification import register_record_visual_identification_subcommands
    register_record_visual_identification_subcommands(projects_sub)
    try:
        from projects.record_identity_evidence import register_record_identity_evidence_subcommands
    except (ImportError, ModuleNotFoundError):
        from core.projects.record_identity_evidence import register_record_identity_evidence_subcommands
    register_record_identity_evidence_subcommands(projects_sub)

    projects_sub.add_parser("list", help="List project records").set_defaults(func=command_projects_list)

    cohorts_p = projects_sub.add_parser("cohorts", help="List photo cohorts linked to a project")
    cohorts_p.add_argument("identifier")
    cohorts_p.add_argument("--json", action="store_true")
    cohorts_p.set_defaults(func=command_projects_cohorts)

    cohort_p = projects_sub.add_parser("cohort", help="Inspect one photo cohort contribution")
    cohort_p.add_argument("identifier")
    cohort_p.add_argument("cohort_id")
    cohort_p.add_argument("--json", action="store_true")
    cohort_p.set_defaults(func=command_projects_cohort)

    briefing_p = projects_sub.add_parser("briefing", help="Show project briefing")
    briefing_p.add_argument("identifier", nargs="?")
    briefing_p.add_argument("--json", action="store_true")
    briefing_p.set_defaults(func=command_projects_briefing)

    queue_p = projects_sub.add_parser("queue", help="Show portfolio-wide project task queue")
    queue_p.add_argument("--status", choices=sorted(TASK_STATUSES))
    queue_p.add_argument("--priority", choices=sorted(TASK_PRIORITIES))
    queue_p.add_argument("--project")
    queue_p.add_argument("--text")
    queue_p.add_argument("--limit", type=int)
    queue_p.add_argument("--json", action="store_true")
    queue_p.set_defaults(func=command_projects_queue)

    active_p = projects_sub.add_parser("active", help="Show active project task context")
    active_p.add_argument("--project")
    active_p.add_argument("--json", action="store_true")
    active_p.set_defaults(func=command_projects_active)

    active_next_p = projects_sub.add_parser("active-next", help="Show next step for active project work")
    active_next_p.add_argument("--project")
    active_next_p.add_argument("--json", action="store_true")
    active_next_p.set_defaults(func=command_projects_active_next)

    active_complete_next_p = projects_sub.add_parser("active-complete-next", help="Complete next step for active project work")
    active_complete_next_p.add_argument("--project")
    active_complete_next_p.add_argument("--log")
    active_complete_next_p.add_argument("--note")
    active_complete_next_p.add_argument("--complete-task", action="store_true")
    active_complete_next_p.add_argument("--json", action="store_true")
    active_complete_next_p.set_defaults(func=command_projects_active_complete_next)

    next_p = projects_sub.add_parser("next", help="Show the next actionable project task")
    next_p.add_argument("--project")
    next_p.add_argument("--json", action="store_true")
    next_p.set_defaults(func=command_projects_next)

    start_next_p = projects_sub.add_parser("start-next", help="Start the next actionable project task")
    start_next_p.add_argument("--project")
    start_next_p.add_argument("--json", action="store_true")
    start_next_p.set_defaults(func=command_projects_start_next)

    blocked_p = projects_sub.add_parser("blocked", help="Show blocked project tasks")
    blocked_p.add_argument("--project")
    blocked_p.add_argument("--json", action="store_true")
    blocked_p.set_defaults(func=command_projects_blocked)

    in_progress_p = projects_sub.add_parser("in-progress", help="Show in-progress project tasks")
    in_progress_p.add_argument("--project")
    in_progress_p.add_argument("--json", action="store_true")
    in_progress_p.set_defaults(func=command_projects_in_progress)

    task_find_p = projects_sub.add_parser("task-find", help="Find a project task globally")
    task_find_p.add_argument("task_id")
    task_find_p.set_defaults(func=command_projects_task_find)

    projects_sub.add_parser("queue-summary", help="Summarize portfolio project task queue").set_defaults(func=command_projects_queue_summary)

    reconciliation_p = projects_sub.add_parser("reconciliation", help="Inspect a project receipt reconciliation report")
    reconciliation_p.add_argument("identifier")
    reconciliation_p.add_argument("report_name", nargs="?")
    reconciliation_p.add_argument("--json", action="store_true")
    reconciliation_p.set_defaults(func=command_projects_reconciliation)

    task_report_export_p = projects_sub.add_parser("task-report-export", help="Export a project task report")
    task_report_export_p.add_argument("identifiers", nargs="+")
    task_report_export_p.add_argument("--project")
    task_report_export_p.add_argument("--format", choices=["md", "json", "both"], default="both")
    task_report_export_p.add_argument("--output-dir")
    task_report_export_p.add_argument("--json", action="store_true")
    task_report_export_p.set_defaults(func=command_projects_task_report_export)

    task_report_p = projects_sub.add_parser("task-report", help="Show a project task report")
    task_report_p.add_argument("identifiers", nargs="+")
    task_report_p.add_argument("--project")
    task_report_p.add_argument("--json", action="store_true")
    task_report_p.set_defaults(func=command_projects_task_report)

    task_report_files_p = projects_sub.add_parser("task-report-files", help="List project task report files")
    task_report_files_p.add_argument("identifiers", nargs="+")
    task_report_files_p.add_argument("--project")
    task_report_files_p.add_argument("--json", action="store_true")
    task_report_files_p.set_defaults(func=command_projects_task_report_files)

    task_reports_export_p = projects_sub.add_parser("task-reports-export", help="Export reports for completed project tasks")
    task_reports_export_p.add_argument("--project")
    task_reports_export_p.add_argument("--format", choices=["md", "json", "both"], default="both")
    task_reports_export_p.add_argument("--output-root")
    task_reports_export_p.add_argument("--json", action="store_true")
    task_reports_export_p.set_defaults(func=command_projects_task_reports_export)

    task_reports_p = projects_sub.add_parser("task-reports", help="List completed project task reports")
    task_reports_p.add_argument("--project")
    task_reports_p.add_argument("--json", action="store_true")
    task_reports_p.set_defaults(func=command_projects_task_reports)

    task_context_p = projects_sub.add_parser("task-context", help="Show detailed task work context")
    task_context_p.add_argument("task_id")
    task_context_p.add_argument("--project")
    task_context_p.add_argument("--json", action="store_true")
    task_context_p.set_defaults(func=command_projects_task_context)

    task_next_step_p = projects_sub.add_parser("task-next-step", help="Show next checklist step for a task")
    task_next_step_p.add_argument("task_id")
    task_next_step_p.add_argument("--project")
    task_next_step_p.add_argument("--json", action="store_true")
    task_next_step_p.set_defaults(func=command_projects_task_next_step)

    task_complete_next_p = projects_sub.add_parser("task-complete-next", help="Complete next checklist step for a task")
    task_complete_next_p.add_argument("task_id")
    task_complete_next_p.add_argument("--project")
    task_complete_next_p.add_argument("--log")
    task_complete_next_p.add_argument("--note")
    task_complete_next_p.add_argument("--complete-task", action="store_true")
    task_complete_next_p.add_argument("--json", action="store_true")
    task_complete_next_p.set_defaults(func=command_projects_task_complete_next)

    task_step_history_p = projects_sub.add_parser("task-step-history", help="Show task checklist step history")
    task_step_history_p.add_argument("task_id")
    task_step_history_p.add_argument("--project")
    task_step_history_p.add_argument("--json", action="store_true")
    task_step_history_p.set_defaults(func=command_projects_task_step_history)

    action_set_p = projects_sub.add_parser("task-step-action-set", help="Configure a safe action for a checklist step")
    action_set_p.add_argument("task_id")
    action_set_p.add_argument("item_id")
    action_set_p.add_argument("--type", required=True, choices=sorted(ACTION_TYPES))
    action_set_p.add_argument("--params-json", required=True)
    action_set_p.add_argument("--project")
    action_set_p.add_argument("--json", action="store_true")
    action_set_p.set_defaults(func=command_projects_task_step_action_set)

    action_p = projects_sub.add_parser("task-step-action", help="Show a checklist step action")
    action_p.add_argument("task_id")
    action_p.add_argument("item_id")
    action_p.add_argument("--project")
    action_p.add_argument("--json", action="store_true")
    action_p.set_defaults(func=command_projects_task_step_action)

    action_clear_p = projects_sub.add_parser("task-step-action-clear", help="Clear a checklist step action")
    action_clear_p.add_argument("task_id")
    action_clear_p.add_argument("item_id")
    action_clear_p.add_argument("--project")
    action_clear_p.add_argument("--json", action="store_true")
    action_clear_p.set_defaults(func=command_projects_task_step_action_clear)

    run_step_p = projects_sub.add_parser("task-run-step", help="Run the configured action for a checklist step")
    run_step_p.add_argument("task_id")
    run_step_p.add_argument("item_id")
    run_step_p.add_argument("--project")
    run_step_p.add_argument("--dry-run", action="store_true")
    run_step_p.add_argument("--complete-on-success", dest="complete_on_success", action="store_true", default=True)
    run_step_p.add_argument("--no-complete-on-success", dest="complete_on_success", action="store_false")
    run_step_p.add_argument("--json", action="store_true")
    run_step_p.set_defaults(func=command_projects_task_run_step)

    run_next_p = projects_sub.add_parser("task-run-next", help="Run the configured action for the next checklist step")
    run_next_p.add_argument("task_id")
    run_next_p.add_argument("--project")
    run_next_p.add_argument("--dry-run", action="store_true")
    run_next_p.add_argument("--complete-on-success", dest="complete_on_success", action="store_true", default=True)
    run_next_p.add_argument("--no-complete-on-success", dest="complete_on_success", action="store_false")
    run_next_p.add_argument("--json", action="store_true")
    run_next_p.set_defaults(func=command_projects_task_run_next)

    active_run_next_p = projects_sub.add_parser("active-run-next", help="Run the configured action for active project work")
    active_run_next_p.add_argument("--project")
    active_run_next_p.add_argument("--dry-run", action="store_true")
    active_run_next_p.add_argument("--complete-on-success", dest="complete_on_success", action="store_true", default=True)
    active_run_next_p.add_argument("--no-complete-on-success", dest="complete_on_success", action="store_false")
    active_run_next_p.add_argument("--json", action="store_true")
    active_run_next_p.set_defaults(func=command_projects_active_run_next)

    action_history_p = projects_sub.add_parser("task-step-action-history", help="Show checklist step action history")
    action_history_p.add_argument("task_id")
    action_history_p.add_argument("item_id")
    action_history_p.add_argument("--project")
    action_history_p.add_argument("--json", action="store_true")
    action_history_p.set_defaults(func=command_projects_task_step_action_history)

    task_note_p = projects_sub.add_parser("task-note", help="Add a task work note")
    task_note_p.add_argument("task_id")
    task_note_p.add_argument("text")
    task_note_p.add_argument("--project")
    task_note_p.add_argument("--status", choices=sorted(NOTE_STATUSES), default="active")
    task_note_p.add_argument("--json", action="store_true")
    task_note_p.set_defaults(func=command_projects_task_note)

    task_notes_p = projects_sub.add_parser("task-notes", help="List task work notes")
    task_notes_p.add_argument("task_id")
    task_notes_p.add_argument("--project")
    task_notes_p.add_argument("--status", choices=sorted(NOTE_STATUSES))
    task_notes_p.add_argument("--json", action="store_true")
    task_notes_p.set_defaults(func=command_projects_task_notes)

    task_note_update_p = projects_sub.add_parser("task-note-update", help="Update a task work note")
    task_note_update_p.add_argument("task_id")
    task_note_update_p.add_argument("note_id")
    task_note_update_p.add_argument("text")
    task_note_update_p.add_argument("--project")
    task_note_update_p.set_defaults(func=command_projects_task_note_update)

    task_note_archive_p = projects_sub.add_parser("task-note-archive", help="Archive a task work note")
    task_note_archive_p.add_argument("task_id")
    task_note_archive_p.add_argument("note_id")
    task_note_archive_p.add_argument("--project")
    task_note_archive_p.set_defaults(func=command_projects_task_note_archive)

    checklist_add_p = projects_sub.add_parser("task-checklist-add", help="Add a task checklist item")
    checklist_add_p.add_argument("task_id")
    checklist_add_p.add_argument("text")
    checklist_add_p.add_argument("--project")
    checklist_add_p.add_argument("--json", action="store_true")
    checklist_add_p.set_defaults(func=command_projects_task_checklist_add)

    checklist_p = projects_sub.add_parser("task-checklist", help="List task checklist")
    checklist_p.add_argument("task_id")
    checklist_p.add_argument("--project")
    checklist_p.add_argument("--status", choices=sorted(CHECKLIST_STATUSES))
    checklist_p.add_argument("--json", action="store_true")
    checklist_p.set_defaults(func=command_projects_task_checklist)

    checklist_complete_p = projects_sub.add_parser("task-checklist-complete", help="Complete task checklist item")
    checklist_complete_p.add_argument("task_id")
    checklist_complete_p.add_argument("item_id")
    checklist_complete_p.add_argument("--project")
    checklist_complete_p.set_defaults(func=command_projects_task_checklist_complete)

    checklist_reopen_p = projects_sub.add_parser("task-checklist-reopen", help="Reopen task checklist item")
    checklist_reopen_p.add_argument("task_id")
    checklist_reopen_p.add_argument("item_id")
    checklist_reopen_p.add_argument("--project")
    checklist_reopen_p.set_defaults(func=command_projects_task_checklist_reopen)

    checklist_update_p = projects_sub.add_parser("task-checklist-update", help="Update task checklist item")
    checklist_update_p.add_argument("task_id")
    checklist_update_p.add_argument("item_id")
    checklist_update_p.add_argument("text")
    checklist_update_p.add_argument("--project")
    checklist_update_p.set_defaults(func=command_projects_task_checklist_update)

    task_log_p = projects_sub.add_parser("task-log", help="Append task work log")
    task_log_p.add_argument("task_id")
    task_log_p.add_argument("text")
    task_log_p.add_argument("--project")
    task_log_p.add_argument("--json", action="store_true")
    task_log_p.set_defaults(func=command_projects_task_log)

    task_logs_p = projects_sub.add_parser("task-logs", help="List task work log")
    task_logs_p.add_argument("task_id")
    task_logs_p.add_argument("--project")
    task_logs_p.add_argument("--json", action="store_true")
    task_logs_p.set_defaults(func=command_projects_task_logs)

    task_link_packet_p = projects_sub.add_parser("task-link-packet", help="Link packet ID to task")
    task_link_packet_p.add_argument("task_id")
    task_link_packet_p.add_argument("packet_id")
    task_link_packet_p.add_argument("--project")
    task_link_packet_p.set_defaults(func=command_projects_task_link_packet)

    task_link_artifact_p = projects_sub.add_parser("task-link-artifact", help="Link artifact path to task")
    task_link_artifact_p.add_argument("task_id")
    task_link_artifact_p.add_argument("artifact_path")
    task_link_artifact_p.add_argument("--project")
    task_link_artifact_p.set_defaults(func=command_projects_task_link_artifact)

    note_p = projects_sub.add_parser("note", help="Add a project note")
    note_p.add_argument("identifier")
    note_p.add_argument("text")
    note_p.add_argument("--status", choices=sorted(NOTE_STATUSES), default="active")
    note_p.add_argument("--json", action="store_true")
    note_p.set_defaults(func=command_projects_note)

    notes_p = projects_sub.add_parser("notes", help="List project notes")
    notes_p.add_argument("identifier")
    notes_p.add_argument("--status", choices=sorted(NOTE_STATUSES))
    notes_p.add_argument("--json", action="store_true")
    notes_p.set_defaults(func=command_projects_notes)

    note_update_p = projects_sub.add_parser("note-update", help="Update a project note")
    note_update_p.add_argument("identifier")
    note_update_p.add_argument("note_id")
    note_update_p.add_argument("text")
    note_update_p.set_defaults(func=command_projects_note_update)

    note_archive_p = projects_sub.add_parser("note-archive", help="Archive a project note")
    note_archive_p.add_argument("identifier")
    note_archive_p.add_argument("note_id")
    note_archive_p.set_defaults(func=command_projects_note_archive)

    task_add_p = projects_sub.add_parser("task-add", help="Add a project task")
    task_add_p.add_argument("identifier")
    task_add_p.add_argument("title")
    task_add_p.add_argument("--description", default="")
    task_add_p.add_argument("--priority", choices=sorted(TASK_PRIORITIES), default="normal")
    task_add_p.add_argument("--source-packet", dest="source_packet")
    task_add_p.add_argument("--artifact")
    task_add_p.set_defaults(func=command_projects_task_add)

    tasks_p = projects_sub.add_parser("tasks", help="List project tasks")
    tasks_p.add_argument("identifier")
    tasks_p.add_argument("--status", choices=sorted(TASK_STATUSES))
    tasks_p.add_argument("--priority", choices=sorted(TASK_PRIORITIES))
    tasks_p.add_argument("--json", action="store_true")
    tasks_p.set_defaults(func=command_projects_tasks)

    task_show_p = projects_sub.add_parser("task-show", help="Show a project task")
    task_show_p.add_argument("identifier")
    task_show_p.add_argument("task_id")
    task_show_p.set_defaults(func=command_projects_task_show)

    task_start_p = projects_sub.add_parser("task-start", help="Start a project task")
    task_start_p.add_argument("identifier")
    task_start_p.add_argument("task_id")
    task_start_p.set_defaults(func=command_projects_task_start)

    task_block_p = projects_sub.add_parser("task-block", help="Block a project task")
    task_block_p.add_argument("identifier")
    task_block_p.add_argument("task_id")
    task_block_p.add_argument("--note", default="")
    task_block_p.set_defaults(func=command_projects_task_block)

    task_complete_p = projects_sub.add_parser("task-complete", help="Complete a project task")
    task_complete_p.add_argument("identifier")
    task_complete_p.add_argument("task_id")
    task_complete_p.add_argument("--note", default="")
    task_complete_p.set_defaults(func=command_projects_task_complete)

    task_cancel_p = projects_sub.add_parser("task-cancel", help="Cancel a project task")
    task_cancel_p.add_argument("identifier")
    task_cancel_p.add_argument("task_id")
    task_cancel_p.add_argument("--note", default="")
    task_cancel_p.set_defaults(func=command_projects_task_cancel)

    task_reopen_p = projects_sub.add_parser("task-reopen", help="Reopen a project task")
    task_reopen_p.add_argument("identifier")
    task_reopen_p.add_argument("task_id")
    task_reopen_p.set_defaults(func=command_projects_task_reopen)

    task_update_p = projects_sub.add_parser("task-update", help="Update a project task")
    task_update_p.add_argument("identifier")
    task_update_p.add_argument("task_id")
    task_update_p.add_argument("--title")
    task_update_p.add_argument("--description")
    task_update_p.add_argument("--priority", choices=sorted(TASK_PRIORITIES))
    task_update_p.add_argument("--source-packet", dest="source_packet")
    task_update_p.add_argument("--artifact")
    task_update_p.set_defaults(func=command_projects_task_update)

    task_summary_p = projects_sub.add_parser("task-summary", help="Summarize project tasks")
    task_summary_p.add_argument("identifier")
    task_summary_p.set_defaults(func=command_projects_task_summary)

    inspect_p = projects_sub.add_parser("inspect", help="Inspect a project record")
    inspect_p.add_argument("identifier")
    inspect_p.set_defaults(func=command_projects_inspect)

    packets_p = projects_sub.add_parser("packets", help="List packets contributing to a project")
    packets_p.add_argument("identifier")
    packets_p.set_defaults(func=command_projects_packets)

    artifacts_p = projects_sub.add_parser("artifacts", help="List artifacts linked to a project")
    artifacts_p.add_argument("identifier")
    artifacts_p.set_defaults(func=command_projects_artifacts)

    search_p = projects_sub.add_parser("search", help="Search project records")
    search_p.add_argument("--type", dest="type")
    search_p.add_argument("--status", dest="status")
    search_p.add_argument("--text", dest="text")
    search_p.add_argument("--has-open-tasks", action="store_true")
    search_p.add_argument("--has-blocked-tasks", action="store_true")
    search_p.add_argument("--priority", choices=sorted(TASK_PRIORITIES))
    search_p.add_argument("--task-text", dest="task_text")
    search_p.add_argument("--json", action="store_true")
    search_p.set_defaults(func=command_projects_search)
