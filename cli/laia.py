#!/usr/bin/env python3
import argparse
import json
import os
import sys
import subprocess
from pathlib import Path
from datetime import date, datetime
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sync.engine import sync_status as engine_sync_status, sync_run as engine_sync_run
from core_client.ollama import (
    ollama_generate,
    clean_note_text,
    structure_task,
    structure_meal,
)

LAIA_ROOT = Path(os.environ.get("LAIA_ROOT", os.path.expanduser("~/LAIA")))


def load_frontmatter(path: Path):
    if not path.exists():
        return {}, ""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    fm = yaml.safe_load(text[4:end]) or {}
    body = text[end + 5:]
    return fm, body


def tasks_dir():
    return LAIA_ROOT / "vault" / "03 Tasks"


def projects_dir():
    return LAIA_ROOT / "vault" / "02 Projects"


def plans_dir():
    return LAIA_ROOT / "vault" / "04 Daily Plans"


def inbox_dir():
    return LAIA_ROOT / "vault" / "00 Inbox"


def health_dir():
    return LAIA_ROOT / "vault" / "05 Health"


def requests_dir():
    return LAIA_ROOT / "operations" / "requests"


def results_dir():
    return LAIA_ROOT / "operations" / "results"


def load_yaml_file(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_json_file(path: Path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def get_personal_os_vault_root() -> Path:
    vault_path = os.environ.get("LAIA_VAULT_PATH")
    if vault_path:
        return Path(vault_path).expanduser()
    return LAIA_ROOT / "vaults" / "Blue Book"


def write_markdown_with_frontmatter(path: Path, frontmatter: dict, body_lines: list[str]):
    content = "---\n"
    content += yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    content += "---\n\n"
    if body_lines:
        content += "\n".join(body_lines).strip() + "\n"
    path.write_text(content, encoding="utf-8")


def get_packet_index_path() -> Path:
    index_path = LAIA_ROOT / "packets" / "index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    return index_path


def load_packet_index() -> dict:
    index_path = get_packet_index_path()
    content = load_json_file(index_path)
    if not isinstance(content, dict):
        return {"packets": []}
    if "packets" not in content or not isinstance(content["packets"], list):
        content["packets"] = []
    return content


def save_packet_index(data: dict):
    index_path = get_packet_index_path()
    index_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_packet_vault_dir() -> Path:
    vault_root = get_personal_os_vault_root()
    packet_dir = vault_root / "04_PACKETS"
    packet_dir.mkdir(parents=True, exist_ok=True)
    return packet_dir


def get_packet_note_path(packet_id: str) -> Path:
    return get_packet_vault_dir() / f"{packet_id}.md"


def write_packet_note(packet: dict):
    packet_note = get_packet_note_path(packet["packet_id"])
    frontmatter = {
        "type": "packet",
        "packet_id": packet.get("packet_id", ""),
        "title": packet.get("title", ""),
        "packet_type": packet.get("packet_type", ""),
        "status": packet.get("status", ""),
        "project": packet.get("project", ""),
        "created": packet.get("created", ""),
        "updated": packet.get("updated", ""),
        "summary": packet.get("summary", ""),
        "source_paths": packet.get("source_paths", []),
        "next_actions": packet.get("next_actions", []),
    }
    if packet.get("closed_at"):
        frontmatter["closed_at"] = packet["closed_at"]
    if packet.get("close_reason"):
        frontmatter["close_reason"] = packet["close_reason"]

    source_paths = packet.get("source_paths") or []
    next_actions = packet.get("next_actions") or []

    body_lines = [
        f"# {packet.get('title', '')}",
        "",
        f"**Packet ID:** `{packet.get('packet_id', '')}`",
        f"**Type:** `{packet.get('packet_type', '')}`",
        f"**Status:** `{packet.get('status', '')}`",
        f"**Project:** `{packet.get('project', '')}`",
        f"**Created:** `{packet.get('created', '')}`",
        f"**Updated:** `{packet.get('updated', '')}`",
    ]
    if packet.get("closed_at"):
        body_lines.extend([
            f"**Closed At:** `{packet.get('closed_at', '')}`",
            f"**Close Reason:** `{packet.get('close_reason', '')}`",
        ])
    body_lines.extend([
        "",
        "## Summary",
        "",
        packet.get("summary", "") or "No summary yet.",
        "",
        "## Source Paths",
        "",
    ])
    if source_paths:
        for path in source_paths:
            body_lines.append(f"- {path}")
    else:
        body_lines.append("- None yet")
    body_lines.extend([
        "",
        "## Next Actions",
        "",
    ])
    if next_actions:
        for action in next_actions:
            body_lines.append(f"- {action}")
    else:
        body_lines.append("- None yet")

    write_markdown_with_frontmatter(packet_note, frontmatter, body_lines)


def find_packet_record(packet_id: str):
    index = load_packet_index()
    for packet in index.get("packets", []):
        if packet.get("packet_id") == packet_id:
            return packet, index
    return None, index


def packet_update(args):
    packet_id = args.packet_id
    packet, index = find_packet_record(packet_id)
    if not packet:
        print(f"Packet not found: {packet_id}")
        return

    updated = False
    if args.status:
        packet["status"] = args.status
        updated = True
    if args.summary is not None:
        packet["summary"] = args.summary
        updated = True
    if args.project:
        packet["project"] = args.project
        updated = True
    if args.type:
        packet["packet_type"] = args.type
        updated = True
    if args.next_action:
        if "next_actions" not in packet or not isinstance(packet["next_actions"], list):
            packet["next_actions"] = []
        packet["next_actions"].append(args.next_action)
        updated = True

    if not updated:
        print("No update fields provided.")
        return

    packet["updated"] = datetime.now().isoformat()
    save_packet_index(index)
    write_packet_note(packet)
    print(f"Updated packet: {packet_id}")


def packet_close(args):
    packet_id = args.packet_id
    packet, index = find_packet_record(packet_id)
    if not packet:
        print(f"Packet not found: {packet_id}")
        return

    packet["status"] = "complete"
    packet["closed_at"] = datetime.now().isoformat()
    packet["close_reason"] = args.reason or ""
    packet["updated"] = datetime.now().isoformat()
    save_packet_index(index)
    write_packet_note(packet)
    print(f"Closed packet: {packet_id}")


def _mode_state_path() -> Path:
    return LAIA_ROOT / "state" / "mode.json"


def read_mode_state():
    path = _mode_state_path()
    if not path.exists():
        return None, path
    data = load_json_file(path)
    if not isinstance(data, dict):
        return None, path
    return data, path


def read_packet_index_file():
    index_path = LAIA_ROOT / "packets" / "index.json"
    if not index_path.exists():
        return None, index_path
    data = load_json_file(index_path)
    if not isinstance(data, dict):
        return {"packets": []}, index_path
    if "packets" not in data or not isinstance(data["packets"], list):
        data["packets"] = []
    return data, index_path


def get_report_vault_dir() -> Path:
    vault_root = get_personal_os_vault_root()
    report_dir = vault_root / "05_REPORTS"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir


def get_report_path(report_id: str) -> Path:
    return get_report_vault_dir() / f"{report_id}.md"


def build_report_id(title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(title)[:50]
    return f"report-{timestamp}-{slug}"


def report_create(args):
    packet_id = args.packet_id
    packet, _ = find_packet_record(packet_id)
    if not packet:
        print(f"Packet not found: {packet_id}")
        return

    report_id = build_report_id(packet.get("title") or packet_id)
    report_path = get_report_path(report_id)
    if report_path.exists():
        print(f"Report already exists: {report_path}")
        return

    created_at = datetime.now().isoformat()
    frontmatter = {
        "type": "report",
        "report_id": report_id,
        "source_packet": packet_id,
        "packet_type": packet.get("packet_type", ""),
        "project": packet.get("project", ""),
        "status": "draft",
        "created": created_at,
        "updated": created_at,
    }

    packet_summary = packet.get("summary") or "No summary available yet."
    next_actions = packet.get("next_actions") or []
    source_paths = packet.get("source_paths") or []

    body_lines = [
        f"# Report: {packet.get('title', packet_id)}",
        "",
        "## Overview",
        "",
        packet_summary,
        "",
        "## Source Packet",
        "",
        f"- Packet ID: `{packet_id}`",
        f"- Type: `{packet.get('packet_type', '')}`",
        f"- Status: `{packet.get('status', '')}`",
        f"- Project: `{packet.get('project', '')}`",
        "",
        "## Work Completed",
        "-",
        "",
        "## Observations",
        "-",
        "",
        "## Decisions",
        "-",
        "",
        "## Next Actions",
        "",
    ]
    if next_actions:
        for action in next_actions:
            body_lines.append(f"- {action}")
    else:
        body_lines.append("- None yet")
    body_lines.extend([
        "",
        "## Evidence / Source Paths",
        "",
    ])
    if source_paths:
        for path in source_paths:
            body_lines.append(f"- {path}")
    else:
        body_lines.append("- None yet")

    body_lines.extend([
        "",
        "## Reuse Potential",
        "-",
        "",
        "## Notes",
        "-",
    ])

    write_markdown_with_frontmatter(report_path, frontmatter, body_lines)
    print(f"Created report: {report_path}")


def report_list(_args=None):
    report_dir = get_report_vault_dir()
    reports = sorted(report_dir.glob("*.md"))
    if not reports:
        print(f"No reports found in: {report_dir}")
        return
    print("Reports:")
    for report in reports:
        print(f"- {report.stem}")


def report_show(args):
    report_path = get_report_path(args.report_id)
    if not report_path.exists():
        print(f"Report not found: {report_path}")
        return
    print(report_path.read_text(encoding="utf-8"))


def get_agent_brief_path(agent_name: str) -> Path:
    vault_root = get_personal_os_vault_root()
    system_dir = vault_root / "07_SYSTEM"
    system_dir.mkdir(parents=True, exist_ok=True)
    return system_dir / f"agent-{agent_name}.md"


def write_agent_brief(agent_name: str, lines: list[str]):
    path = get_agent_brief_path(agent_name)
    write_markdown_with_frontmatter(
        path,
        {
            "type": "agent_brief",
            "agent": agent_name,
            "status": "active",
            "updated": datetime.now().isoformat(),
        },
        lines,
    )
    print(f"Wrote agent brief: {path}")


def _format_packet_row(packet: dict) -> str:
    return (
        f"- {packet.get('packet_id', 'UNKNOWN')} | {packet.get('title', '')} | "
        f"{packet.get('status', '')} | {packet.get('packet_type', '')} | {packet.get('project', '')}"
    )


def _build_agent_brief(agent_name: str, mode_data: dict, packets: list[dict]) -> list[str]:
    current_mode = mode_data.get("current", "unknown")
    active_review_statuses = {"active", "review"}

    def matching_packets(types=None, statuses=None):
        result = []
        for packet in packets:
            if types and packet.get("packet_type") not in types:
                continue
            if statuses and packet.get("status") not in statuses:
                continue
            result.append(packet)
        return result

    def format_packet_list(title, packet_list):
        lines = [title]
        if not packet_list:
            lines.append("- None")
        else:
            for packet in packet_list:
                lines.append(_format_packet_row(packet))
        return lines

    lines = [f"{agent_name.upper()} BRIEF", ""]
    if agent_name == "operator":
        active_review_packets = matching_packets(statuses=active_review_statuses)
        blocked_packets = matching_packets(statuses={"blocked"})
        next_actions = [
            action
            for packet in active_review_packets
            for action in (packet.get("next_actions") or [])
        ]

        lines.append(f"Current mode: {current_mode}")
        lines.append("")
        lines.extend(format_packet_list("Active/Review packets:", active_review_packets))
        lines.append("")
        lines.extend(format_packet_list("Blocked packets:", blocked_packets))
        lines.append("")
        lines.append("Suggested next action:")
        if next_actions:
            for action in next_actions[:5]:
                lines.append(f"- {action}")
        else:
            lines.append("- No next actions found for active/review packets.")

    elif agent_name == "librarian":
        archive_types = {"nas", "archive", "research", "system"}
        subject_packets = matching_packets(types=archive_types)
        review_packets = matching_packets(statuses={"review"})

        lines.append("Archive safety doctrine:")
        lines.append("- Preserve original materials and source copies.")
        lines.append("- Prefer immutable, verified archive paths for critical content.")
        lines.append("- Escalate review items before archive actions.")
        lines.append("")
        lines.extend(format_packet_list("Archive-related packets:", subject_packets))
        lines.append("")
        lines.extend(format_packet_list("Packets needing review:", review_packets))

    elif agent_name == "ingest":
        ingest_types = {"ingest", "component", "photo", "document", "visual"}
        ingest_packets = matching_packets(types=ingest_types)
        active_review_packets = matching_packets(statuses=active_review_statuses)

        lines.extend(format_packet_list("Ingest-related packets:", ingest_packets))
        lines.append("")
        lines.extend(format_packet_list("Active/Review packets:", active_review_packets))

    elif agent_name == "documentation":
        complete_review_packets = matching_packets(statuses={"complete", "review"})
        missing_summary = [
            packet
            for packet in packets
            if not packet.get("summary") or not str(packet.get("summary")).strip()
        ]
        report_candidates = [
            packet
            for packet in packets
            if packet.get("summary") and packet.get("status") in {"active", "review", "complete"}
        ]

        lines.extend(format_packet_list("Complete/Review packets:", complete_review_packets))
        lines.append("")
        lines.extend(format_packet_list("Packets missing summaries:", missing_summary))
        lines.append("")
        lines.extend(format_packet_list("Candidates for reports:", report_candidates))

    return lines


def agent_list(_args=None):
    agents = {
        "operator": "Monitor current mode, manage active/review packets, and surface blocking or next actions.",
        "librarian": "Protect archive safety, review archive-related packets, and monitor review needs.",
        "ingest": "Track ingest-related packets and keep active/review work moving.",
        "documentation": "Review completed items, missing summaries, and report candidates.",
    }
    print("Supported agents:")
    for agent_name, description in agents.items():
        print(f"- {agent_name}: {description}")


def agent_brief(args):
    agent_name = args.agent_name
    mode_data, mode_path = read_mode_state()
    packet_data, packet_path = read_packet_index_file()

    if mode_data is None:
        print(f"Mode state missing: {mode_path}")
        print("Run: laia personal-os init")
        return
    if packet_data is None:
        print(f"Packet index missing: {packet_path}")
        print("Run: laia personal-os init")
        return

    packets = packet_data.get("packets", [])
    write = getattr(args, "write", False)
    all_agents = ["operator", "librarian", "ingest", "documentation"]
    targets = all_agents if agent_name == "all" else [agent_name]

    for idx, target in enumerate(targets):
        lines = _build_agent_brief(target, mode_data, packets)
        print("\n".join(lines))
        if write:
            write_agent_brief(target, lines)
        if idx != len(targets) - 1:
            print("")


def build_packet_id(title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"packet-{timestamp}-{slugify(title)}"


def build_packet_id(title: str) -> str:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"packet-{timestamp}-{slugify(title)}"


def packet_create(args):
    title = " ".join(args.title).strip()
    packet_type = args.type
    project = args.project
    status = args.status

    packet_id = build_packet_id(title)
    index = load_packet_index()
    existing_ids = {packet.get("packet_id") for packet in index.get("packets", [])}
    if packet_id in existing_ids:
        print(f"Packet already exists: {packet_id}")
        return

    created_at = datetime.now().isoformat()
    packet = {
        "packet_id": packet_id,
        "title": title,
        "packet_type": packet_type,
        "status": status,
        "project": project,
        "created": created_at,
        "updated": created_at,
        "summary": "",
        "source_paths": [],
        "next_actions": [],
    }

    index["packets"].append(packet)
    save_packet_index(index)

    packet_note = get_packet_vault_dir() / f"{packet_id}.md"
    if packet_note.exists():
        print(f"Packet note already exists: {packet_note}")
    else:
        write_markdown_with_frontmatter(
            packet_note,
            {
                "type": "packet",
                "packet_id": packet_id,
                "title": title,
                "packet_type": packet_type,
                "status": status,
                "project": project,
                "created": created_at,
                "updated": created_at,
                "summary": "",
                "source_paths": [],
                "next_actions": [],
            },
            [
                f"# {title}",
                "",
                f"**Packet ID:** `{packet_id}`",
                f"**Type:** `{packet_type}`",
                f"**Status:** `{status}`",
                f"**Project:** `{project}`",
                "",
                "## Summary",
                "",
                "",
                "## Source Paths",
                "",
                "- None yet",
                "",
                "## Next Actions",
                "",
                "- None yet",
            ],
        )
        print(f"Created packet note: {packet_note}")

    print(f"Created packet: {packet_id}")


def packet_list(_args=None):
    index = load_packet_index()
    packets = index.get("packets", [])
    print("\nLAIA PACKETS\n")
    if not packets:
        print("No packets found.")
        return
    for packet in packets:
        print(
            f"- {packet.get('packet_id', '')} | {packet.get('title', '')} | "
            f"{packet.get('packet_type', '')} | {packet.get('status', '')} | "
            f"{packet.get('project', '')}"
        )


def packet_show(args):
    packet_id = args.packet_id
    index = load_packet_index()
    packets = index.get("packets", [])
    for packet in packets:
        if packet.get("packet_id") == packet_id:
            print(json.dumps(packet, indent=2))
            return
    print(f"Packet not found: {packet_id}")


def load_sync_config():
    path = LAIA_ROOT / "core" / "configs" / "sync-config.yaml"
    data = load_yaml_file(path)
    if not data:
        raise FileNotFoundError(f"Missing sync config: {path}")
    return data


def command_exists(name):
    try:
        result = subprocess.run(
            ["which", name],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def ssh_core_reachable(config):
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=3",
                f"{config['core_user']}@{config['core_host']}",
                "echo ok",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0 and "ok" in (result.stdout or "")
    except Exception:
        return False


def priority_score(value):
    scores = {
        "Critical": 100,
        "High": 80,
        "Medium": 50,
        "Low": 20,
    }
    return scores.get(value, 0)


def time_score(value):
    scores = {
        "15m": 20,
        "30m": 18,
        "1h": 15,
        "2h": 10,
        "Half Day": 5,
        "Full Day": 2,
    }
    return scores.get(value, 0)


def momentum_score(value):
    scores = {
        "High": 20,
        "Medium": 10,
        "Low": 5,
        "None": 0,
    }
    return scores.get(value, 0)


def parse_time_to_minutes(value):
    if not value:
        return None
    value = str(value).strip().lower()
    if value.endswith("m"):
        return int(value.replace("m", ""))
    if value.endswith("h"):
        return int(value.replace("h", "")) * 60
    if value == "half day":
        return 240
    if value == "full day":
        return 480
    return None


def slugify(value: str) -> str:
    value = value.strip().lower()
    chars = []
    for ch in value:
        if ch.isalnum():
            chars.append(ch)
        elif ch in (" ", "-", "_"):
            chars.append("-")
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "item"


def count_ready_tasks():
    count = 0
    if tasks_dir().exists():
        for note in tasks_dir().glob("*.md"):
            fm, _ = load_frontmatter(note)
            if fm.get("state") == "Ready":
                count += 1
    return count


def count_recent_files(directory: Path, hours: int = 24):
    if not directory.exists():
        return 0

    now = datetime.now().timestamp()
    threshold = hours * 3600

    count = 0
    for f in directory.glob("*.md"):
        if f.stat().st_mtime >= now - threshold:
            count += 1
    return count


def get_recent_meal_energy(hours: int = 6):
    if not health_dir().exists():
        return None

    files = sorted(
        health_dir().glob("meal-*.md"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    if not files:
        return None

    latest = files[0]
    fm, body = load_frontmatter(latest)

    energy = (body or "").lower()

    if "low energy" in energy:
        return "low"
    if "tired" in energy:
        return "low"
    if "good energy" in energy:
        return "high"
    if "energized" in energy:
        return "high"

    return None


def get_energy_label():
    state = get_recent_meal_energy()
    if state == "low":
        return "Low"
    if state == "high":
        return "High"
    return "Neutral"


def load_projects_map():
    projects = {}
    proj_dir = projects_dir()
    if not proj_dir.exists():
        return projects
    for note in sorted(proj_dir.glob("*.md")):
        fm, _ = load_frontmatter(note)
        if fm and fm.get("id"):
            projects[fm["id"]] = fm
    return projects


def today_plan_path():
    return plans_dir() / f"{date.today()}-plan.md"


def briefing(_args=None):
    print(f"\nLAIA DAILY BRIEFING — {date.today()}\n")
    print("Commands:")
    print("- laia day")
    print("- laia focus")
    print("- laia sync status")
    print('- laia test-model mistral "hello"')
    print('- laia dictation note "raw note text"')
    print('- laia dictation task "raw task text"')
    print('- laia dictation meal "raw meal text"')
    print('- laia dev request "goal text"')
    print("")


def focus_task(args):
    energy_filter = getattr(args, "energy", None)
    project_filter = getattr(args, "project", None)
    max_time_filter = getattr(args, "max_time", None)

    projects = load_projects_map()
    candidates = []

    task_dir = tasks_dir()
    if task_dir.exists():
        for note in sorted(task_dir.glob("*.md")):
            fm, _ = load_frontmatter(note)
            if not fm or fm.get("state") != "Ready":
                continue

            project_id = fm.get("project_id")
            project = projects.get(project_id, {})

            if energy_filter and fm.get("energy_type") != energy_filter:
                continue
            if project_filter and project_id != project_filter:
                continue
            if max_time_filter:
                task_minutes = parse_time_to_minutes(fm.get("time_estimate"))
                limit_minutes = parse_time_to_minutes(max_time_filter)
                if task_minutes is None or limit_minutes is None or task_minutes > limit_minutes:
                    continue

            score = 0
            score += priority_score(fm.get("priority"))
            score += time_score(fm.get("time_estimate"))
            score += momentum_score(project.get("momentum"))

            if project.get("horizon") == "H1 Active":
                score += 15
            if project.get("state") == "Active":
                score += 10

            energy_state = get_recent_meal_energy()

            if energy_state == "low":
                if fm.get("energy_type") == "Deep Work":
                    score -= 20
                if parse_time_to_minutes(fm.get("time_estimate") or "") and parse_time_to_minutes(fm.get("time_estimate")) > 60:
                    score -= 10

            if energy_state == "high":
                if fm.get("energy_type") == "Deep Work":
                    score += 10

            candidates.append((score, fm, project))

    candidates.sort(key=lambda x: x[0], reverse=True)

    print("\nLAIA FOCUS\n")
    active_filters = []
    if energy_filter:
        active_filters.append(f"energy={energy_filter}")
    if project_filter:
        active_filters.append(f"project={project_filter}")
    if max_time_filter:
        active_filters.append(f"max_time={max_time_filter}")

    if active_filters:
        print("Filters: " + ", ".join(active_filters))
        print("")

    if not candidates:
        print("No matching ready tasks found.\n")
        return

    score, task, project = candidates[0]
    print("Best Next Task:")
    print(f"- {task.get('title', 'Untitled')}")
    print(f"  Task ID: {task.get('id', '')}")
    print(f"  Priority: {task.get('priority', 'Unknown')}")
    print(f"  Energy: {task.get('energy_type', 'Unknown')}")
    print(f"  Time: {task.get('time_estimate', 'Unknown')}")
    print(f"  Project: {project.get('title', task.get('project_id', 'Unknown'))}")
    print(f"  Score: {score}")
    print("")

    if len(candidates) > 1:
        print("Top Alternatives:")
        for alt_score, alt_task, alt_project in candidates[1:4]:
            print(f"- {alt_task.get('title', 'Untitled')} "
                  f"[{alt_task.get('priority', 'Unknown')}, "
                  f"{alt_task.get('time_estimate', 'Unknown')}, "
                  f"{alt_task.get('energy_type', 'Unknown')}] "
                  f"Score={alt_score}")
        print("")


def plan_generate(_args=None):
    ready = []
    task_dir = tasks_dir()
    if task_dir.exists():
        for note in sorted(task_dir.glob("*.md")):
            fm, _ = load_frontmatter(note)
            if fm.get("state") == "Ready":
                ready.append(fm)

    plans_dir().mkdir(parents=True, exist_ok=True)
    plan_path = today_plan_path()

    queued_ids = [t.get("id") for t in ready[:5]]
    body = f"# Daily Plan {date.today()}\n\n## Tasks\n"
    if ready:
        body += "\n".join([f"- [ ] {t.get('title', 'Untitled')}" for t in ready[:5]]) + "\n"
    else:
        body += "- No ready tasks found\n"

    fm = {
        "id": f"plan_{str(date.today()).replace('-', '_')}",
        "title": f"Daily Plan {date.today()}",
        "type": "daily_plan",
        "state": "Published",
        "plan_date": str(date.today()),
        "focus_1": "Advance active projects",
        "focus_2": "Maintain field operations",
        "queued_task_ids": queued_ids,
        "owner": "Paul",
        "created_at": str(date.today()),
        "updated_at": str(date.today()),
    }

    content = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n" + body
    plan_path.write_text(content, encoding="utf-8")
    print(f"Generated: {plan_path}")


def plan_today(_args=None):
    path = today_plan_path()
    if not path.exists():
        print("No plan found for today. Run: laia plan generate\n")
        return
    print(path.read_text(encoding="utf-8"))


def sync_status(_args=None):
    print("\nLAIA SYNC STATUS\n")
    config_path = LAIA_ROOT / "core" / "configs" / "sync-config.yaml"

    try:
        status = engine_sync_status(config_path, LAIA_ROOT)
    except Exception as e:
        print(f"Sync config error: {e}\n")
        return

    print(f"Core Host: {status['core_host']}")
    print(f"Core User: {status['core_user']}")
    print(f"Core reachable: {'Yes' if status['core_reachable'] else 'No'}")
    print(f"Pending conflicts: {status['pending_conflicts']}")
    print("")


def sync_dry_run(args):
    config_path = LAIA_ROOT / "core" / "configs" / "sync-config.yaml"
    reviews_dir = LAIA_ROOT / "operations" / "reviews"
    direction = "pull" if getattr(args, "pull", False) else "push"

    ok, lines, report = engine_sync_run(
        config_path,
        LAIA_ROOT,
        reviews_dir,
        direction=direction,
        dry_run=True,
    )

    for line in lines[:40]:
        print(line)

    if len(lines) > 40:
        print(f"... {len(lines) - 40} more lines")

    if report:
        print(f"\nReport: {report}\n")

    if not ok:
        raise SystemExit(1)


def sync_push(_args=None):
    config_path = LAIA_ROOT / "core" / "configs" / "sync-config.yaml"
    reviews_dir = LAIA_ROOT / "operations" / "reviews"

    ok, lines, report = engine_sync_run(
        config_path,
        LAIA_ROOT,
        reviews_dir,
        direction="push",
        dry_run=False,
    )

    for line in lines[:40]:
        print(line)

    if len(lines) > 40:
        print(f"... {len(lines) - 40} more lines")

    if report:
        print(f"\nReport: {report}\n")

    if not ok:
        raise SystemExit(1)


def sync_pull(_args=None):
    config_path = LAIA_ROOT / "core" / "configs" / "sync-config.yaml"
    reviews_dir = LAIA_ROOT / "operations" / "reviews"

    ok, lines, report = engine_sync_run(
        config_path,
        LAIA_ROOT,
        reviews_dir,
        direction="pull",
        dry_run=False,
    )

    for line in lines[:40]:
        print(line)

    if len(lines) > 40:
        print(f"... {len(lines) - 40} more lines")

    if report:
        print(f"\nReport: {report}\n")

    if not ok:
        raise SystemExit(1)


def test_model(args):
    prompt = " ".join(args.prompt)
    response = ollama_generate(args.model, prompt)
    print(response)
    print("")


def dictation_note(args):
    raw_text = " ".join(args.text)
    cleaned = clean_note_text(raw_text, model="mistral")

    target_dir = inbox_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_path = target_dir / f"dictation-note-{timestamp}.md"

    body = f"""---
type: note
source: dictation
processed_by: mistral
created_at: {datetime.now().isoformat()}
---

# Dictation Note

{cleaned}
"""
    file_path.write_text(body, encoding="utf-8")

    print(f"Saved note: {file_path}")
    print("")


def dictation_task(args):
    raw_text = " ".join(args.text)
    task = structure_task(raw_text, model="mistral")

    target_dir = tasks_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y_%m_%d_%H_%M_%S")
    title = task.get("title", "Untitled Task").strip()
    task_id = f"task_{timestamp}_{slugify(title)[:40]}"
    file_path = target_dir / f"{task_id}.md"

    fm = {
        "id": task_id,
        "title": title,
        "type": "task",
        "state": "Ready",
        "project_id": "",
        "priority": task.get("priority", "Medium"),
        "energy_type": task.get("energy_type", "Admin"),
        "time_estimate": task.get("time_estimate", "30m"),
        "dependency_ids": [],
        "next_step_after": "",
        "source": "dictation",
        "processed_by": "mistral",
        "owner": "Paul",
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    notes = task.get("notes", "").strip() or "Captured by dictation."

    content = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n"
    content += f"# {title}\n\n"
    content += "## Notes\n"
    content += f"{notes}\n"

    file_path.write_text(content, encoding="utf-8")

    print(f"Saved task: {file_path}")
    print(f"Title: {title}")
    print("")


def dictation_meal(args):
    raw_text = " ".join(args.text)
    meal = structure_meal(raw_text, model="mistral")

    target_dir = health_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    file_path = target_dir / f"meal-{timestamp}.md"

    content = f"""---
type: meal
source: dictation
processed_by: mistral
created_at: {datetime.now().isoformat()}
meal_type: {meal.get("meal_type", "Unknown")}
portion: {meal.get("portion", "Unknown")}
---

# {meal.get("meal_summary", "Meal")}

## Ingredients
{meal.get("ingredients", "")}

## Notes
{meal.get("notes", "")}

## Energy Effect
{meal.get("energy_effect", "")}
"""
    file_path.write_text(content, encoding="utf-8")

    print(f"Saved meal: {file_path}")
    print("")





def extract_request_goal(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "## Goal\n"
    if marker not in text:
        return text.strip()
    after = text.split(marker, 1)[1]
    if "\n## " in after:
        return after.split("\n## ", 1)[0].strip()
    return after.strip()



def repo_file_snapshot(limit: int = 80) -> str:
    repo_files = []
    for path in sorted(REPO_ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(REPO_ROOT)
        rel_str = str(rel)

        if rel_str.startswith(".git/"):
            continue
        if rel_str.endswith(".pyc"):
            continue
        if "/__pycache__/" in rel_str:
            continue
        if rel_str.startswith(".venv/"):
            continue

        repo_files.append(rel_str)

    return "\n".join(repo_files[:limit])


def build_dev_response(goal_text: str, model: str = "mistral") -> str:
    repo_files = repo_file_snapshot()

    prompt = f"""You are the development operator for a system called LAIA.

The user submitted this development request:

{goal_text}

Here is a snapshot of real files that exist in the repository:
{repo_files}

Write a concise implementation response with these sections in plain Markdown:

## Interpretation
Briefly explain what the request is asking for.

## Proposed Approach
Give a safe repo-first plan.

## Likely Files
List only files that exist in the repository snapshot above.

## Next Command
Give the single best next command or action.

Rules:
- do not invent files, folders, components, or services
- only mention files from the repository snapshot
- do NOT use wildcards or globs (e.g., no *.yaml)
- use exact file paths only
- if unsure of the exact file, say "uncertain" rather than guessing
- do not claim changes were already made
- do not claim tests were already run
- keep it practical and specific to LAIA
- if the exact file is uncertain, say so explicitly
"""
    return ollama_generate(model, prompt)


def dev_process_latest(args):
    d = requests_dir()
    if not d.exists():
        print("No requests directory found.")
        return

def dev_process_file(args):
    req_name = args.request_file
    req_path = requests_dir() / req_name

    if not req_path.exists():
        print(f"Request not found: {req_name}")
        return

    goal = extract_request_goal(req_path)
    response = build_dev_response(goal, model=getattr(args, "model", "mistral"))

    target_dir = results_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    result_name = f"dev-result-{timestamp}-{req_name.replace('dev-request-', '')}"
    result_path = target_dir / result_name

    content = f"""---
type: dev_result
source_request: {req_name}
created_at: {datetime.now().isoformat()}
owner: Paul
processed_by: {getattr(args, "model", "mistral")}
status: generated
---

# Dev Result

## Source Request
{req_name}

## Response
{response}
"""

    result_path.write_text(content, encoding="utf-8")

    print(f"Processed request: {req_name}")
    print(f"Saved result: {result_path}")
    print("")


    files = sorted(d.glob("dev-request-*.md"), key=lambda f: f.stat().st_mtime, reverse=True)

    # Filter only queued requests
    queued = []
    for f in files:
        fm, _ = load_frontmatter(f)
        if fm.get("status", "queued") == "queued":
            queued.append(f)

    if not queued:
        print("No queued requests.")
        return

    req_path = queued[0]
    goal = extract_request_goal(req_path)
    response = build_dev_response(goal, model=getattr(args, "model", "mistral"))

    target_dir = results_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    result_name = f"dev-result-{timestamp}-{req_path.name.replace('dev-request-', '')}"
    result_path = target_dir / result_name

    content = f"""---
type: dev_result
source_request: {req_path.name}
created_at: {datetime.now().isoformat()}
owner: Paul
processed_by: {getattr(args, "model", "mistral")}
status: generated
---

# Dev Result

## Source Request
{req_path.name}

## Response
{response}
"""

    result_path.write_text(content, encoding="utf-8")
    update_request_status(
        req_path,
        status="processed",
        processed_by=getattr(args, "model", "mistral"),
        latest_result=result_path.name,
    )

    print(f"Processed request: {req_path.name}")
    print(f"Saved result: {result_path}")
    print("")


def update_request_status(req_path: Path, *, status: str, processed_by: str, latest_result: str):
    fm, body = load_frontmatter(req_path)

    fm["status"] = status
    fm["processed_at"] = datetime.now().isoformat()
    fm["processed_by"] = processed_by
    fm["latest_result"] = latest_result

    content = "---\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\n\n" + body
    req_path.write_text(content, encoding="utf-8")

def dev_inbox(_args):
    d = requests_dir()
    if not d.exists():
        print("No requests directory found.")
        return

    files = sorted(d.glob("dev-request-*.md"), key=lambda f: f.stat().st_mtime, reverse=True)

    print("\nLAIA DEV INBOX\n")

    if not files:
        print("No pending requests.\n")
        return

    for f in files[:10]:
        print(f"- {f.name}")
    print("")


def dev_result(args):
    req_file = args.request_file
    text_body = " ".join(args.text)

    req_path = requests_dir() / req_file

    if not req_path.exists():
        print(f"Request not found: {req_file}")
        return

    target_dir = results_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    result_file = f"dev-result-{timestamp}-{req_file.replace('dev-request', '')}"
    result_path = target_dir / result_file

    content = f"""---
type: dev_result
source_request: {req_file}
created_at: {datetime.now().isoformat()}
owner: Paul
---

# Dev Result

## Response
{text_body}
"""

    result_path.write_text(content, encoding="utf-8")

    print(f"Saved result: {result_path}")
    print("")
def dev_request(args):
    target_dir = requests_dir()
    target_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    slug = slugify(" ".join(args.text))[:50]
    file_path = target_dir / f"dev-request-{timestamp}-{slug}.md"

    request_type = getattr(args, "request_type", "feature_plan")
    body = " ".join(args.text)

    content = f"""---
type: dev_request
request_type: {request_type}
source: field_node
status: queued
created_at: {datetime.now().isoformat()}
owner: Paul
---

# Dev Request

## Goal
{body}

## Constraints
- repo-first
- preserve working behavior unless explicitly changed
- keep changes auditable
"""

    file_path.write_text(content, encoding="utf-8")

    print(f"Saved dev request: {file_path}")
    print("")


def day_command(args):
    print(f"\nLAIA DAY BRIEFING — {date.today()}\n")

    print("System:")
    sync_status(args)

    print("Overview:")
    energy = get_energy_label()
    print(f"- Energy: {energy}")
    tasks = count_ready_tasks()
    notes = count_recent_files(inbox_dir(), 24)
    meals = count_recent_files(health_dir(), 24)

    print(f"- Ready tasks: {tasks}")
    print(f"- Notes (24h): {notes}")
    print(f"- Meals (24h): {meals}")
    print("")

    if not today_plan_path().exists():
        print("No daily plan found. Generating one.\n")
        plan_generate(args)

    print("Focus:")
    focus_task(args)


def doctor(_args=None):
    print("\nLAIA DOCTOR REPORT\n")

    checks = [
        ("LAIA root", LAIA_ROOT),
        ("vault", LAIA_ROOT / "vault"),
        ("projects notes", projects_dir()),
        ("tasks notes", tasks_dir()),
        ("dashboard note", LAIA_ROOT / "vault" / "01 Dashboard" / "mission-control.md"),
        ("sync config", LAIA_ROOT / "core" / "configs" / "sync-config.yaml"),
        ("node identity", LAIA_ROOT / "core" / "configs" / "node.yaml"),
    ]

    for label, path in checks:
        status = "PASS" if path.exists() else "FAIL"
        print(f"{status}: {label} — {path}")

    print("")
    print(f"PASS: python3 available — {command_exists('python3')}")
    print(f"PASS: rsync available — {command_exists('rsync')}")
    print(f"PASS: ssh available — {command_exists('ssh')}")

    try:
        config = load_sync_config()
        print(f"PASS: core reachable — {ssh_core_reachable(config)}")
    except Exception as e:
        print(f"WARN: sync config not usable — {e}")

    print("")

def personal_os_init(_args=None):
    state_dir = LAIA_ROOT / "state"
    packets_dir = LAIA_ROOT / "packets"
    vault_dashboard_dir = LAIA_ROOT / "vault" / "01 Dashboard"

    state_dir.mkdir(parents=True, exist_ok=True)
    packets_dir.mkdir(parents=True, exist_ok=True)
    vault_dashboard_dir.mkdir(parents=True, exist_ok=True)

    mode_path = state_dir / "mode.json"
    core_memory = state_dir / "core_memory.md"
    packets_index_json = packets_dir / "index.json"
    packets_index_md = packets_dir / "index.md"
    personal_md = vault_dashboard_dir / "personal-os.md"

    default_modes = [
        "idle",
        "planning",
        "focus",
        "capture",
        "review",
        "maintenance",
        "field",
        "offline",
    ]

    if not mode_path.exists():
        mode_path.write_text(
            json.dumps({
                "current": "unknown",
                "reason": "",
                "set_at": None,
                "available_modes": default_modes,
            }, indent=2),
            encoding="utf-8",
        )
        print(f"Created: {mode_path}")
    else:
        # Backfill available_modes if missing, preserving current fields
        try:
            existing = json.loads(mode_path.read_text(encoding="utf-8"))
            if not isinstance(existing, dict):
                existing = {}
        except Exception:
            existing = {}

        if "available_modes" not in existing:
            existing["available_modes"] = default_modes
            # Preserve current, reason, set_at if present; write back
            mode_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
            print(f"Updated (backfilled available_modes): {mode_path}")
        else:
            print(f"Exists: {mode_path}")

    if not core_memory.exists():
        core_memory.write_text("# Core Memory\n\n", encoding="utf-8")
        print(f"Created: {core_memory}")
    else:
        print(f"Exists: {core_memory}")

    if not packets_index_json.exists():
        packets_index_json.write_text(json.dumps({"packets": []}, indent=2), encoding="utf-8")
        print(f"Created: {packets_index_json}")
    else:
        print(f"Exists: {packets_index_json}")

    if not packets_index_md.exists():
        packets_index_md.write_text("# Packets Index\n\n", encoding="utf-8")
        print(f"Created: {packets_index_md}")
    else:
        print(f"Exists: {packets_index_md}")

    if not personal_md.exists():
        personal_md.write_text("# Personal OS\n\nThis note is managed by `laia personal-os`.\n", encoding="utf-8")
        print(f"Created: {personal_md}")
    else:
        print(f"Exists: {personal_md}")


def personal_os_doctor(_args=None):
    print("\nPERSONAL OS DOCTOR\n")
    checks = [
        ("state dir", LAIA_ROOT / "state"),
        ("mode.json", LAIA_ROOT / "state" / "mode.json"),
        ("core_memory.md", LAIA_ROOT / "state" / "core_memory.md"),
        ("packets index json", LAIA_ROOT / "packets" / "index.json"),
        ("packets index md", LAIA_ROOT / "packets" / "index.md"),
        ("personal dashboard note", LAIA_ROOT / "vault" / "01 Dashboard" / "personal-os.md"),
    ]

    for label, path in checks:
        status = "PASS" if path.exists() else "MISSING"
        print(f"{status}: {label} — {path}")


def get_blue_book_vault_root() -> Path:
    vault_path = os.environ.get("LAIA_VAULT_PATH")
    if vault_path:
        return Path(vault_path).expanduser()
    return Path(os.path.expanduser("~/Documents/Blue Book"))


def get_vault_git_remotes(vault_root: Path) -> dict:
    git_dir = vault_root / ".git"
    if not git_dir.exists():
        return {}

    try:
        result = subprocess.run(
            ["git", "-C", str(vault_root), "config", "--get-regexp", "^remote\\..*\\.url$"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}

        remotes = {}
        for line in result.stdout.strip().splitlines():
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            key, url = parts
            if not key.startswith("remote.") or not key.endswith(".url"):
                continue
            remote_name = key[len("remote.") : -len(".url")]
            remotes[remote_name] = url.strip()
        return remotes
    except Exception:
        return {}


def format_vault_git_remotes(remotes: dict) -> str:
    if not remotes:
        return "No remote configured"
    return "; ".join(f"{name}: {url}" for name, url in sorted(remotes.items()))


def paths_show(_args=None):
    vault_root = get_blue_book_vault_root()
    archive_duplicate = LAIA_ROOT / "archive" / "duplicate-vaults"
    remotes = get_vault_git_remotes(vault_root)
    git_remote_text = format_vault_git_remotes(remotes)

    print("\nLAIA PATHS\n")
    print(f"LAIA_ROOT: {LAIA_ROOT}")
    print(f"Core repo: {REPO_ROOT}")
    print(f"Blue Book vault: {vault_root}")
    print(f"Packets dir: {LAIA_ROOT / 'packets'}")
    print(f"State dir: {LAIA_ROOT / 'state'}")
    print(f"Duplicate vault archive dir: {archive_duplicate}")
    print(f"Local vault Git backup remote: {git_remote_text}")
    print("")
    print("Notes:")
    print("- `LAIA_ROOT` is the canonical container for state and packets.")
    print("- `LAIA_VAULT_PATH` controls the Blue Book vault location.")
    print("- Do not duplicate vault content inside the archive path above.")


def paths_doctor(_args=None):
    vault_root = get_blue_book_vault_root()
    archive_duplicate = LAIA_ROOT / "archive" / "duplicate-vaults"
    remotes = get_vault_git_remotes(vault_root)

    checks = [
        ("LAIA_ROOT", LAIA_ROOT),
        ("Core repo", REPO_ROOT),
        ("Blue Book vault", vault_root),
        ("Packets dir", LAIA_ROOT / "packets"),
        ("State dir", LAIA_ROOT / "state"),
        ("Duplicate vault archive dir", archive_duplicate),
    ]

    print("\nLAIA PATHS DOCTOR\n")
    for label, path in checks:
        status = "PASS" if path.exists() else "WARN"
        print(f"{status}: {label} — {path}")

    if not vault_root.exists():
        print(f"WARN: Blue Book vault does not exist — {vault_root}")
    elif not remotes:
        print(f"WARN: Local vault git has no remotes configured — {vault_root}")
    else:
        for name, url in sorted(remotes.items()):
            print(f"PASS: Local vault Git remote {name} — {url}")
    print("")


def paths_write_map(_args=None):
    vault_root = get_blue_book_vault_root()
    archive_duplicate = LAIA_ROOT / "archive" / "duplicate-vaults"
    remotes = get_vault_git_remotes(vault_root)
    git_remote_text = format_vault_git_remotes(remotes)
    state_dir = LAIA_ROOT / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    path_map = state_dir / "path-map.md"

    lines = [
        "# LAIA Path Map",
        "",
        "This document records the canonical LAIA paths used for Phase 3 preparation.",
        "",
        "## Canonical Paths",
        "",
        f"- LAIA_ROOT: `{LAIA_ROOT}`",
        f"- Core repo: `{REPO_ROOT}`",
        f"- Blue Book vault: `{vault_root}`",
        f"- Packets dir: `{LAIA_ROOT / 'packets'}`",
        f"- State dir: `{LAIA_ROOT / 'state'}`",
        f"- Duplicate vault archive dir: `{archive_duplicate}`",
        f"- Local vault Git backup remote: `{git_remote_text}`",
        "",
        "## Path Rules",
        "",
        "1. `LAIA_ROOT` is the canonical root for LAIA-managed state and packets.",
        "2. `LAIA_VAULT_PATH` may be used to override the Blue Book vault location.",
        "3. The Blue Book vault should remain separate from `LAIA_ROOT` unless explicitly configured.",
        "4. `state` and `packets` directories must live under `LAIA_ROOT`.",
        "5. `archive/duplicate-vaults` is only for archive duplicates, not the authoritative vault.",
        "6. Do not move or delete existing archive originals as part of path normalization.",
        "7. Verify `git` remote configuration for the local Blue Book vault if using backup synchronization.",
        "",
        "## Notes",
        "",
        "- If the vault path is not present, set `LAIA_VAULT_PATH` to the desired Blue Book vault directory.",
        "- Keep this file under `LAIA_ROOT/state` for local canonical path reference.",
        "",
        f"Generated: `{datetime.now().isoformat()}`",
        "",
    ]

    path_map.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote path map: {path_map}")


def get_archive_root(args=None) -> Path:
    if args is not None and getattr(args, "root", None):
        return Path(args.root).expanduser()
    archive_root = os.environ.get("LAIA_ARCHIVE_ROOT")
    if archive_root:
        return Path(archive_root).expanduser()
    return Path(os.path.expanduser("~/LAIA_ARCHIVE"))


def get_librarian_manifest_dir() -> Path:
    return LAIA_ROOT / "manifests" / "librarian"


def get_latest_manifest_paths() -> tuple[Path, Path]:
    manifest_dir = get_librarian_manifest_dir()
    return (
        manifest_dir / "manifest-latest.json",
        manifest_dir / "manifest-latest.md",
    )


def format_bytes(size: int) -> str:
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"


def scan_archive_root(root: Path) -> dict:
    ignored_names = {
        ".git",
        ".DS_Store",
        ".Trash",
        ".TemporaryItems",
        "@Recycle",
        "@Recently-Snapshot",
        "__pycache__",
    }
    if not root.exists():
        return {
            "generated_at": datetime.now().isoformat(),
            "root": str(root),
            "file_count": 0,
            "total_bytes": 0,
            "extensions": [],
            "files": [],
        }

    files = []
    extension_counts = {}
    total_bytes = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignored_names]
        for filename in filenames:
            if filename in ignored_names:
                continue
            path = Path(dirpath) / filename
            if any(part in ignored_names for part in path.parts):
                continue
            try:
                stat = path.stat()
            except (OSError, PermissionError):
                continue
            relative_path = path.relative_to(root)
            extension = path.suffix.lower() or ""
            files.append({
                "path": str(path),
                "relative_path": str(relative_path),
                "name": path.name,
                "extension": extension,
                "size_bytes": stat.st_size,
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
            total_bytes += stat.st_size
            extension_counts[extension] = extension_counts.get(extension, 0) + 1

    manifest = {
        "generated_at": datetime.now().isoformat(),
        "root": str(root),
        "file_count": len(files),
        "total_bytes": total_bytes,
        "extensions": sorted(extension_counts.keys()),
        "files": sorted(files, key=lambda item: item["relative_path"]),
    }
    return manifest


def write_librarian_manifest_files(manifest: dict) -> tuple[Path, Path]:
    manifest_dir = get_librarian_manifest_dir()
    manifest_dir.mkdir(parents=True, exist_ok=True)
    latest_json, latest_md = get_latest_manifest_paths()
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    timestamped_json = manifest_dir / f"manifest-{timestamp}.json"
    timestamped_md = manifest_dir / f"manifest-{timestamp}.md"

    json_text = json.dumps(manifest, indent=2)
    latest_json.write_text(json_text + "\n", encoding="utf-8")
    timestamped_json.write_text(json_text + "\n", encoding="utf-8")

    md_lines = [
        "# Librarian Manifest",
        "",
        f"Generated at: `{manifest['generated_at']}`",
        f"Root: `{manifest['root']}`",
        f"File count: `{manifest['file_count']}`",
        f"Total bytes: `{manifest['total_bytes']}`",
        "",
        "## Extensions",
        "",
    ]
    if manifest["extensions"]:
        for ext in manifest["extensions"]:
            md_lines.append(f"- `{ext or '<none>'}`")
    else:
        md_lines.append("- None")
    md_lines.extend([
        "",
        "## Files",
        "",
        "| Path | Relative Path | Name | Extension | Size | Modified |",
        "|---|---|---|---|---|---|",
    ])
    for file_record in manifest["files"][:100]:
        md_lines.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                file_record["path"],
                file_record["relative_path"],
                file_record["name"],
                file_record["extension"],
                format_bytes(file_record["size_bytes"]),
                file_record["modified_at"],
            )
        )
    if len(manifest["files"]) > 100:
        md_lines.append("\n...more files available in JSON manifest...")

    md_text = "\n".join(md_lines).strip() + "\n"
    latest_md.write_text(md_text, encoding="utf-8")
    timestamped_md.write_text(md_text, encoding="utf-8")
    return latest_json, latest_md


def load_latest_librarian_manifest() -> dict | None:
    latest_json, _ = get_latest_manifest_paths()
    return load_json_file(latest_json)


def librarian_scan(args):
    root = get_archive_root(args)
    if not root.exists():
        print(f"Archive root does not exist: {root}")
        return

    manifest = scan_archive_root(root)
    if getattr(args, "dry_run", False):
        print("\nLIBRARIAN SCAN (dry run)\n")
        print(f"Archive root: {root}")
        print(f"File count: {manifest['file_count']}")
        print(f"Total bytes: {format_bytes(manifest['total_bytes'])}")
        top_extensions = sorted(
            [ext for ext in manifest["extensions"] if ext],
            key=lambda x: x,
        )
        if top_extensions:
            print("Extensions:")
            for ext in top_extensions[:10]:
                print(f"- {ext}")
        else:
            print("Extensions: none")
        return

    latest_json, latest_md = write_librarian_manifest_files(manifest)
    print("\nLIBRARIAN SCAN\n")
    print(f"Wrote manifest: {latest_json}")
    print(f"Wrote manifest summary: {latest_md}")


def librarian_find(args):
    query = " ".join(args.query).strip().lower()
    manifest = load_latest_librarian_manifest()
    if not manifest:
        print("No manifest found. Run: laia librarian scan")
        return

    matches = []
    for file_record in manifest.get("files", []):
        if query in file_record.get("relative_path", "").lower() or query in file_record.get("name", "").lower():
            matches.append(file_record)
            if len(matches) >= 25:
                break

    if not matches:
        print(f"No results for query: {query}")
        return

    print(f"\nLIBRARIAN FIND — {len(matches)} result(s)\n")
    for file_record in matches:
        print(f"- {file_record['relative_path']} ({format_bytes(file_record['size_bytes'])})")


def librarian_packet(args):
    query = " ".join(args.query).strip().lower()
    manifest = load_latest_librarian_manifest()
    if not manifest:
        print("No manifest found. Run: laia librarian scan")
        return

    matches = []
    for file_record in manifest.get("files", []):
        if query in file_record.get("relative_path", "").lower() or query in file_record.get("name", "").lower():
            matches.append(file_record)

    if not matches:
        print(f"No files matched query: {query}")
        return

    title = f"Librarian retrieval: {query}"
    packet_id = build_packet_id(title)
    index = load_packet_index()
    packet = {
        "packet_id": packet_id,
        "title": title,
        "packet_type": "librarian",
        "status": "review",
        "project": "librarian",
        "created": datetime.now().isoformat(),
        "updated": datetime.now().isoformat(),
        "summary": f"Retrieval packet for query: {query}",
        "source_paths": [file_record["path"] for file_record in matches],
        "next_actions": [],
    }
    index.setdefault("packets", []).append(packet)
    save_packet_index(index)
    write_packet_note(packet)

    print(f"Created librarian packet: {packet_id}")
    print(f"Matched files: {len(matches)}")


def librarian_report(_args=None):
    latest_json, _ = get_latest_manifest_paths()
    manifest = load_latest_librarian_manifest()
    if not latest_json.exists() or not manifest:
        print("No Librarian manifest found. Run: laia librarian scan")
        return

    vault_root = get_blue_book_vault_root()
    reports_dir = vault_root / "05_REPORTS"
    reports_dir.mkdir(parents=True, exist_ok=True)
    report_path = reports_dir / "librarian-manifest-report.md"

    front = {
        "type": "report",
        "report_id": "librarian-manifest-report",
        "project": "LAIA Librarian",
        "report_type": "manifest",
        "status": "active",
        "updated": datetime.now().isoformat(),
        "archive_root": manifest.get("root"),
        "file_count": manifest.get("file_count"),
        "total_bytes": manifest.get("total_bytes"),
    }

    body = []
    body.append("# Librarian Manifest Report")
    body.append("")
    body.append("## Summary")
    body.append(f"- Archive root: `{manifest.get('root')}`")
    body.append(f"- File count: `{manifest.get('file_count')}`")
    body.append(f"- Total size: `{format_bytes(manifest.get('total_bytes', 0))}`")
    body.append(f"- Generated: `{manifest.get('generated_at')}`")
    body.append("")

    # Top extensions with counts and bytes
    ext_stats = {}
    for f in manifest.get("files", []):
        ext = f.get("extension") or ""
        stats = ext_stats.setdefault(ext, {"count": 0, "bytes": 0})
        stats["count"] += 1
        stats["bytes"] += f.get("size_bytes", 0)

    body.append("## Top Extensions")
    body.append("")
    body.append("| Extension | Count | Bytes |")
    body.append("|---|---:|---:|")
    for ext, stats in sorted(ext_stats.items(), key=lambda kv: kv[1]["count"], reverse=True):
        body.append(f"| {ext or '<none>'} | {stats['count']} | {format_bytes(stats['bytes'])} |")
    body.append("")

    # Largest files
    files = manifest.get("files", [])
    largest = sorted(files, key=lambda x: x.get("size_bytes", 0), reverse=True)[:20]
    body.append("## Largest Files")
    body.append("")
    body.append("| File | Size | Modified |")
    body.append("|---|---:|---|")
    for f in largest:
        body.append(f"| {f.get('relative_path')} | {format_bytes(f.get('size_bytes',0))} | {f.get('modified_at')} |")
    body.append("")

    # Recent files
    recent = sorted(files, key=lambda x: x.get("modified_at", ""), reverse=True)[:20]
    body.append("## Recent Files")
    body.append("")
    body.append("| File | Size | Modified |")
    body.append("|---|---:|---|")
    for f in recent:
        body.append(f"| {f.get('relative_path')} | {format_bytes(f.get('size_bytes',0))} | {f.get('modified_at')} |")
    body.append("")

    body.append("## Notes")
    body.append("")
    body.append("- This is a read-only report.")
    body.append("- No archive originals were moved, renamed, deleted, or modified.")

    write_markdown_with_frontmatter(report_path, front, body)
    print(f"Wrote Librarian manifest report: {report_path}")


def personal_os_dashboard(_args=None):
    personal_md = LAIA_ROOT / "vault" / "01 Dashboard" / "personal-os.md"
    if not personal_md.exists():
        print("Dashboard note not found. Run: laia personal-os init")
        return
    print(personal_md.read_text(encoding="utf-8"))


def personal_os_sync_obsidian(_args=None):
    vault_root = get_personal_os_vault_root()
    system_dir = vault_root / "07_SYSTEM"
    packets_dir = vault_root / "04_PACKETS"
    system_dir.mkdir(parents=True, exist_ok=True)
    packets_dir.mkdir(parents=True, exist_ok=True)

    mode_path = LAIA_ROOT / "state" / "mode.json"
    packets_index_path = LAIA_ROOT / "packets" / "index.json"

    mode_data = load_json_file(mode_path) or {}
    packet_data = load_json_file(packets_index_path) or {}
    packet_list = packet_data.get("packets") if isinstance(packet_data, dict) else None

    current_mode_path = system_dir / "current-mode.md"
    current_mode = mode_data.get("current", "unknown")
    current_reason = mode_data.get("reason", "")
    current_updated = mode_data.get("set_at") or datetime.now().isoformat()
    write_markdown_with_frontmatter(
        current_mode_path,
        {
            "type": "mode_state",
            "mode": current_mode,
            "reason": current_reason,
            "updated": current_updated,
        },
        [
            "# Current Mode",
            "",
            f"Mode: `{current_mode}`",
            f"Reason: `{current_reason}`",
            f"Updated: `{current_updated}`",
        ],
    )

    core_health_path = system_dir / "core-health.md"
    core_status = "active" if mode_data else "missing state"
    health_updated = datetime.now().isoformat()
    write_markdown_with_frontmatter(
        core_health_path,
        {
            "type": "core-health",
            "service": "LAIA Core",
            "status": core_status,
            "updated": health_updated,
        },
        [
            "# Core Health",
            "",
            f"State file: `{mode_path}`",
            f"Packets index file: `{packets_index_path}`",
            f"Status: `{core_status}`",
            f"Updated: `{health_updated}`",
        ],
    )

    packets_output_path = packets_dir / "index.md"
    packet_count = len(packet_list) if isinstance(packet_list, list) else 0
    body_lines = ["# Packet Index", "", f"{packet_count} packets registered", ""]
    if packet_count:
        body_lines.extend([
            "| Packet | Type | Status | Project |",
            "| --- | --- | --- | --- |",
        ])
        for packet in packet_list:
            packet_name = packet.get("name") or packet.get("id") or packet.get("packet", "")
            packet_type = packet.get("type", "")
            packet_status = packet.get("status", "")
            packet_project = packet.get("project", "")
            body_lines.append(f"| {packet_name} | {packet_type} | {packet_status} | {packet_project} |")
    else:
        body_lines = ["# Packet Index", "", "No packets registered yet."]

    write_markdown_with_frontmatter(
        packets_output_path,
        {
            "type": "packet_index",
            "updated": datetime.now().isoformat(),
            "packet_count": packet_count,
        },
        body_lines,
    )

    print(f"Exported personal-os state to vault: {vault_root}")


def get_personal_os_log_path(date_str: str) -> Path:
    return get_personal_os_vault_root() / "06_LOGS" / f"{date_str}.md"


def get_personal_os_report_files() -> list[Path]:
    report_dir = get_personal_os_vault_root() / "05_REPORTS"
    if not report_dir.exists():
        return []
    return sorted(report_dir.glob("*.md"))


def get_personal_os_agent_brief_files() -> list[Path]:
    system_dir = get_personal_os_vault_root() / "07_SYSTEM"
    if not system_dir.exists():
        return []
    return sorted(system_dir.glob("agent-*.md"))


def get_personal_os_tasks() -> list[dict]:
    tasks_dir = get_personal_os_vault_root() / "03_TASKS"
    if not tasks_dir.exists():
        return []

    tasks = []
    for task_path in sorted(tasks_dir.glob("*.md")):
        fm, _ = load_frontmatter(task_path)
        state = (fm.get("state") or "open").strip()
        state_low = state.lower()
        if state_low in {"done", "completed", "closed", "cancelled", "canceled", "resolved"}:
            continue
        title = fm.get("title") or task_path.stem
        tasks.append({"path": task_path, "title": title, "state": state or "open"})
    return tasks


def get_daily_brief_path() -> Path:
    system_dir = get_personal_os_vault_root() / "07_SYSTEM"
    system_dir.mkdir(parents=True, exist_ok=True)
    return system_dir / "daily-briefing.md"


def _format_brief_packet_row(packet: dict) -> str:
    return (
        f"- {packet.get('packet_id', 'UNKNOWN')} | {packet.get('title', '')} | "
        f"{packet.get('packet_type', '')} | {packet.get('status', '')} | {packet.get('project', '')}"
    )


def _format_file_link(prefix: str, path: Path) -> str:
    return f"- [[{prefix}/{path.stem}]]"


def _build_personal_os_brief(date_str: str, mode_data: dict, packets: list[dict], tasks: list[dict], reports: list[Path], agent_briefs: list[Path]) -> list[str]:
    lines = [f"# LAIA Daily Briefing — {date_str}", ""]

    current_mode = mode_data.get("current", "unknown")
    current_reason = mode_data.get("reason", "")
    lines.extend([
        "## Current Mode",
        "",
        f"- Mode: `{current_mode}`",
        f"- Reason: `{current_reason}`",
        "",
    ])

    log_path = get_personal_os_log_path(date_str)
    lines.extend(["## Today’s Log", ""])
    if log_path.exists():
        lines.append(f"- [[06_LOGS/{date_str}]]")
    else:
        lines.append(f"- No log found for today. Create it at `06_LOGS/{date_str}.md`.")
    lines.append("")

    active_review_packets = [p for p in packets if p.get("status") in {"active", "review"}]
    blocked_packets = [p for p in packets if p.get("status") == "blocked"]

    lines.extend(["## Active / Review Packets", ""])
    if active_review_packets:
        for packet in active_review_packets:
            lines.append(_format_brief_packet_row(packet))
    else:
        lines.append("- None")
    lines.append("")

    lines.extend(["## Blocked Packets", ""])
    if blocked_packets:
        for packet in blocked_packets:
            lines.append(_format_brief_packet_row(packet))
    else:
        lines.append("- None")
    lines.append("")

    lines.extend(["## Open Tasks", ""])
    if tasks:
        for task in tasks:
            lines.append(f"- [[03_TASKS/{task['path'].stem}]] — {task['title']} ({task['state']})")
    else:
        lines.append("- None")
    lines.append("")

    lines.extend(["## Reports", ""])
    if reports:
        for report in reports:
            lines.append(f"- [[05_REPORTS/{report.stem}]]")
    else:
        lines.append("- None")
    lines.append("")

    lines.extend(["## Agent Notes", ""])
    if agent_briefs:
        for brief in agent_briefs:
            lines.append(f"- [[07_SYSTEM/{brief.stem}]]")
    else:
        lines.append("- None")
    lines.append("")

    suggestions = []
    for packet in active_review_packets:
        for action in packet.get("next_actions") or []:
            if action and len(suggestions) < 3:
                suggestions.append(f"Review next action for {packet.get('packet_id')}: {action}")
    if len(suggestions) < 3 and tasks:
        for task in tasks:
            suggestions.append(f"Work on task [[03_TASKS/{task['path'].stem}]]")
            if len(suggestions) >= 3:
                break
    if len(suggestions) < 3 and reports:
        suggestions.append(f"Review report [[05_REPORTS/{reports[0].stem}]]")
    while len(suggestions) < 3:
        if not suggestions:
            suggestions.append("Review active packet statuses and update next actions.")
        elif len(suggestions) == 1:
            suggestions.append("Update the daily log with any new observations.")
        else:
            suggestions.append("Check agent notes and incorporate any new guidance.")

    lines.extend(["## Suggested Next Actions", ""])
    for suggestion in suggestions[:3]:
        lines.append(f"- {suggestion}")

    return lines


def personal_os_briefing(args):
    date_str = date.today().isoformat()
    mode_data, mode_path = read_mode_state()
    packet_data, packet_path = read_packet_index_file()

    if mode_data is None:
        print(f"Mode state missing: {mode_path}")
        print("Run: laia personal-os init")
        mode_data = {}
    if packet_data is None:
        print(f"Packet index missing: {packet_path}")
        print("Run: laia personal-os init")
        packet_data = {"packets": []}

    packets = packet_data.get("packets", []) if isinstance(packet_data, dict) else []
    tasks = get_personal_os_tasks()
    reports = get_personal_os_report_files()
    agent_briefs = get_personal_os_agent_brief_files()
    lines = _build_personal_os_brief(date_str, mode_data or {}, packets, tasks, reports, agent_briefs)

    if args.write:
        brief_path = get_daily_brief_path()
        write_markdown_with_frontmatter(
            brief_path,
            {
                "type": "daily_briefing",
                "date": date_str,
                "mode": mode_data.get("current", "unknown") if isinstance(mode_data, dict) else "unknown",
                "status": "active",
                "updated": datetime.now().isoformat(),
            },
            lines,
        )
        print(f"Wrote daily briefing: {brief_path}")
    else:
        print("\n".join(lines))


def _mode_path() -> Path:
    state_dir = LAIA_ROOT / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / "mode.json"


def mode_list(_args=None):
    path = _mode_path()
    if not path.exists():
        print("No mode state found. Run: laia personal-os init or set a mode.")


def personal_os_validate_phase2(args):
    """Validate Phase 2 readiness for LAIA Personal OS.

    Reads LAIA_ROOT state and packet index, checks vault structure and
    key sync files. If --write is set, writes a validation report
    to the Blue Book vault under `05_REPORTS/phase-2-validation-report.md`.
    """
    vault_root = get_personal_os_vault_root()
    checks = []  # list of (check_name, status, detail)

    # 1. mode.json
    mode_path = LAIA_ROOT / "state" / "mode.json"
    mode = load_json_file(mode_path)
    if not mode or not isinstance(mode, dict):
        checks.append(("mode.json", "FAIL", f"Missing or invalid: {mode_path}"))
    else:
        required_keys = ["current", "reason", "set_at", "available_modes"]
        missing = [k for k in required_keys if k not in mode]
        if missing:
            checks.append(("mode.json", "WARN", f"Missing keys: {', '.join(missing)}"))
        else:
            checks.append(("mode.json", "PASS", "OK"))

    # 2. packets/index.json
    packet_index = load_packet_index()
    packet_index_path = get_packet_index_path()
    if not packet_index or not isinstance(packet_index, dict) or not packet_index.get("packets"):
        checks.append(("packets/index.json", "WARN", f"Missing or empty: {packet_index_path}"))
    else:
        checks.append(("packets/index.json", "PASS", f"{len(packet_index.get('packets', []))} packets"))

    # 3. Obsidian homepage
    home_md = vault_root / "00_HOME" / "LAIA_HOME.md"
    if home_md.exists():
        checks.append(("Obsidian homepage", "PASS", str(home_md)))
    else:
        checks.append(("Obsidian homepage", "WARN", str(home_md)))

    # 4. Blue Book folders
    required_folders = [
        "00_HOME", "03_TASKS", "04_PACKETS", "05_REPORTS",
        "06_LOGS", "07_SYSTEM", "99_TEMPLATES",
    ]
    for f in required_folders:
        p = vault_root / f
        checks.append((f"vault/{f}", "PASS" if p.exists() else "WARN", str(p)))

    # 5. Core sync files in 07_SYSTEM
    system_files = [
        "current-mode.md", "core-health.md", "daily-briefing.md",
        "agent-operator.md", "agent-librarian.md", "agent-ingest.md", "agent-documentation.md",
    ]
    system_dir = vault_root / "07_SYSTEM"
    for fn in system_files:
        p = system_dir / fn
        checks.append((f"07_SYSTEM/{fn}", "PASS" if p.exists() else "WARN", str(p)))

    # 6. Agent brief files (already included above)

    # 7. Daily briefing
    db = system_dir / "daily-briefing.md"
    checks.append(("daily-briefing.md", "PASS" if db.exists() else "WARN", str(db)))

    # 8. Templates folder has markdown
    templates_dir = vault_root / "99_TEMPLATES"
    md_templates = list(templates_dir.glob("*.md")) if templates_dir.exists() else []
    checks.append(("templates", "PASS" if md_templates else "WARN", f"{len(md_templates)} templates"))

    # 9. At least one packet exists
    packet_count = len(packet_index.get("packets", [])) if isinstance(packet_index, dict) else 0
    checks.append(("packets exist", "PASS" if packet_count > 0 else "WARN", f"{packet_count} packets"))

    # 10. At least one report exists
    reports = get_personal_os_report_files()
    checks.append(("reports exist", "PASS" if reports else "WARN", f"{len(reports)} reports"))

    # Summarize to terminal
    print("\nLAIA PERSONAL-OS PHASE 2 VALIDATION\n")
    print(f"Vault: {vault_root}")
    print("")
    print("| Check | Status | Detail |")
    print("|---|---:|---|")
    for name, status, detail in checks:
        print(f"| {name} | {status} | {detail} |")

    # Built command surface
    commands = [
        "laia packet create/list/show/update/close",
        "laia agent list",
        "laia agent brief operator",
        "laia agent brief all --write",
        "laia report create/list/show",
        "laia personal-os briefing",
        "laia personal-os briefing --write",
        "laia personal-os sync-obsidian",
        "laia personal-os validate-phase2",
    ]

    print("\nBuilt command surface:")
    for c in commands:
        print(f"- {c}")

    if args.write:
        # Build report frontmatter and body
        report_id = "phase-2-validation-report"
        report_path = get_personal_os_vault_root() / "05_REPORTS" / f"{report_id}.md"
        front = {
            "type": "report",
            "report_id": report_id,
            "project": "LAIA Personal OS",
            "report_type": "validation",
            "status": "draft",
            "created": datetime.now().isoformat(),
            "updated": datetime.now().isoformat(),
        }

        body = []
        body.append("# LAIA Personal OS Phase 2 Validation Report")
        body.append("")
        body.append("## Executive Summary")
        body.append("Phase 2 establishes structured memory and role-based intelligence (packets, briefs, reports, daily briefing, Obsidian sync, dashboard, git-backed vault).")
        body.append("")
        body.append("## Phase 2 Scope")
        for s in ["Packets","Packet lifecycle","Agent briefs","Writable agent briefs","Reports","Daily briefing","Obsidian sync","Dashboard visibility","Git audit trail"]:
            body.append(f"- {s}")
        body.append("")
        body.append("## Validation Results")
        body.append("| Check | Status | Detail |")
        body.append("|---|---:|---|")
        for name, status, detail in checks:
            body.append(f"| {name} | {status} | {detail} |")
        body.append("")
        body.append("## Built Command Surface")
        for c in commands:
            body.append(f"- {c}")
        body.append("")
        body.append("## Source of Truth")
        body.append("- JSON state: `LAIA_ROOT/state` and `LAIA_ROOT/packets`")
        body.append("- Human-readable synced state: Blue Book vault")
        body.append("- Git: repository history and audit trail")
        body.append("")
        body.append("## What Works Now")
        for name, status, detail in checks:
            if status == "PASS":
                body.append(f"- {name}: {detail}")
        body.append("")
        body.append("## Gaps / Warnings")
        for name, status, detail in checks:
            if status in ("WARN", "FAIL"):
                body.append(f"- {name}: {status} — {detail}")
        body.append("")
        body.append("## What Is Intentionally Not Automated Yet")
        body.extend(["- archive modification","- NAS restructuring","- ingest watchers","- Home Assistant/Grocy actions","- autonomous agent actions"])
        body.append("")
        body.append("## Phase 3 Readiness")
        body.append("Assess next steps toward Phase 3 based on gaps above.")
        body.append("")
        body.append("## Next Actions")
        body.extend(["1. Fill missing Blue Book files listed in Gaps.", "2. Confirm ComfyUI outputs collection and integrate collector.", "3. Automate agent brief writable flows.", "4. Add monitoring for packet lifecycle events.", "5. Run full staged tests with ComfyUI live runs."])

        # Ensure reports dir exists
        report_dir = report_path.parent
        report_dir.mkdir(parents=True, exist_ok=True)
        write_markdown_with_frontmatter(report_path, front, body)
        print(f"Wrote validation report: {report_path}")

        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print("Unable to read mode state.")
        return

    available = data.get("available_modes")
    if not available:
        print("No available modes defined in mode state.")
        return
    print("Available modes:")
    for m in available:
        print(f"- {m}")


def mode_show(_args=None):
    path = _mode_path()
    if not path.exists():
        print("Mode not set. Run: laia mode set <mode> --reason \"reason\"")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        print("Unable to read mode state.")
        return

    print("Current mode:")
    print(f"- mode: {data.get('current')}")
    print(f"- reason: {data.get('reason')}")
    print(f"- set_at: {data.get('set_at')}")


def mode_set(args):
    mode_value = getattr(args, "mode", None)
    reason = getattr(args, "reason", "")
    if not mode_value:
        print("Mode value required.")
        raise SystemExit(1)

    path = _mode_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        data = {}

    data["current"] = mode_value
    data["reason"] = reason
    data["set_at"] = datetime.now().isoformat()

    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"Mode set: {mode_value}")


# ---------------------------------------------------------------------
# LAIA Documents / Obsidian Vault Mirror
# ---------------------------------------------------------------------

BLUE_BOOK_VAULT = Path.home() / "LAIA" / "vaults" / "Blue Book"


def run_cmd(cmd, cwd=None, check=True):
    result = subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )

    if result.stdout:
        print(result.stdout.strip())

    if result.stderr:
        print(result.stderr.strip())

    if check and result.returncode != 0:
        raise SystemExit(result.returncode)

    return result


def documents_status(args):
    vault = BLUE_BOOK_VAULT

    if not vault.exists():
        print(f"Vault mirror not found: {vault}")
        raise SystemExit(1)

    print("==> LAIA Documents")
    print(f"Vault: {vault}")
    print()

    print("==> Git status")
    run_cmd(["git", "status", "--short"], cwd=vault, check=False)

    print()
    print("==> Branch")
    run_cmd(["git", "branch", "--show-current"], cwd=vault, check=False)

    print()
    print("==> Latest commit")
    run_cmd(["git", "log", "-1", "--oneline"], cwd=vault, check=False)


def documents_pull(args):
    vault = BLUE_BOOK_VAULT

    if not vault.exists():
        print(f"Vault mirror not found: {vault}")
        raise SystemExit(1)

    print("==> Pulling Blue Book vault mirror")
    run_cmd(["git", "pull", "--ff-only"], cwd=vault)

    print()
    print("==> Current status")
    run_cmd(["git", "status", "--short"], cwd=vault, check=False)


def documents_log(args):
    vault = BLUE_BOOK_VAULT

    if not vault.exists():
        print(f"Vault mirror not found: {vault}")
        raise SystemExit(1)

    count = str(getattr(args, "count", 8))

    print("==> Recent Blue Book commits")
    run_cmd(["git", "log", f"-{count}", "--oneline", "--decorate"], cwd=vault, check=False)


def documents_archive_status(_args=None):
    base = LAIA_ROOT / "archive" / "library" / "documents"

    paths = {
        "inbox": base / "inbox",
        "inbox_action": base / "inbox" / "action",
        "inbox_records": base / "inbox" / "records",
        "inbox_junk": base / "inbox" / "junk",
        "action": base / "action",
        "records": base / "records",
        "junk": base / "junk",
    }

    def count_pdfs(path: Path) -> int:
        if not path.exists():
            return 0
        return sum(
            1 for f in path.iterdir()
            if f.is_file() and f.suffix.lower() == ".pdf"
        )

    inbox_total = (
        count_pdfs(paths["inbox"]) +
        count_pdfs(paths["inbox_action"]) +
        count_pdfs(paths["inbox_records"]) +
        count_pdfs(paths["inbox_junk"])
    )

    print("\n=== LAIA Documents Archive Status ===\n")
    print("Inbox:")
    print(f"  Total:   {inbox_total}")
    print(f"  Action:  {count_pdfs(paths['inbox_action'])}")
    print(f"  Records: {count_pdfs(paths['inbox_records'])}")
    print(f"  Junk:    {count_pdfs(paths['inbox_junk'])}")

    print("\nArchive:")
    print(f"  Action:  {count_pdfs(paths['action'])}")
    print(f"  Records: {count_pdfs(paths['records'])}")
    print(f"  Junk:    {count_pdfs(paths['junk'])}")
    print("")




def load_frontmatter_safe_for_index(path: Path):
    """
    Load Obsidian Markdown frontmatter for indexing.

    Obsidian templates may contain placeholders like {{date:YYYY-MM-DD}},
    which are useful inside Obsidian but invalid YAML. For indexing, treat
    invalid frontmatter as plain note text instead of failing loudly.
    """
    text = path.read_text(encoding="utf-8")

    if not text.startswith("---\n"):
        return {}, text

    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text

    try:
        fm = yaml.safe_load(text[4:end]) or {}
        body = text[end + 5:]
        return fm, body
    except Exception:
        return {}, text


def markdown_title(path: Path, body: str, fm: dict) -> str:
    if fm.get("title"):
        return str(fm["title"]).strip()

    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()

    return path.stem


def markdown_excerpt(body: str, limit: int = 500) -> str:
    lines = []
    in_code = False

    for line in body.splitlines():
        stripped = line.strip()

        if stripped.startswith("```"):
            in_code = not in_code
            continue

        if in_code:
            continue

        if not stripped:
            continue

        if stripped.startswith("![[") or stripped.startswith("!["):
            continue

        lines.append(stripped)

    text = " ".join(lines)
    if len(text) <= limit:
        return text

    return text[:limit].rsplit(" ", 1)[0] + "..."


def documents_index(args):
    vault = BLUE_BOOK_VAULT

    if not vault.exists():
        print(f"Vault mirror not found: {vault}")
        raise SystemExit(1)

    output_dir = Path.home() / "LAIA" / "indexes"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_path = output_dir / "blue-book-index.json"

    include_body = getattr(args, "include_body", False)

    records = []

    for note in sorted(vault.rglob("*.md")):
        if ".obsidian" in note.parts:
            continue
        if ".git" in note.parts:
            continue
        if "99_TEMPLATES" in note.parts:
            continue
        if "Templates" in note.parts:
            continue

        fm, body = load_frontmatter_safe_for_index(note)

        rel = str(note.relative_to(vault))
        stat = note.stat()

        record = {
            "path": rel,
            "absolute_path": str(note),
            "title": markdown_title(note, body, fm),
            "type": fm.get("type", "note") if isinstance(fm, dict) else "note",
            "tags": fm.get("tags", []) if isinstance(fm, dict) else [],
            "created_at": fm.get("created_at") if isinstance(fm, dict) else None,
            "updated_at": fm.get("updated_at") if isinstance(fm, dict) else None,
            "modified_timestamp": stat.st_mtime,
            "size_bytes": stat.st_size,
            "excerpt": markdown_excerpt(body),
        }

        if include_body:
            record["body"] = body

        records.append(record)

    index = {
        "index_type": "laia_blue_book_markdown_index",
        "vault": str(vault),
        "generated_at": datetime.now().isoformat(),
        "note_count": len(records),
        "include_body": include_body,
        "records": records,
    }

    output_path.write_text(
        json.dumps(index, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("==> LAIA Documents Index")
    print(f"Vault: {vault}")
    print(f"Notes indexed: {len(records)}")
    print(f"Index written: {output_path}")

    if records:
        print()
        print("==> Sample records")
        for record in records[:5]:
            print(f"- {record['title']} — {record['path']}")


def documents_search(args):
    index_path = Path.home() / "LAIA" / "indexes" / "blue-book-index.json"

    if not index_path.exists():
        print("Index not found. Run: laia documents index")
        raise SystemExit(1)

    query = " ".join(args.query).lower()
    data = json.loads(index_path.read_text(encoding="utf-8"))

    matches = []

    for record in data.get("records", []):
        haystack = " ".join([
            str(record.get("title", "")),
            str(record.get("path", "")),
            str(record.get("type", "")),
            " ".join(record.get("tags", []) if isinstance(record.get("tags"), list) else []),
            str(record.get("excerpt", "")),
            str(record.get("body", "")),
        ]).lower()

        if query in haystack:
            matches.append(record)

    print(f"==> Search: {query}")
    print(f"Matches: {len(matches)}")
    print()

    for record in matches[:20]:
        print(f"- {record.get('title', 'Untitled')}")
        print(f"  Path: {record.get('path')}")
        excerpt = record.get("excerpt")
        if excerpt:
            print(f"  {excerpt[:220]}")
        print("")




DOCUMENT_QUERY_STOPWORDS = {
    "what", "does", "blue", "book", "say", "about", "through", "using",
    "only", "with", "from", "into", "that", "this", "there", "their",
    "would", "could", "should", "explain", "tell", "give", "show",
    "lens", "note", "notes", "source", "sources"
}


def document_query_terms(text: str) -> list[str]:
    cleaned = (
        text.replace("?", " ")
        .replace(",", " ")
        .replace(".", " ")
        .replace(";", " ")
        .replace(":", " ")
        .replace("/", " ")
        .replace("-", " ")
    )

    terms = []
    for term in cleaned.split():
        term = term.strip().lower()
        if len(term) <= 2:
            continue
        if term in DOCUMENT_QUERY_STOPWORDS:
            continue
        terms.append(term)

    return terms


def score_document_record(record: dict, query_terms: list[str]) -> int:
    haystack = " ".join([
        str(record.get("title", "")),
        str(record.get("path", "")),
        str(record.get("type", "")),
        " ".join(record.get("tags", []) if isinstance(record.get("tags"), list) else []),
        str(record.get("excerpt", "")),
        str(record.get("body", "")),
    ]).lower()

    score = 0

    for term in query_terms:
        if not term:
            continue

        title = str(record.get("title", "")).lower()
        path = str(record.get("path", "")).lower()
        excerpt = str(record.get("excerpt", "")).lower()
        body = str(record.get("body", "")).lower()

        if term in title:
            score += 10
        if term in path:
            score += 6
        if term in excerpt:
            score += 4
        if term in body:
            score += 2
        if term in haystack:
            score += 1

    path_text = str(record.get("path", "")).lower()

    # Strong topical folder boosts for LAIA research areas.
    if "tarot" in query_terms and "/tarot/" in path_text:
        score += 12
    if "archetype" in query_terms or "archetypes" in query_terms:
        if "/archetypes/" in path_text:
            score += 12
    if "jung" in query_terms or "jungian" in query_terms:
        if "red book" in path_text or "/archetypes/" in path_text:
            score += 8
    if "individuation" in query_terms or "shadow" in query_terms:
        if "shadow" in path_text or "/archetypes/" in path_text or "/tarot/" in path_text:
            score += 6

    return score


def load_documents_index(include_body_if_missing: bool = False):
    index_path = Path.home() / "LAIA" / "indexes" / "blue-book-index.json"

    if not index_path.exists():
        print("Index not found. Building one now...")
        class Args:
            include_body = include_body_if_missing
        documents_index(Args())

    return json.loads(index_path.read_text(encoding="utf-8"))


def documents_ask(args):
    question = " ".join(args.question).strip()
    model = getattr(args, "model", "mistral")
    limit = getattr(args, "limit", 8)

    if not question:
        print("Ask needs a question.")
        raise SystemExit(1)

    data = load_documents_index(include_body_if_missing=False)
    records = data.get("records", [])

    query_terms = document_query_terms(question)

    scored = []
    for record in records:
        score = score_document_record(record, query_terms)
        if score > 0:
            scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)

    # Keep weak accidental matches out of model context.
    min_score = getattr(args, "min_score", 6)
    selected = [record for score, record in scored if score >= min_score][:limit]

    if not selected:
        print("No matching Blue Book notes found in the index.")
        print("Try: laia documents index --include-body")
        raise SystemExit(1)

    context_blocks = []
    for idx, record in enumerate(selected, start=1):
        title = record.get("title", "Untitled")
        rel_path = record.get("path", "")
        excerpt = record.get("excerpt", "")

        context_blocks.append(
            f"[{idx}] {title}\n"
            f"Path: {rel_path}\n"
            f"Excerpt:\n{excerpt}\n"
        )

    context = "\n---\n".join(context_blocks)

    mode = getattr(args, "mode", "strict")

    if mode == "interpretive":
        prompt = f"""You are LAIA's local symbolic research assistant.

Use the Blue Book Obsidian vault context below as your source material.

You may make clearly labeled symbolic, Jungian, archetypal, or systems-thinking interpretations, but you must distinguish:
- what the notes explicitly say
- what you are inferring from the notes
- what remains uncertain or needs more source material

Question:
{question}

Blue Book context:
{context}

Answer for Paul in Markdown with these sections:

## Direct Source Reading
Summarize what the selected Blue Book notes explicitly say.

## Interpretive / Jungian Reading
Make careful symbolic or archetypal inferences from the selected notes.

## LAIA Research Use
Explain how this could be useful as a LAIA research packet, agent memory, personal knowledge map, or symbolic interface.

## Gaps / Follow-up
Name missing sources, weak spots, or next notes to inspect.

## Sources Used
List the note paths you relied on.
"""
    else:
        prompt = f"""You are LAIA's local document assistant.

Use only the Blue Book Obsidian vault context below. If the answer is not supported by the context, say that the current index does not contain enough information.

Question:
{question}

Blue Book context:
{context}

Answer in a practical way for Paul. Include the note paths you relied on.
"""

    print(f"==> Asking {model} using {len(selected)} Blue Book notes")
    print()

    response = ollama_generate(model, prompt)
    print(response)
    print()

    print("==> Sources")
    for record in selected:
        print(f"- {record.get('title', 'Untitled')} — {record.get('path', '')}")


def documents_context(args):
    question = " ".join(args.question).strip()
    limit = getattr(args, "limit", 8)

    data = load_documents_index(include_body_if_missing=False)
    records = data.get("records", [])

    query_terms = document_query_terms(question)

    scored = []
    for record in records:
        score = score_document_record(record, query_terms)
        if score > 0:
            scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)

    print(f"==> Context candidates for: {question}")
    print()

    for score, record in scored[:limit]:
        print(f"- Score {score}: {record.get('title', 'Untitled')}")
        print(f"  Path: {record.get('path', '')}")
        excerpt = record.get("excerpt")
        if excerpt:
            print(f"  {excerpt[:260]}")
        print("")



def slugify_packet_name(value: str) -> str:
    return slugify(value)[:80]


def select_document_context(question: str, *, limit: int = 8, min_score: int = 6):
    data = load_documents_index(include_body_if_missing=False)
    records = data.get("records", [])

    query_terms = document_query_terms(question)

    scored = []
    for record in records:
        score = score_document_record(record, query_terms)
        if score >= min_score:
            scored.append((score, record))

    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[:limit]


def documents_packet(args):
    topic = " ".join(args.topic).strip()
    model = getattr(args, "model", "mistral")
    limit = getattr(args, "limit", 8)
    min_score = getattr(args, "min_score", 10)
    ask_model = getattr(args, "ask_model", False)
    mode = getattr(args, "mode", "strict")

    if not topic:
        print("Packet needs a topic.")
        raise SystemExit(1)

    selected_scored = select_document_context(
        topic,
        limit=limit,
        min_score=min_score,
    )

    if not selected_scored:
        print(f"No matching Blue Book notes found for packet topic: {topic}")
        print("Try a lower threshold, for example: --min-score 4")
        raise SystemExit(1)

    packet_root = Path.home() / "LAIA" / "context-packets" / "blue-book"
    packet_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    topic_slug = slugify_packet_name(topic)
    packet_id = f"{timestamp}-{topic_slug}"

    packet_dir = packet_root / packet_id
    packet_dir.mkdir(parents=True, exist_ok=True)

    json_path = packet_dir / "packet.json"
    md_path = packet_dir / "packet.md"

    sources = []
    context_blocks = []

    for idx, (score, record) in enumerate(selected_scored, start=1):
        source = {
            "index": idx,
            "score": score,
            "title": record.get("title", "Untitled"),
            "path": record.get("path", ""),
            "absolute_path": record.get("absolute_path", ""),
            "type": record.get("type", "note"),
            "tags": record.get("tags", []),
            "excerpt": record.get("excerpt", ""),
        }
        sources.append(source)

        context_blocks.append(
            f"[{idx}] {source['title']}\n"
            f"Score: {score}\n"
            f"Path: {source['path']}\n\n"
            f"{source['excerpt']}\n"
        )

    generated_summary = None

    if ask_model:
        context = "\n---\n".join(context_blocks)

        if mode == "interpretive":
            prompt = f"""You are LAIA's local symbolic research assistant.

Build an interpretive context packet summary using only the Blue Book source excerpts below.

You may make clearly labeled symbolic, Jungian, archetypal, or systems-thinking interpretations, but separate direct evidence from inference.

Topic:
{topic}

Source excerpts:
{context}

Return Markdown with:
# Summary
## Direct Source Reading
## Interpretive / Jungian Reading
## LAIA Research Use
## Key Symbols / Archetypes
## Gaps / follow-up notes

Include source path references inline where useful.
"""
        else:
            prompt = f"""You are LAIA's local Librarian Node.

Build a concise context packet summary using only the Blue Book source excerpts below.

Topic:
{topic}

Source excerpts:
{context}

Return Markdown with:
# Summary
## What this packet contains
## Key facts
## Useful commands or paths
## Gaps / follow-up notes

Include source path references inline where useful.
"""

        print(f"==> Asking {model} to summarize packet context")
        generated_summary = ollama_generate(model, prompt)

    packet = {
        "packet_type": "laia_blue_book_context_packet",
        "packet_id": packet_id,
        "topic": topic,
        "generated_at": datetime.now().isoformat(),
        "vault": str(BLUE_BOOK_VAULT),
        "index_path": str(Path.home() / "LAIA" / "indexes" / "blue-book-index.json"),
        "model_summary_generated": ask_model,
        "model": model if ask_model else None,
        "mode": mode,
        "limit": limit,
        "min_score": min_score,
        "source_count": len(sources),
        "sources": sources,
        "summary": generated_summary,
    }

    json_path.write_text(
        json.dumps(packet, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    md = []
    md.append("---")
    md.append(f"type: context_packet")
    md.append(f"packet_id: {packet_id}")
    md.append(f"topic: {topic}")
    md.append(f"source: blue_book")
    md.append(f"source_count: {len(sources)}")
    md.append(f"generated_at: {packet['generated_at']}")
    md.append("---")
    md.append("")
    md.append(f"# Context Packet — {topic}")
    md.append("")
    md.append(f"- Packet ID: `{packet_id}`")
    md.append(f"- Vault: `{BLUE_BOOK_VAULT}`")
    md.append(f"- Sources: `{len(sources)}`")
    md.append(f"- Min score: `{min_score}`")
    md.append(f"- Mode: `{mode}`")
    md.append("")

    if generated_summary:
        md.append("## Model Summary")
        md.append("")
        md.append(generated_summary)
        md.append("")

    md.append("## Sources")
    md.append("")

    for source in sources:
        md.append(f"### [{source['index']}] {source['title']}")
        md.append("")
        md.append(f"- Score: `{source['score']}`")
        md.append(f"- Path: `{source['path']}`")
        md.append(f"- Type: `{source['type']}`")
        if source.get("tags"):
            md.append(f"- Tags: `{source['tags']}`")
        md.append("")
        md.append("#### Excerpt")
        md.append("")
        md.append(source.get("excerpt", "") or "_No excerpt available._")
        md.append("")

    md_path.write_text("\n".join(md), encoding="utf-8")

    latest_md = packet_root / f"{topic_slug}-latest.md"
    latest_json = packet_root / f"{topic_slug}-latest.json"

    latest_md.write_text(md_path.read_text(encoding="utf-8"), encoding="utf-8")
    latest_json.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")

    print("==> LAIA Context Packet")
    print(f"Topic: {topic}")
    print(f"Packet ID: {packet_id}")
    print(f"Sources: {len(sources)}")
    print(f"Markdown: {md_path}")
    print(f"JSON: {json_path}")
    print()
    print("==> Source summary")
    for source in sources:
        print(f"- Score {source['score']}: {source['title']} — {source['path']}")


def add_documents_parser(subparsers):
    documents = subparsers.add_parser(
        "documents",
        help="Manage LAIA Obsidian vault mirrors",
    )

    document_subcommands = documents.add_subparsers(
        dest="documents_command",
        required=True,
    )

    status = document_subcommands.add_parser(
        "status",
        help="Show Blue Book vault mirror status",
    )
    status.set_defaults(func=documents_status)

    pull = document_subcommands.add_parser(
        "pull",
        help="Pull latest Blue Book changes into the Core mirror",
    )
    pull.set_defaults(func=documents_pull)

    log = document_subcommands.add_parser(
        "log",
        help="Show recent Blue Book commits",
    )
    log.add_argument(
        "-n",
        "--count",
        type=int,
        default=8,
        help="Number of commits to show",
    )
    log.set_defaults(func=documents_log)

    index = document_subcommands.add_parser(
        "index",
        help="Build a JSON index of the Blue Book Markdown vault",
    )
    index.add_argument(
        "--include-body",
        action="store_true",
        help="Store full note bodies in the JSON index",
    )
    index.set_defaults(func=documents_index)

    search = document_subcommands.add_parser(
        "search",
        help="Search the generated Blue Book Markdown index",
    )
    search.add_argument("query", nargs="+")
    search.set_defaults(func=documents_search)

    ask = document_subcommands.add_parser(
        "ask",
        help="Ask a local Ollama model a question using the Blue Book index",
    )
    ask.add_argument("question", nargs="+")
    ask.add_argument(
        "--model",
        default="mistral",
        help="Ollama model to use, for example mistral, llama3, qwen2.5:7b",
    )
    ask.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Number of matching notes to include as context",
    )
    ask.add_argument(
        "--min-score",
        type=int,
        default=6,
        help="Minimum relevance score required for model context",
    )
    ask.add_argument(
        "--mode",
        choices=["strict", "interpretive"],
        default="strict",
        help="Answer mode: strict source summary or clearly labeled symbolic interpretation",
    )
    ask.set_defaults(func=documents_ask)

    context = document_subcommands.add_parser(
        "context",
        help="Preview which Blue Book notes would be used as model context",
    )
    context.add_argument("question", nargs="+")
    context.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Number of context candidates to show",
    )
    context.set_defaults(func=documents_context)

    packet = document_subcommands.add_parser(
        "packet",
        help="Build a reusable LAIA context packet from matching Blue Book notes",
    )
    packet.add_argument("topic", nargs="+")
    packet.add_argument(
        "--limit",
        type=int,
        default=8,
        help="Number of source notes to include",
    )
    packet.add_argument(
        "--min-score",
        type=int,
        default=10,
        help="Minimum relevance score required for packet sources",
    )
    packet.add_argument(
        "--ask-model",
        action="store_true",
        help="Ask the local model to generate a packet summary",
    )
    packet.add_argument(
        "--model",
        default="mistral",
        help="Ollama model to use when --ask-model is enabled",
    )
    packet.add_argument(
        "--mode",
        choices=["strict", "interpretive"],
        default="strict",
        help="Packet summary mode: strict source summary or clearly labeled symbolic interpretation",
    )
    packet.set_defaults(func=documents_packet)

    archive = subparsers.add_parser(
        "documents-archive",
        help="Show legacy PDF/archive document status",
    )

    archive_subcommands = archive.add_subparsers(
        dest="documents_archive_command",
        required=True,
    )

    archive_status = archive_subcommands.add_parser(
        "status",
        help="Show PDF/archive document counts",
    )
    archive_status.set_defaults(func=documents_archive_status)



def nas_manifest_dir():
    return LAIA_ROOT / "archive" / "nas_manifests"


def nas_latest(_args=None):
    d = nas_manifest_dir()
    md = d / "nas_manifest_latest.md"
    js = d / "nas_manifest_latest.json"

    print("\nLAIA NAS LATEST\n")
    print(f"Manifest dir: {d}")
    print(f"Markdown: {'PASS' if md.exists() else 'MISSING'} — {md}")
    print(f"JSON: {'PASS' if js.exists() else 'MISSING'} — {js}")

    if md.exists():
        print("")
        print("Preview:")
        text = md.read_text(encoding="utf-8", errors="replace")
        print("\n".join(text.splitlines()[:30]))
    print("")


def nas_manifests(_args=None):
    d = nas_manifest_dir()

    print("\nLAIA NAS MANIFESTS\n")

    if not d.exists():
        print(f"Missing manifest directory: {d}\n")
        return

    files = sorted(
        d.glob("nas_manifest_*"),
        key=lambda f: f.stat().st_mtime,
        reverse=True
    )

    if not files:
        print("No NAS manifests found.\n")
        return

    for f in files[:20]:
        print(f"- {f.name}")

    print("")


def nas_find(args):
    import json

    query = " ".join(args.query).lower()

    d = nas_manifest_dir()
    js = d / "nas_manifest_latest.json"
    md = d / "nas_manifest_latest.md"

    print(f"\nLAIA NAS FIND — {query}\n")

    matches = []

    if js.exists():
        rows = json.loads(js.read_text(encoding="utf-8", errors="replace"))

        for row in rows:
            haystack = " ".join([
                str(row.get("path", "")),
                str(row.get("relative_path", "")),
                str(row.get("filename", "")),
                str(row.get("extension", "")),
                str(row.get("top_level_dir", "")),
            ]).lower()

            if query in haystack:
                matches.append(row)

        if not matches:
            print("No matches found in latest JSON manifest.\n")
            return

        for row in matches[:50]:
            size = row.get("size_bytes", "")
            rel = row.get("relative_path", row.get("path", ""))
            mod = row.get("modified_time", "")
            print(f"- {rel} | {size} bytes | modified {mod}")

        if len(matches) > 50:
            print(f"\n... {len(matches)-50} more matches")

        print("")
        return

    if md.exists():
        for line in md.read_text(
            encoding="utf-8",
            errors="replace"
        ).splitlines():
            if query in line.lower():
                matches.append(line)

        if not matches:
            print("No matches found in latest markdown manifest.\n")
            return

        for line in matches[:50]:
            print(line)

        if len(matches) > 50:
            print(f"\n... {len(matches)-50} more matches")

        print("")
        return

    print(f"Missing latest manifest JSON: {js}")
    print(f"Missing latest manifest Markdown: {md}\n")


def packets_dir():
    return LAIA_ROOT / "packets"


def nas_retrieval_packets_dir():
    return packets_dir() / "nas_retrieval"




def packet_categories():
    return {
        "nas_retrieval": packets_dir() / "nas_retrieval",
        "visual": packets_dir() / "visual",
        "ocr": packets_dir() / "ocr",
    }


def find_packet(name_or_category, maybe_name=None):
    categories = packet_categories()

    if maybe_name:
        d = categories.get(name_or_category)
        if not d:
            return None
        p = d / maybe_name
        return p if p.exists() else None

    for d in categories.values():
        p = d / name_or_category
        if p.exists():
            return p

    return None


def packets_show(args):
    packet = find_packet(
        args.category_or_name,
        getattr(args, "packet_name", None)
    )

    print("\nLAIA PACKET SHOW\n")

    if not packet:
        print("Packet not found. Use: laia packets list\\n")
        return

    print(f"Packet: {packet}\n")

    preferred = [
        "README.md",
        "query.txt",
        "prompt.txt",
        "results.txt",
        "notes.md"
    ]

    for name in preferred:
        f = packet / name
        if f.exists():
            print(f"## {name}")
            print(
                f.read_text(
                    encoding="utf-8",
                    errors="replace"
                )[:4000]
            )
            print("")

    other_files = sorted(
        f.name for f in packet.iterdir()
        if f.is_file() and f.name not in preferred
    )

    if other_files:
        print("## Other files")
        for name in other_files:
            print(f"- {name}")
        print("")

def packets_list(_args=None):
    print("\nLAIA PACKETS\n")

    categories = {
        "nas_retrieval": packets_dir() / "nas_retrieval",
        "visual": packets_dir() / "visual",
        "ocr": packets_dir() / "ocr",
    }

    found_any = False

    for label, d in categories.items():
        print(f"## {label}")

        if not d.exists():
            print(f"- Missing: {d}\n")
            continue

        packets = sorted(
            [p for p in d.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if not packets:
            print("- No packets found.\n")
            continue

        found_any = True

        for packet in packets[:10]:
            print(f"- {packet.name}")

        print("")

    if not found_any:
        print("No packets found.\n")

def packets_latest(args=None):
    print("\nLAIA LATEST PACKET\n")

    categories = packet_categories()

    category = getattr(args, "category", None) if args else None

    if category:
        selected = {
            category: categories.get(category)
        }
    else:
        selected = categories

    latest_packet = None

    for label, d in selected.items():
        if not d or not d.exists():
            continue

        packets = sorted(
            [p for p in d.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if packets:
            candidate = packets[0]

            if (
                latest_packet is None or
                candidate.stat().st_mtime >
                latest_packet.stat().st_mtime
            ):
                latest_packet = candidate

    if not latest_packet:
        print("No packets found.\\n")
        return

    print(latest_packet)

    readme = latest_packet / "README.md"

    if readme.exists():
        print("")
        print(
            readme.read_text(
                encoding="utf-8",
                errors="replace"
            )[:4000]
        )

    print("")

def packets_create(args):
    import json

    kind = args.kind
    query = " ".join(args.query)
    slug = slugify(query)[:60]
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = nas_retrieval_packets_dir() / f"{stamp}-{slug}"
    target.mkdir(parents=True, exist_ok=False)

    manifest_json = nas_manifest_dir() / "nas_manifest_latest.json"
    matches = []

    if kind == "nas-search" and manifest_json.exists():
        rows = json.loads(manifest_json.read_text(encoding="utf-8", errors="replace"))
        q = query.lower()
        for row in rows:
            haystack = " ".join([
                str(row.get("path", "")),
                str(row.get("relative_path", "")),
                str(row.get("filename", "")),
                str(row.get("extension", "")),
                str(row.get("top_level_dir", "")),
            ]).lower()
            if q in haystack:
                matches.append(row)

    (target / "query.txt").write_text(query + "\n", encoding="utf-8")

    results_lines = []
    for row in matches[:200]:
        results_lines.append(
            f"{row.get('relative_path', row.get('path', ''))} | "
            f"{row.get('size_bytes', '')} bytes | "
            f"modified {row.get('modified_time', '')}"
        )
    (target / "results.txt").write_text("\n".join(results_lines) + ("\n" if results_lines else ""), encoding="utf-8")

    (target / "manifest_excerpt.json").write_text(
        json.dumps(matches[:200], indent=2),
        encoding="utf-8"
    )

    readme = f"""# LAIA Retrieval Packet

Type: {kind}
Query: {query}
Created: {datetime.now().isoformat()}

## Source Artifact

- Manifest JSON: {manifest_json}

## Results

- Matches captured: {len(matches)}
- Results stored: {min(len(matches), 200)}

## Rules

- Originals are sacred.
- This packet is read-only evidence.
- Any copy/move/rename requires explicit approval.
"""
    (target / "README.md").write_text(readme, encoding="utf-8")
    (target / "notes.md").write_text("# Notes\n\n", encoding="utf-8")

    print(f"Created packet: {target}")
    print(f"Matches: {len(matches)}")
    print("")


def visual_profiles_dir():
    return REPO_ROOT / "services" / "visual" / "profiles"


def visual_services_dir() -> Path:
    return REPO_ROOT / "services" / "visual"


def visual_comfy_dir() -> Path:
    # Allow override to point to a different local ComfyUI install (e.g. on Mac mini)
    env = os.environ.get("LAIA_COMFY_DIR")
    if env:
        return Path(env).expanduser()
    return visual_services_dir() / "ComfyUI"


def visual_models_dir() -> Path:
    return visual_comfy_dir() / "models"


def visual_workflows_dir() -> Path:
    # Primary workflows directory inside repo; Comfy blueprints are separate
    return visual_services_dir() / "workflows"


def _resolve_workflow_path(profile_workflow: str, profile_name: str) -> Path:
    """Resolve workflow path using search order described in config.

    Order:
      - absolute path if provided
      - visual_workflows_dir() / profile_workflow
      - visual_workflows_dir() / "api" / profile_workflow
      - visual_comfy_dir() / "blueprints" / profile_workflow
      - fallback: visual_workflows_dir() / f"laia_{profile_name}.json"
    """
    # Absolute path
    candidate = Path(profile_workflow).expanduser()
    if candidate.is_absolute() and candidate.exists():
        return candidate

    # repo workflows
    w1 = visual_workflows_dir() / profile_workflow
    if w1.exists():
        return w1

    w2 = visual_workflows_dir() / "api" / profile_workflow
    if w2.exists():
        return w2

    w3 = visual_comfy_dir() / "blueprints" / profile_workflow
    if w3.exists():
        return w3

    # fallback
    fb = visual_workflows_dir() / f"laia_{profile_name}.json"
    return fb


def visual_status(_args=None):
    import urllib.request

    print("\nLAIA VISUAL STATUS\n")

    url = "http://127.0.0.1:8188"

    try:
        with urllib.request.urlopen(url, timeout=3) as r:
            print(f"ComfyUI reachable: PASS ({url})")
            print(f"HTTP status: {r.status}")
    except Exception as e:
        print(f"ComfyUI reachable: FAIL ({url})")
        print(f"Error: {e}")

    print("")


def visual_profiles(_args=None):
    d = visual_profiles_dir()

    print("\nLAIA VISUAL PROFILES\n")

    if not d.exists():
        print(f"Missing profiles dir: {d}\n")
        return

    profiles = sorted(d.glob("*.yaml"))

    if not profiles:
        print("No visual profiles found.\n")
        return

    for p in profiles:
        print(f"- {p.stem}")

    print("")


def visual_profile(args):
    p = visual_profiles_dir() / f"{args.name}.yaml"

    print(f"\nLAIA VISUAL PROFILE — {args.name}\n")

    if not p.exists():
        print(f"Missing profile: {p}\n")
        return

    print(p.read_text(encoding="utf-8", errors="replace"))
    print("")


def visual_run(args):
    profile_path = visual_profiles_dir() / f"{args.profile}.yaml"

    print(f"\nLAIA VISUAL RUN — {args.profile}\n")

    if not profile_path.exists():
        print(f"Missing profile: {profile_path}\n")
        return

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}

    prompt = " ".join(args.prompt) if getattr(args, "prompt", None) else ""

    print("Mode: DRY RUN" if args.dry_run else "Mode: LIVE RUN")
    print("")
    print(f"Profile: {profile.get('name', args.profile)}")
    print(f"Description: {profile.get('description', '')}")
    print(f"Checkpoint: {profile.get('checkpoint', '')}")
    print("")
    print("Positive prompt:")
    for item in profile.get("positive", []):
        print(f"- {item}")
    if prompt:
        print(f"- {prompt}")

    print("")
    print("Negative prompt:")
    for item in profile.get("negative", []):
        print(f"- {item}")

    outputs = profile.get("outputs", {})
    print("")
    print("Output:")
    print(f"- Folder: {outputs.get('folder', 'services/visual/outputs')}")
    print(f"- Prefix: {outputs.get('prefix', 'laia_visual')}")

    if args.dry_run:
        print("\nNo image generated. Dry run only.\n")
        return

    print("\nLIVE RUN is not enabled yet. Add workflow execution after dry-run validation.\n")


def visual_packets_dir():
    return LAIA_ROOT / "packets" / "visual"


def visual_packet(args):
    profile_path = visual_profiles_dir() / f"{args.profile}.yaml"

    print(f"\nLAIA VISUAL PACKET — {args.profile}\n")

    if not profile_path.exists():
        print(f"Missing profile: {profile_path}\n")
        return

    prompt = " ".join(args.prompt).strip()
    slug = slugify(prompt)[:60] if prompt else args.profile
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target = visual_packets_dir() / f"{stamp}-{slug}"
    target.mkdir(parents=True, exist_ok=False)

    profile_text = profile_path.read_text(encoding="utf-8", errors="replace")
    profile = yaml.safe_load(profile_text) or {}

    positives = profile.get("positive", [])
    negatives = profile.get("negative", [])
    outputs = profile.get("outputs", {})

    (target / "prompt.txt").write_text(prompt + "\n", encoding="utf-8")
    (target / "profile.yaml").write_text(profile_text, encoding="utf-8")
    (target / "positive.txt").write_text("\n".join(positives + ([prompt] if prompt else [])) + "\n", encoding="utf-8")
    (target / "negative.txt").write_text("\n".join(negatives) + "\n", encoding="utf-8")
    (target / "notes.md").write_text("# Notes\n\n", encoding="utf-8")

    readme = f"""# LAIA Visual Packet

Type: visual-generation
Profile: {args.profile}
Created: {datetime.now().isoformat()}

## Prompt

{prompt}

## Source Profile

- {profile_path}

## Intended Output

- Folder: {outputs.get('folder', 'services/visual/outputs')}
- Prefix: {outputs.get('prefix', 'laia_visual')}

## Rules

- No image has been generated by this packet.
- Generated assets must remain traceable to this packet.
- Source/reference media must be preserved.
- Any live generation requires explicit approval.
"""
    (target / "README.md").write_text(readme, encoding="utf-8")

    print(f"Created visual packet: {target}")
    print("")


def _validate_safetensors_header(path: Path) -> tuple[bool, str]:
    """
    Validate safetensors file header.
    Returns (is_valid, error_message).
    """
    try:
        data = path.read_bytes()
        if len(data) < 8:
            return False, "file too small (< 8 bytes)"

        # First 8 bytes are the header length in little-endian
        header_len = int.from_bytes(data[:8], "little")

        if header_len < 2:
            return False, "invalid header length"

        if 8 + header_len > len(data):
            return False, "truncated file (header overflow)"

        # Header should be valid JSON
        try:
            header_json = data[8:8+header_len].decode("utf-8")
            json.loads(header_json)
            return True, ""
        except (json.JSONDecodeError, UnicodeDecodeError):
            return False, "invalid header JSON"
    except Exception as e:
        return False, str(e)


def _inspect_workflow_json(workflow_path: Path) -> dict:
    """
    Parse workflow JSON and extract model/node references.
    Returns dict with categorized requirements.
    """
    result = {
        "checkpoints": set(),
        "loras": set(),
        "vae": set(),
        "text_encoders": set(),
        "controlnet": set(),
        "diffusion_models": set(),
        "custom_nodes": set(),
        "unknown_nodes": set(),
    }

    try:
        workflow = json.loads(workflow_path.read_text(encoding="utf-8"))
    except Exception as e:
        return {"error": str(e)}

    # Known ComfyUI node types that are part of core
    core_nodes = {
        "CheckpointLoaderSimple",
        "CheckpointLoader",
        "VAELoader",
        "LoraLoader",
        "CLIPLoader",
        "KSampler",
        "KSamplerAdvanced",
        "EmptyLatentImage",
        "LatentUpscale",
        "VAEDecode",
        "VAEEncode",
        "CLIPTextEncode",
        "ConditioningCombine",
        "PrimitiveNode",
    }

    for node_id, node_data in workflow.items():
        if not isinstance(node_data, dict):
            continue

        class_type = node_data.get("class_type", "")
        inputs = node_data.get("inputs", {})

        # Extract model references
        if class_type == "CheckpointLoaderSimple" or class_type == "CheckpointLoader":
            ckpt = inputs.get("ckpt_name", "")
            if ckpt:
                result["checkpoints"].add(ckpt)

        elif class_type == "VAELoader":
            vae = inputs.get("vae_name", "")
            if vae:
                result["vae"].add(vae)

        elif class_type == "LoraLoader":
            lora = inputs.get("lora_name", "")
            if lora:
                result["loras"].add(lora)

        elif class_type == "CLIPLoader":
            clip = inputs.get("clip_name", "")
            if clip:
                result["text_encoders"].add(clip)

        # Track custom nodes
        if class_type not in core_nodes:
            # Split on :: to get base name
            if "::" in class_type:
                result["custom_nodes"].add(class_type.split("::")[0])
            elif class_type and not class_type.startswith("_"):
                result["custom_nodes"].add(class_type)

    # Convert sets to sorted lists
    for key in result:
        if key != "error" and isinstance(result[key], set):
            result[key] = sorted(result[key])

    return result


def visual_inspect_workflow(args):
    workflow_path = Path(args.workflow_file).expanduser()

    print("\nLAIA VISUAL WORKFLOW INSPECTOR\n")

    if not workflow_path.exists():
        print(f"Workflow file not found: {workflow_path}\n")
        raise SystemExit(1)

    if not workflow_path.suffix.lower() == ".json":
        print(f"Not a JSON file: {workflow_path}\n")
        raise SystemExit(1)

    inspection = _inspect_workflow_json(workflow_path)

    if "error" in inspection:
        print(f"Failed to parse workflow: {inspection['error']}\n")
        raise SystemExit(1)

    print(f"File: {workflow_path}")
    print("")

    # Report required models
    has_models = False
    if inspection["checkpoints"]:
        print("Checkpoints:")
        for item in inspection["checkpoints"]:
            print(f"  - {item}")
        has_models = True

    if inspection["loras"]:
        print("LoRAs:")
        for item in inspection["loras"]:
            print(f"  - {item}")
        has_models = True

    if inspection["vae"]:
        print("VAE encoders:")
        for item in inspection["vae"]:
            print(f"  - {item}")
        has_models = True

    if inspection["text_encoders"]:
        print("Text encoders:")
        for item in inspection["text_encoders"]:
            print(f"  - {item}")
        has_models = True

    if not has_models:
        print("No model files detected.")

    print("")

    # Report custom nodes
    if inspection["custom_nodes"]:
        print("Required custom nodes:")
        for node in inspection["custom_nodes"]:
            print(f"  - {node}")
        print("")

    # Estimate complexity
    total_items = (
        len(inspection["checkpoints"]) +
        len(inspection["loras"]) +
        len(inspection["vae"]) +
        len(inspection["text_encoders"])
    )

    if total_items > 5:
        complexity = "HIGH"
    elif total_items > 2:
        complexity = "MEDIUM"
    else:
        complexity = "LOW"

    print(f"Estimated complexity: {complexity}")
    print("")


def visual_doctor(args):
    models_dir = visual_models_dir()

    print("\nLAIA VISUAL DOCTOR\n")

    if not models_dir.exists():
        print(f"Models directory not found: {models_dir}\n")
        return

    print(f"Scanning: {models_dir}\n")

    ok_files = []
    broken_files = []
    warnings = []

    # Scan all files recursively
    for file_path in models_dir.rglob("*"):
        if not file_path.is_file():
            continue

        if file_path.suffix.lower() == ".safetensors":
            is_valid, error_msg = _validate_safetensors_header(file_path)

            if is_valid:
                ok_files.append(file_path)
                # Check size
                size_gb = file_path.stat().st_size / (1024**3)
                if size_gb > 30:
                    warnings.append(f"{file_path.name}: {size_gb:.1f}GB (may exceed M1 Mini memory)")
            else:
                broken_files.append((file_path, error_msg))

    # Report OK files
    if ok_files:
        print(f"OK: {len(ok_files)} file(s)")
        for fpath in sorted(ok_files)[:10]:  # Show first 10
            print(f"  ✓ {fpath.name}")
        if len(ok_files) > 10:
            print(f"  ... and {len(ok_files) - 10} more")
        print("")

    # Report broken files
    if broken_files:
        print(f"BROKEN: {len(broken_files)} file(s)")
        for fpath, error_msg in sorted(broken_files):
            print(f"  ✗ {fpath.name}")
            print(f"    reason: {error_msg}")
        print("")

    # Report warnings
    if warnings:
        print("WARNINGS:")
        for warning in warnings:
            print(f"  ⚠ {warning}")
        print("")

    if not broken_files and not warnings:
        print("All model files validated successfully.\n")

    print(f"Summary: {len(ok_files)} OK, {len(broken_files)} broken")
    print("")


def visual_review(args):
    packet_dir = visual_packets_dir() / args.packet
    outputs_dir = packet_dir / "outputs"

    print("\nLAIA VISUAL REVIEW\n")
    print(f"Packet path: {packet_dir}")
    print(f"Outputs path: {outputs_dir}")

    if not outputs_dir.exists() or not outputs_dir.is_dir():
        print(f"Outputs directory missing: {outputs_dir}")
        print("Create the visual packet outputs first.")
        raise SystemExit(1)

    image_files = []
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        image_files.extend(sorted(outputs_dir.glob(ext)))

    if not image_files:
        print(f"No image files found in outputs: {outputs_dir}")
        raise SystemExit(1)

    review_items = []
    for image_path in image_files:
        command = [
            "ollama",
            "run",
            "llava:latest",
            "Describe this image in one sentence.",
            str(image_path),
        ]
        try:
            result = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
            caption = result.stdout.strip()
        except subprocess.CalledProcessError as exc:
            caption = f"ERROR: {exc.stderr.strip() if exc.stderr else exc}"

        print(f"{image_path.name}: {caption}")
        review_items.append({
            "file": image_path.name,
            "caption": caption,
            "reviewed_by": "ollama/llava:latest",
        })

    review_path = packet_dir / "review.json"
    review_path.write_text(json.dumps(review_items, indent=2) + "\n", encoding="utf-8")
    print(f"Saved review: {review_path}")


def visual_generate(args):
    # Support two modes:
    # Mode 1 (legacy): visual generate <packet_name> [--dry-run]
    # Mode 2 (stable): visual generate --profile <profile_name> "<prompt>" [--dry-run]

    if args.profile:
        # Mode 2: Stable generation from profile + prompt
        return _visual_generate_from_profile(args)
    else:
        # Mode 1: Legacy packet-based generation
        return _visual_generate_from_packet(args)


def _visual_generate_from_packet(args):
    """Legacy: Generate from an existing visual packet."""
    packet = find_packet("visual", args.packet_name)

    print("\nLAIA VISUAL GENERATE (from packet)\n")

    if not packet:
        print("Visual packet not found. Use: laia packets list\n")
        return

    prompt_path = packet / "prompt.txt"
    positive_path = packet / "positive.txt"
    negative_path = packet / "negative.txt"
    profile_path = packet / "profile.yaml"

    missing = [
        str(p) for p in [prompt_path, positive_path, negative_path, profile_path]
        if not p.exists()
    ]

    if missing:
        print("Packet is incomplete:")
        for item in missing:
            print(f"- Missing: {item}")
        print("")
        return

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8", errors="replace")) or {}
    prompt = prompt_path.read_text(encoding="utf-8", errors="replace").strip()
    positive = positive_path.read_text(encoding="utf-8", errors="replace").strip()
    negative = negative_path.read_text(encoding="utf-8", errors="replace").strip()
    outputs = profile.get("outputs", {})

    print(f"Packet: {packet}")
    print(f"Profile: {profile.get('name', '')}")
    print(f"Checkpoint: {profile.get('checkpoint', '')}")
    print("")
    print("Prompt:")
    print(prompt)
    print("")
    print("Positive:")
    print(positive)
    print("")
    print("Negative:")
    print(negative)
    print("")
    print("Output plan:")
    print(f"- Folder: {outputs.get('folder', 'services/visual/outputs')}")
    print(f"- Prefix: {outputs.get('prefix', 'laia_visual')}")

    if args.dry_run:
        print("\nNo generation submitted. Dry run only.\n")
        return

    print("\nLIVE GENERATION IS NOT ENABLED YET.")
    print("Next step: wire this to services/visual/comfy_client.py after approval.\n")


def _visual_generate_from_profile(args):
    """
    Stable generation pipeline: Load profile + prompt → create packet → queue workflow → wait → collect → review
    """
    import time
    import urllib.error

    profile_name = args.profile
    prompt_text = " ".join(args.prompt).strip() if args.prompt else ""

    print("\nLAIA VISUAL GENERATE (from profile)\n")

    # Load profile
    profile_path = visual_profiles_dir() / f"{profile_name}.yaml"

    if not profile_path.exists():
        print(f"Profile not found: {profile_path}\n")
        raise SystemExit(1)

    profile = yaml.safe_load(profile_path.read_text(encoding="utf-8")) or {}

    if not prompt_text:
        print("Error: Prompt is required.\n")
        raise SystemExit(1)

    print(f"Profile: {profile_name}")
    print(f"Prompt: {prompt_text}")
    print(f"Checkpoint: {profile.get('checkpoint', 'unknown')}")
    print("")

    if args.dry_run:
        print("DRY RUN - No workflow will be executed.\n")

    # Resolve workflow using multiple lookup locations
    workflow_name = profile.get("workflow", f"laia_{profile_name}.json")
    workflow_path = _resolve_workflow_path(workflow_name, profile_name)

    if not workflow_path.exists():
        print(f"Workflow not found: {workflow_path}\n")
        raise SystemExit(1)

    # Create visual packet
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    slug = slugify(prompt_text)[:60]
    packet_name = f"{stamp}-{slug}"
    packet_dir = visual_packets_dir() / packet_name

    try:
        packet_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        print(f"Packet already exists: {packet_dir}\n")
        raise SystemExit(1)

    print(f"Created packet: {packet_dir.name}")

    # Create packet structure
    (packet_dir / "outputs").mkdir(parents=True, exist_ok=True)

    # Save prompt and profile
    (packet_dir / "prompt.txt").write_text(prompt_text + "\n", encoding="utf-8")
    (packet_dir / "profile_used.yaml").write_text(profile_path.read_text(encoding="utf-8"), encoding="utf-8")

    # Save workflow
    workflow_content = workflow_path.read_text(encoding="utf-8")
    (packet_dir / "workflow_used.json").write_text(workflow_content, encoding="utf-8")

    # Create manifest
    manifest = {
        "packet_name": packet_name,
        "packet_path": str(packet_dir),
        "profile": profile_name,
        "prompt": prompt_text,
        "workflow": workflow_name,
        "checkpoint": profile.get("checkpoint", ""),
        "created_at": datetime.now().isoformat(),
        "status": "created",
        "prompt_id": None,
    }
    (packet_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"Saved manifest to {packet_name}/manifest.json")
    print("")

    if args.dry_run:
        print("Dry run complete. No workflow submitted.\n")
        return

    # Import comfy_client
    sys.path.insert(0, str(REPO_ROOT / "services" / "visual"))
    try:
        from comfy_client import ComfyClient
    except ImportError:
        print("Error: Could not import comfy_client.\n")
        raise SystemExit(1)

    # Check ComfyUI health
    client = ComfyClient()

    try:
        if not client.health():
            print("Error: ComfyUI is not reachable at http://127.0.0.1:8188\n")
            raise SystemExit(1)
    except Exception as e:
        print(f"Error: Could not connect to ComfyUI: {e}\n")
        raise SystemExit(1)

    print("ComfyUI health check: OK")

    # Load and inject prompt into workflow
    try:
        workflow = json.loads(workflow_content)
    except json.JSONDecodeError:
        print(f"Error: Invalid workflow JSON: {workflow_path}\n")
        raise SystemExit(1)

    # Try to inject prompt into common node positions
    # For API workflows, typically node 6 = positive, node 7 = negative
    positive_prompt = "\n".join(profile.get("positive", [])) + "\n" + prompt_text
    negative_prompt = "\n".join(profile.get("negative", []))

    if "6" in workflow and "inputs" in workflow["6"]:
        workflow["6"]["inputs"]["text"] = positive_prompt.strip()

    if "7" in workflow and "inputs" in workflow["7"]:
        workflow["7"]["inputs"]["text"] = negative_prompt.strip()

    print("Injected prompt into workflow")

    # Queue workflow
    try:
        print("Queuing workflow...")
        prompt_id = client.queue_workflow(workflow)
        print(f"Queued with prompt_id: {prompt_id}")
        print("")
    except Exception as e:
        print(f"Error: Failed to queue workflow: {e}\n")
        raise SystemExit(1)

    # Update manifest with prompt_id
    manifest["prompt_id"] = prompt_id
    manifest["status"] = "queued"
    (packet_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # Wait for completion
    print("Waiting for ComfyUI to process...")
    try:
        history = client.wait_for_prompt(prompt_id, timeout_seconds=600)
        print("Generation complete!")
        print("")
    except TimeoutError:
        print("Error: Generation timed out after 10 minutes.\n")
        manifest["status"] = "timeout"
        (packet_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(1)
    except Exception as e:
        print(f"Error: Failed waiting for completion: {e}\n")
        manifest["status"] = "error"
        (packet_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        raise SystemExit(1)

    # Save history
    (packet_dir / "comfy_history.json").write_text(json.dumps(history, indent=2) + "\n", encoding="utf-8")

    # TODO: Collect outputs from ComfyUI outputs directory
    # For now, assume they are copied to packet/outputs
    print(f"Packet ready at: {packet_dir}")
    print("")

    # Auto-run visual review
    print("Running automatic visual review...")
    outputs_dir = packet_dir / "outputs"
    if outputs_dir.exists():
        # Call visual_review logic
        image_files = []
        for ext in ("*.png", "*.jpg", "*.jpeg"):
            image_files.extend(sorted(outputs_dir.glob(ext)))

        if image_files:
            review_items = []
            for image_path in image_files:
                # Try to run ollama review
                try:
                    result = subprocess.run(
                        ["ollama", "run", "llava:latest", "Describe this image in one sentence.", str(image_path)],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    caption = result.stdout.strip()
                except Exception as e:
                    caption = f"ERROR: {str(e)}"

                review_items.append({
                    "file": image_path.name,
                    "caption": caption,
                    "reviewed_by": "ollama/llava:latest",
                })

            if review_items:
                (packet_dir / "review.json").write_text(json.dumps(review_items, indent=2) + "\n", encoding="utf-8")
                print(f"Saved review with {len(review_items)} image(s)")
        else:
            print("No images found in outputs directory")
    else:
        print(f"No outputs directory: {outputs_dir}")

def visual_generate_submit(args):
    import json
    import shutil
    import subprocess

    packet = find_packet("visual", args.packet_name)

    print("\nLAIA VISUAL GENERATE SUBMIT\n")

    if not packet:
        print("Visual packet not found.\\n")
        return

    workflow_arg = Path(args.workflow).expanduser()

    if workflow_arg.is_absolute():
        workflow = workflow_arg
    elif workflow_arg.exists():
        workflow = workflow_arg.resolve()
    else:
        # Try resolving via known workflow locations
        workflow = _resolve_workflow_path(args.workflow, Path(args.workflow).stem)

    if not workflow.exists():
        print(f"Missing workflow: {workflow}\n")
        return

    submitted = packet / "workflow.submitted.json"

    # Inject packet prompts into known ComfyUI API workflow nodes.
    # Node 6 = positive prompt, Node 7 = negative prompt for current API workflow.
    workflow_data = json.loads(workflow.read_text(encoding="utf-8"))

    positive_path = packet / "positive.txt"
    negative_path = packet / "negative.txt"

    if positive_path.exists() and "6" in workflow_data:
        workflow_data["6"]["inputs"]["text"] = positive_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).strip()

    if negative_path.exists() and "7" in workflow_data:
        workflow_data["7"]["inputs"]["text"] = negative_path.read_text(
            encoding="utf-8",
            errors="replace",
        ).strip()

    submitted.write_text(
        json.dumps(workflow_data, indent=2),
        encoding="utf-8",
    )

    print(f"Packet: {packet}")
    print(f"Workflow: {workflow}")
    print(f"Copied workflow -> {submitted}")
    print("")

    cmd = [
        "python",
        "services/visual/comfy_client.py",
        "queue",
        str(submitted),
    ]

    print("Queue command:")
    print(" ".join(cmd))
    print("")

    if args.dry_run:
        print("Dry run only. Workflow NOT submitted.\n")
        return

    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )

    print(result.stdout)

    if result.returncode != 0:
        print(result.stderr)
        print("Generation submission failed.\n")
        return

    generation_log = packet / "generation-result.txt"
    generation_log.write_text(
        result.stdout,
        encoding="utf-8",
    )

    prompt_id = ""
    for line in result.stdout.splitlines():
        if line.startswith("Queued workflow:"):
            prompt_id = line.split(":", 1)[1].strip()

    prompt_id_path = packet / "prompt-id.json"
    prompt_id_path.write_text(
        json.dumps({
            "packet": args.packet_name,
            "prompt_id": prompt_id,
            "workflow": args.workflow,
            "workflow_submitted": str(submitted),
            "created_at": datetime.now().isoformat(),
        }, indent=2),
        encoding="utf-8",
    )

    provenance = provenance_write(
        service="visual",
        action="generation_submit",
        packet=args.packet_name,
        details={
            "workflow": args.workflow,
            "workflow_submitted": str(submitted),
            "generation_log": str(generation_log),
            "prompt_id": prompt_id,
            "prompt_id_file": str(prompt_id_path),
            "status": "queued",
            "stdout": result.stdout.strip(),
        },
    )

    print(f"Saved generation log: {generation_log}")
    print(f"Saved provenance log: {provenance}")
    print("")


def packets_index(args=None):
    import json

    print("\nLAIA PACKET INDEX\n")

    index_dir = LAIA_ROOT / "index" / "packets"
    index_dir.mkdir(parents=True, exist_ok=True)

    rows = []

    categories = packet_categories()

    for category, d in categories.items():
        if not d.exists():
            continue

        for packet in sorted(d.iterdir()):
            if not packet.is_dir():
                continue

            readme = packet / "README.md"
            prompt = packet / "prompt.txt"
            query = packet / "query.txt"

            title = packet.name
            summary = ""

            if readme.exists():
                text = readme.read_text(encoding="utf-8", errors="replace")
                summary = "\n".join(text.splitlines()[:20])

            row = {
                "category": category,
                "name": packet.name,
                "path": str(packet),
                "created_or_modified": datetime.fromtimestamp(packet.stat().st_mtime).isoformat(),
                "has_readme": readme.exists(),
                "has_prompt": prompt.exists(),
                "has_query": query.exists(),
                "summary": summary,
            }

            rows.append(row)

    json_path = index_dir / "packet_index.json"
    md_path = index_dir / "packet_index.md"

    json_path.write_text(json.dumps(rows, indent=2), encoding="utf-8")

    lines = [
        "# LAIA Packet Index",
        "",
        f"- Packets indexed: {len(rows)}",
        f"- Generated: {datetime.now().isoformat()}",
        "",
        "| Category | Packet | Path |",
        "|---|---|---|",
    ]

    for row in rows:
        lines.append(
            f"| `{row['category']}` | `{row['name']}` | `{row['path']}` |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Indexed packets: {len(rows)}")
    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print("")


def search_packets(args):
    import json

    query = " ".join(args.query).lower()
    index_path = LAIA_ROOT / "index" / "packets" / "packet_index.json"

    print(f"\nLAIA SEARCH PACKETS — {query}\n")

    if not index_path.exists():
        print("Missing packet index. Run: laia packets index\n")
        return

    rows = json.loads(index_path.read_text(encoding="utf-8", errors="replace"))
    matches = []

    for row in rows:
        haystack = " ".join([
            str(row.get("category", "")),
            str(row.get("name", "")),
            str(row.get("path", "")),
            str(row.get("summary", "")),
        ]).lower()

        if query in haystack:
            matches.append(row)

    if not matches:
        print("No packet matches found.\n")
        return

    for row in matches[:20]:
        print(f"- [{row.get('category')}] {row.get('name')}")
        print(f"  {row.get('path')}")
    print("")


def search_all(args):
    query = " ".join(args.query)

    print(f"\nLAIA SEARCH — {query}\n")

    print("=== Packet matches ===")
    search_packets(args)

    print("=== NAS matches ===")
    class NasArgs:
        pass

    nas_args = NasArgs()
    nas_args.query = args.query
    nas_find(nas_args)

    print("=== Provenance matches ===")
    class ProvenanceArgs:
        pass

    prov_args = ProvenanceArgs()
    prov_args.query = args.query
    provenance_search(prov_args)

    print("=== Packet state matches ===")
    class StateArgs:
        pass

    state_args = StateArgs()
    state_args.query = args.query
    search_packet_states(state_args)

def provenance_log_dir():
    d = LAIA_ROOT / "logs" / "provenance"
    d.mkdir(parents=True, exist_ok=True)
    return d


def provenance_write(
    service: str,
    action: str,
    packet: str = "",
    details: dict | None = None,
):
    import json

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    row = {
        "timestamp": datetime.now().isoformat(),
        "service": service,
        "action": action,
        "packet": packet,
        "details": details or {},
    }

    out = provenance_log_dir() / f"{stamp}-{service}-{action}.json"

    out.write_text(
        json.dumps(row, indent=2),
        encoding="utf-8",
    )

    return out


def provenance_log(args):
    details = {}

    for item in args.detail:
        if "=" in item:
            k, v = item.split("=", 1)
            details[k] = v

    out = provenance_write(
        service=args.service,
        action=args.action,
        packet=args.packet,
        details=details,
    )

    print("\nLAIA PROVENANCE LOG\n")
    print(f"Log written: {out}\n")


def provenance_entries():
    import json

    d = provenance_log_dir()
    entries = []

    for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            row = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            row["_file"] = str(f)
            entries.append(row)
        except Exception:
            continue

    return entries


def provenance_list(args):
    print("\nLAIA PROVENANCE LIST\n")

    entries = provenance_entries()

    if not entries:
        print("No provenance logs found.\n")
        return

    limit = getattr(args, "limit", 20)

    for row in entries[:limit]:
        print(f"- {row.get('timestamp')} | {row.get('service')}:{row.get('action')}")
        if row.get("packet"):
            print(f"  packet: {row.get('packet')}")
        print(f"  file: {row.get('_file')}")
    print("")


def provenance_search(args):
    query = " ".join(args.query).lower()

    print(f"\nLAIA PROVENANCE SEARCH — {query}\n")

    matches = []

    for row in provenance_entries():
        haystack = " ".join([
            str(row.get("timestamp", "")),
            str(row.get("service", "")),
            str(row.get("action", "")),
            str(row.get("packet", "")),
            str(row.get("details", "")),
            str(row.get("_file", "")),
        ]).lower()

        if query in haystack:
            matches.append(row)

    if not matches:
        print("No provenance matches found.\n")
        return

    for row in matches[:20]:
        print(f"- {row.get('timestamp')} | {row.get('service')}:{row.get('action')}")
        if row.get("packet"):
            print(f"  packet: {row.get('packet')}")
        print(f"  file: {row.get('_file')}")
    print("")


def provenance_packet(args):
    packet = args.packet_name.lower()

    print(f"\nLAIA PROVENANCE PACKET — {args.packet_name}\n")

    matches = [
        row for row in provenance_entries()
        if packet in str(row.get("packet", "")).lower()
    ]

    if not matches:
        print("No provenance found for packet.\n")
        return

    for row in matches:
        print(f"- {row.get('timestamp')} | {row.get('service')}:{row.get('action')}")
        print(f"  file: {row.get('_file')}")
        if row.get("details"):
            print(f"  details: {row.get('details')}")
    print("")


def node_registry_path():
    return REPO_ROOT / "services" / "nodes" / "node-registry.yaml"


def load_node_registry():
    path = node_registry_path()
    if not path.exists():
        return {"nodes": {}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"nodes": {}}


def nodes_list(_args=None):
    data = load_node_registry()
    nodes = data.get("nodes", {})

    print("\nLAIA NODES\n")

    if not nodes:
        print("No nodes registered.\n")
        return

    for node_id, node in nodes.items():
        print(f"- {node_id}: {node.get('name', '')}")
        print(f"  role: {node.get('role', '')}")
    print("")


def nodes_show(args):
    data = load_node_registry()
    node = data.get("nodes", {}).get(args.node_id)

    print(f"\nLAIA NODE — {args.node_id}\n")

    if not node:
        print("Node not found.\n")
        return

    print(yaml.safe_dump(node, sort_keys=False, allow_unicode=True))


def nodes_capabilities(_args=None):
    data = load_node_registry()
    nodes = data.get("nodes", {})

    print("\nLAIA NODE CAPABILITIES\n")

    for node_id, node in nodes.items():
        print(f"## {node_id}")
        for service in node.get("services", []):
            print(f"- {service}")
        print("")


def librarian_status(args=None):
    print("\nLAIA LIBRARIAN STATUS\n")

    packet_index = LAIA_ROOT / "index" / "packets" / "packet_index.json"
    provenance_dir = provenance_log_dir()
    node_registry = node_registry_path()

    packet_count = 0
    provenance_count = 0
    node_count = 0

    if packet_index.exists():
        try:
            import json
            rows = json.loads(packet_index.read_text())
            packet_count = len(rows)
        except Exception:
            pass

    if provenance_dir.exists():
        provenance_count = len(list(provenance_dir.glob("*.json")))

    if node_registry.exists():
        try:
            data = yaml.safe_load(node_registry.read_text()) or {}
            node_count = len(data.get("nodes", {}))
        except Exception:
            pass

    print(f"Packets indexed:    {packet_count}")
    print(f"Provenance logs:   {provenance_count}")
    print(f"Registered nodes:  {node_count}")
    print("")

    root = get_archive_root(args)
    manifest = load_latest_librarian_manifest()
    latest_json, _ = get_latest_manifest_paths()

    print("ARCHIVE INDEX STATUS")
    print(f"Archive root: {root}")
    print(f"Exists: {'yes' if root.exists() else 'no'}")
    if latest_json.exists():
        file_count = manifest.get("file_count") if isinstance(manifest, dict) else None
        print(f"Latest manifest: {latest_json}")
        print(f"Latest manifest file count: {file_count if file_count is not None else 'unknown'}")
    else:
        print("Latest manifest: none")
        print("Latest manifest file count: none")
    print("")


def librarian_summarize(_args=None):
    print("\nLAIA LIBRARIAN SUMMARY\n")

    print("=== Recent packets ===")
    packets_list()

    print("=== Recent provenance ===")
    class ProvArgs:
        limit = 10

    provenance_list(ProvArgs())

    print("=== Registered nodes ===")
    nodes_list()


def librarian_index(_args=None):
    import json

    print("\nLAIA LIBRARIAN INDEX\n")

    out_dir = LAIA_ROOT / "index" / "librarian"
    out_dir.mkdir(parents=True, exist_ok=True)

    packets = []
    categories = packet_categories()

    provenance = provenance_entries()

    for category, d in categories.items():
        if not d.exists():
            continue

        for packet in sorted(d.iterdir()):
            if not packet.is_dir():
                continue

            readme = packet / "README.md"
            state_path = packet / "packet-state.json"
            packet_name = packet.name

            packet_state = "unknown"
            packet_state_updated = ""

            if state_path.exists():
                try:
                    state_data = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
                    packet_state = state_data.get("state", "unknown")
                    packet_state_updated = state_data.get("updated_at", "")
                except Exception:
                    packet_state = "unreadable"

            related_provenance = [
                row for row in provenance
                if packet_name in str(row.get("packet", ""))
            ]

            files = sorted(
                f.name for f in packet.iterdir()
                if f.is_file()
            )

            packet_row = {
                "category": category,
                "name": packet_name,
                "path": str(packet),
                "files": files,
                "has_readme": readme.exists(),
                "state": packet_state,
                "state_updated": packet_state_updated,
                "provenance_count": len(related_provenance),
                "provenance": related_provenance,
                "modified": datetime.fromtimestamp(packet.stat().st_mtime).isoformat(),
            }

            packets.append(packet_row)

    index = {
        "generated": datetime.now().isoformat(),
        "packet_count": len(packets),
        "provenance_count": len(provenance),
        "packets": packets,
    }

    json_path = out_dir / "librarian_index.json"
    md_path = out_dir / "librarian_index.md"

    json_path.write_text(
        json.dumps(index, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# LAIA Librarian Index",
        "",
        f"- Generated: `{index['generated']}`",
        f"- Packets indexed: `{index['packet_count']}`",
        f"- Provenance logs indexed: `{index['provenance_count']}`",
        "",
        "## Packet Relationship Summary",
        "",
        "| Category | Packet | State | Files | Provenance Logs |",
        "|---|---|---|---:|---:|",
    ]

    for row in packets:
        lines.append(
            f"| `{row['category']}` | `{row['name']}` | `{row.get('state', 'unknown')}` | "
            f"{len(row['files'])} | {row['provenance_count']} |"
        )

    md_path.write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )

    print(f"Packets indexed: {len(packets)}")
    print(f"Provenance logs indexed: {len(provenance)}")
    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print("")


def jobs_root():
    return LAIA_ROOT / "jobs"


def jobs_state_dir(state: str):
    d = jobs_root() / state
    d.mkdir(parents=True, exist_ok=True)
    return d


def jobs_create(args):
    title = " ".join(args.title).strip()
    slug = slugify(title)[:60]
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    job_id = f"{stamp}-{slug}"

    packet = getattr(args, "packet", "") or ""
    service = getattr(args, "service", "planner")

    target = jobs_state_dir("queued") / f"{job_id}.md"

    content = f"""---
id: {job_id}
type: laia_job
state: queued
service: {service}
packet: {packet}
created_at: {datetime.now().isoformat()}
requires_approval: true
---

# {title}

## Goal
{title}

## Packet Reference
{packet or "None"}

## Status
Queued. Planner proposes; Operator approves.

## Notes
"""

    target.write_text(content, encoding="utf-8")

    provenance_write(
        service="planner",
        action="job_created",
        packet=packet,
        details={
            "job_id": job_id,
            "job_path": str(target),
            "service": service,
            "title": title,
        },
    )

    print("\nLAIA JOB CREATED\n")
    print(f"Job ID: {job_id}")
    print(f"Path: {target}\n")


def jobs_list(_args=None):
    print("\nLAIA JOBS\n")

    states = ["queued", "approved", "running", "completed", "failed"]

    for state in states:
        d = jobs_state_dir(state)
        jobs = sorted(d.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

        print(f"## {state}")
        if not jobs:
            print("- none\n")
            continue

        for job in jobs[:10]:
            print(f"- {job.stem}")
        print("")


def jobs_find(job_id: str):
    for state in ["queued", "approved", "running", "completed", "failed"]:
        p = jobs_state_dir(state) / f"{job_id}.md"
        if p.exists():
            return p
    return None


def jobs_show(args):
    job = jobs_find(args.job_id)

    print(f"\nLAIA JOB — {args.job_id}\n")

    if not job:
        print("Job not found. Use: laia jobs list\n")
        return

    print(job.read_text(encoding="utf-8", errors="replace"))


def jobs_move_state(args, target_state: str):
    import shutil

    job = jobs_find(args.job_id)

    print(f"\nLAIA JOB {target_state.upper()}\n")

    if not job:
        print("Job not found. Use: laia jobs list\n")
        return

    new_path = jobs_state_dir(target_state) / job.name
    shutil.move(str(job), str(new_path))

    text = new_path.read_text(encoding="utf-8", errors="replace")
    text = text.replace("state: queued", f"state: {target_state}")
    text = text.replace("state: approved", f"state: {target_state}")
    text = text.replace("state: running", f"state: {target_state}")
    text = text.replace("state: completed", f"state: {target_state}")
    text = text.replace("state: failed", f"state: {target_state}")

    text += f"\n\n## State Change\nMoved to `{target_state}` at {datetime.now().isoformat()}.\n"
    new_path.write_text(text, encoding="utf-8")

    packet = ""
    for line in text.splitlines():
        if line.startswith("packet:"):
            packet = line.split(":", 1)[1].strip()
            break

    provenance_write(
        service="planner",
        action=f"job_{target_state}",
        packet=packet,
        details={
            "job_id": args.job_id,
            "job_path": str(new_path),
            "state": target_state,
        },
    )

    print(f"Job ID: {args.job_id}")
    print(f"State: {target_state}")
    print(f"Path: {new_path}\n")


def jobs_approve(args):
    jobs_move_state(args, "approved")


def jobs_complete(args):
    jobs_move_state(args, "completed")


def publish_dir():
    d = LAIA_ROOT / "LAIA" / "00_DASHBOARD"
    d.mkdir(parents=True, exist_ok=True)
    return d


def publish_status(_args=None):
    out = publish_dir() / "LAIA_STATUS.md"

    lines = [
        "# LAIA Status",
        "",
        f"Generated: `{datetime.now().isoformat()}`",
        "",
        "## System Summary",
        "",
    ]

    packet_index = LAIA_ROOT / "index" / "packets" / "packet_index.json"
    librarian_index = LAIA_ROOT / "index" / "librarian" / "librarian_index.md"

    lines.append(f"- Packet index: `{'PASS' if packet_index.exists() else 'MISSING'}`")
    lines.append(f"- Librarian index: `{'PASS' if librarian_index.exists() else 'MISSING'}`")
    lines.append(f"- Provenance logs: `{len(list(provenance_log_dir().glob('*.json')))}`")
    lines.append(f"- Jobs queued: `{len(list(jobs_state_dir('queued').glob('*.md')))}`")
    lines.append(f"- Jobs approved: `{len(list(jobs_state_dir('approved').glob('*.md')))}`")
    lines.append(f"- Jobs completed: `{len(list(jobs_state_dir('completed').glob('*.md')))}`")
    lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Published: {out}")


def publish_packets(_args=None):
    out = publish_dir() / "PACKET_INDEX.md"
    src = LAIA_ROOT / "index" / "packets" / "packet_index.md"

    if src.exists():
        out.write_text(src.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    else:
        out.write_text("# Packet Index\n\nMissing packet index. Run `laia packets index`.\n", encoding="utf-8")

    print(f"Published: {out}")


def publish_provenance(_args=None):
    out = publish_dir() / "PROVENANCE_RECENT.md"

    lines = [
        "# Recent Provenance",
        "",
        f"Generated: `{datetime.now().isoformat()}`",
        "",
    ]

    for row in provenance_entries()[:25]:
        lines.append(f"- `{row.get('timestamp')}` — **{row.get('service')}:{row.get('action')}**")
        if row.get("packet"):
            lines.append(f"  - Packet: `{row.get('packet')}`")
        lines.append(f"  - File: `{row.get('_file')}`")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Published: {out}")


def publish_jobs(_args=None):
    out = publish_dir() / "JOBS.md"

    lines = [
        "# LAIA Jobs",
        "",
        f"Generated: `{datetime.now().isoformat()}`",
        "",
    ]

    for state in ["queued", "approved", "running", "completed", "failed"]:
        lines.append(f"## {state}")
        jobs = sorted(
            jobs_state_dir(state).glob("*.md"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not jobs:
            lines.append("- none")
        else:
            for job in jobs[:20]:
                lines.append(f"- `{job.stem}`")
        lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"Published: {out}")


def publish_all(args=None):
    publish_status(args)
    publish_packets(args)
    publish_provenance(args)
    publish_jobs(args)
    publish_visual(args)
    publish_states(args)
    publish_ocr(args)


def librarian_orphaned(_args=None):
    print("\nLAIA LIBRARIAN ORPHANED\n")

    categories = packet_categories()
    provenance = provenance_entries()

    packet_names = set()
    packet_rows = []

    for category, d in categories.items():
        if not d.exists():
            continue
        for packet in d.iterdir():
            if packet.is_dir():
                packet_names.add(packet.name)
                packet_rows.append((category, packet.name, packet))

    packets_without_provenance = []
    for category, name, packet in packet_rows:
        related = [row for row in provenance if name in str(row.get("packet", ""))]
        if not related:
            packets_without_provenance.append((category, name, packet))

    provenance_without_packet = []
    for row in provenance:
        packet = str(row.get("packet", ""))
        if packet and packet not in packet_names:
            provenance_without_packet.append(row)

    print("## Packets without provenance")
    if not packets_without_provenance:
        print("- none")
    else:
        for category, name, packet in packets_without_provenance:
            print(f"- [{category}] {name}")
            print(f"  {packet}")

    print("\n## Provenance referencing missing packets")
    if not provenance_without_packet:
        print("- none")
    else:
        for row in provenance_without_packet:
            print(f"- {row.get('timestamp')} | {row.get('service')}:{row.get('action')}")
            print(f"  packet: {row.get('packet')}")
            print(f"  file: {row.get('_file')}")
    print("")


def jobs_reopen(args):
    jobs_move_state(args, "approved")


def publish_refresh(args):
    import time

    interval = args.interval
    count = args.count

    print("\nLAIA PUBLISH REFRESH\n")
    print(f"Interval: {interval}s")
    print(f"Count: {count if count else 'until stopped'}\n")

    i = 0
    while True:
        packets_index()
        librarian_index()
        publish_all()
        i += 1
        print(f"Refresh complete: {i}")

        if count and i >= count:
            break

        time.sleep(interval)


def doctor_phase2(_args=None):
    import urllib.request

    print("\nLAIA PHASE 2 DOCTOR\n")

    checks = []

    def check(name, ok, detail=""):
        checks.append((name, ok, detail))
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {name}" + (f" — {detail}" if detail else ""))

    check("LAIA root", LAIA_ROOT.exists(), str(LAIA_ROOT))
    check("Packet index", (LAIA_ROOT / "index" / "packets" / "packet_index.json").exists())
    check("Librarian index", (LAIA_ROOT / "index" / "librarian" / "librarian_index.json").exists())
    check("Dashboard status", (publish_dir() / "LAIA_STATUS.md").exists())
    check("Node registry", node_registry_path().exists())
    check("NAS manifest", (LAIA_ROOT / "archive" / "nas_manifests" / "nas_manifest_latest.json").exists())
    check("Jobs root", jobs_root().exists())
    check("Provenance logs", len(list(provenance_log_dir().glob("*.json"))) > 0)

    try:
        with urllib.request.urlopen("http://127.0.0.1:8188", timeout=3) as r:
            check("ComfyUI", r.status == 200, "http://127.0.0.1:8188")
    except Exception as e:
        check("ComfyUI", False, str(e))

    failed = [c for c in checks if not c[1]]
    print("")
    print(f"Checks: {len(checks)}")
    print(f"Failed: {len(failed)}")
    print("")


def comfy_output_dir():
    return visual_comfy_dir() / "output"


def visual_collect(args):
    import json
    import shutil

    packet = find_packet("visual", args.packet_name)

    print("\nLAIA VISUAL COLLECT\n")

    if not packet:
        print("Visual packet not found. Use: laia packets list\n")
        return

    source_dir = comfy_output_dir()
    collected_dir = packet / "outputs"
    collected_dir.mkdir(parents=True, exist_ok=True)

    if not source_dir.exists():
        print(f"Missing ComfyUI output directory: {source_dir}\n")
        return

    prompt_id_path = packet / "prompt-id.json"
    files = []

    if prompt_id_path.exists():
        try:
            import urllib.request

            prompt_data = json.loads(prompt_id_path.read_text(encoding="utf-8", errors="replace"))
            prompt_id = prompt_data.get("prompt_id", "")

            if prompt_id:
                with urllib.request.urlopen(f"http://127.0.0.1:8188/history/{prompt_id}", timeout=10) as r:
                    history = json.loads(r.read().decode("utf-8"))

                outputs = history.get(prompt_id, {}).get("outputs", {})

                for node_output in outputs.values():
                    for image in node_output.get("images", []):
                        filename = image.get("filename")
                        subfolder = image.get("subfolder", "")
                        if filename:
                            candidate = source_dir / subfolder / filename if subfolder else source_dir / filename
                            if candidate.exists():
                                files.append(candidate)
        except Exception as e:
            print(f"Prompt history lookup failed; falling back to newest files: {e}")

    if not files:
        files = sorted(
            [f for f in source_dir.iterdir() if f.is_file()],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if args.limit:
            files = files[:args.limit]

    copied = []

    for src in files:
        dst = collected_dir / src.name
        if dst.exists() and not args.force:
            continue
        shutil.copy2(src, dst)
        copied.append({
            "source": str(src),
            "collected": str(dst),
            "bytes": dst.stat().st_size,
            "modified": datetime.fromtimestamp(dst.stat().st_mtime).isoformat(),
        })

    present_files = sorted(
        [f for f in collected_dir.iterdir() if f.is_file()],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    present = [
        {
            "path": str(f),
            "filename": f.name,
            "bytes": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }
        for f in present_files
    ]

    manifest_path = packet / "visual-output-manifest.json"
    newest_collected_output = ""
    if copied:
        newest_collected_output = copied[0].get("collected", "")
    elif present:
        newest_collected_output = present[0].get("path", "")

    prompt_id = ""
    prompt_id_path = packet / "prompt-id.json"
    if prompt_id_path.exists():
        try:
            prompt_data = json.loads(prompt_id_path.read_text(encoding="utf-8", errors="replace"))
            prompt_id = prompt_data.get("prompt_id", "")
        except Exception:
            prompt_id = ""

    manifest = {
        "packet": args.packet_name,
        "collected_at": datetime.now().isoformat(),
        "prompt_id": prompt_id,
        "source_dir": str(source_dir),
        "outputs_dir": str(collected_dir),
        "newest_collected_output": newest_collected_output,
        "files_copied": copied,
        "files_present": present,
        "copied_count": len(copied),
        "present_count": len(present),
    }

    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    provenance = provenance_write(
        service="visual",
        action="outputs_collected",
        packet=args.packet_name,
        details={
            "source_dir": str(source_dir),
            "outputs_dir": str(collected_dir),
            "manifest": str(manifest_path),
            "copied_count": len(copied),
            "present_count": len(present),
        },
    )

    print(f"Packet: {packet}")
    print(f"Source: {source_dir}")
    print(f"Collected dir: {collected_dir}")
    print(f"Files copied: {len(copied)}")
    print(f"Files present: {len(present)}")
    print(f"Manifest: {manifest_path}")
    print(f"Provenance: {provenance}\n")


def visual_outputs(args):
    import json

    packet = find_packet("visual", args.packet_name)

    print("\nLAIA VISUAL OUTPUTS\n")

    if not packet:
        print("Visual packet not found. Use: laia packets list\n")
        return

    manifest = packet / "visual-output-manifest.json"
    outputs_dir = packet / "outputs"

    print(f"Packet: {packet}")

    if not outputs_dir.exists():
        print("No outputs directory found.\n")
        return

    files = sorted(
        [f for f in outputs_dir.iterdir() if f.is_file()],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    print(f"Outputs dir: {outputs_dir}")
    print(f"Files: {len(files)}\n")

    for f in files:
        print(f"- {f.name} | {f.stat().st_size} bytes")

    if manifest.exists():
        print("\nManifest:")
        data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
        print(f"- collected_at: {data.get('collected_at')}")
        print(f"- source_dir: {data.get('source_dir')}")
        print(f"- copied_count: {data.get('copied_count', len(data.get('files_copied', [])))}")
        print(f"- present_count: {data.get('present_count', len(data.get('files_present', [])))}")

    print("")


def visual_inspect(args):
    import json
    import hashlib
    from PIL import Image

    packet = find_packet("visual", args.packet_name)

    print("\nLAIA VISUAL INSPECT\n")

    if not packet:
        print("Visual packet not found. Use: laia packets list\n")
        return

    outputs_dir = packet / "outputs"

    if not outputs_dir.exists():
        print("No outputs directory found. Run: laia visual collect <packet>\n")
        return

    files = sorted(
        [f for f in outputs_dir.iterdir() if f.is_file()],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )

    if not files:
        print("No output files found.\n")
        return

    inspected = []

    for f in files:
        row = {
            "filename": f.name,
            "path": str(f),
            "bytes": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        }

        h = hashlib.sha256()
        with f.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        row["sha256"] = h.hexdigest()

        try:
            with Image.open(f) as img:
                row["format"] = img.format
                row["width"] = img.width
                row["height"] = img.height
                row["mode"] = img.mode
                row["info"] = {k: str(v)[:500] for k, v in img.info.items()}
        except Exception as e:
            row["image_error"] = str(e)

        inspected.append(row)

    out = packet / "visual-inspection.json"
    out.write_text(json.dumps({
        "packet": args.packet_name,
        "inspected_at": datetime.now().isoformat(),
        "files": inspected,
    }, indent=2), encoding="utf-8")

    provenance = provenance_write(
        service="visual",
        action="outputs_inspected",
        packet=args.packet_name,
        details={
            "inspection": str(out),
            "count": len(inspected),
        },
    )

    print(f"Packet: {packet}")
    print(f"Inspection: {out}")
    print(f"Files inspected: {len(inspected)}")
    print(f"Provenance: {provenance}\n")

    for row in inspected:
        print(f"- {row.get('filename')}")
        print(f"  size: {row.get('bytes')} bytes")
        if "width" in row:
            print(f"  dimensions: {row.get('width')}x{row.get('height')}")
            print(f"  format: {row.get('format')}")
        print(f"  sha256: {row.get('sha256')}")
    print("")


def visual_report(args):
    import json

    packet = find_packet("visual", args.packet_name)

    print("\nLAIA VISUAL REPORT\n")

    if not packet:
        print("Visual packet not found. Use: laia packets list\n")
        return

    prompt_path = packet / "prompt.txt"
    output_manifest = packet / "visual-output-manifest.json"
    inspection_path = packet / "visual-inspection.json"
    generation_log = packet / "generation-result.txt"

    provenance = [
        row for row in provenance_entries()
        if args.packet_name in str(row.get("packet", ""))
    ]

    lines = [
        "# LAIA Visual Report",
        "",
        f"- Packet: `{args.packet_name}`",
        f"- Generated: `{datetime.now().isoformat()}`",
        "",
        "## Prompt",
        "",
    ]

    if prompt_path.exists():
        lines.append(prompt_path.read_text(encoding="utf-8", errors="replace").strip())
    else:
        lines.append("_No prompt.txt found._")

    lines += ["", "## Generation", ""]

    if generation_log.exists():
        lines.append("```text")
        lines.append(generation_log.read_text(encoding="utf-8", errors="replace").strip()[:2000])
        lines.append("```")
    else:
        lines.append("_No generation-result.txt found._")

    lines += ["", "## Outputs", ""]

    if output_manifest.exists():
        data = json.loads(output_manifest.read_text(encoding="utf-8", errors="replace"))
        lines.append(f"- Source dir: `{data.get('source_dir')}`")
        lines.append(f"- Outputs dir: `{data.get('outputs_dir')}`")
        lines.append(f"- Copied count: `{data.get('copied_count', len(data.get('files_copied', [])))}`")
        lines.append(f"- Present count: `{data.get('present_count', len(data.get('files_present', [])))}`")
        lines.append("")
        for item in data.get("files_present", []):
            lines.append(f"- `{item.get('filename')}` — {item.get('bytes')} bytes")
    else:
        lines.append("_No visual-output-manifest.json found._")

    lines += ["", "## Inspection", ""]

    if inspection_path.exists():
        data = json.loads(inspection_path.read_text(encoding="utf-8", errors="replace"))
        for item in data.get("files", []):
            lines.append(f"### {item.get('filename')}")
            lines.append("")
            lines.append(f"- Format: `{item.get('format')}`")
            lines.append(f"- Dimensions: `{item.get('width')}x{item.get('height')}`")
            lines.append(f"- Mode: `{item.get('mode')}`")
            lines.append(f"- Bytes: `{item.get('bytes')}`")
            lines.append(f"- SHA256: `{item.get('sha256')}`")
            lines.append("")
    else:
        lines.append("_No visual-inspection.json found._")

    lines += ["", "## Provenance Events", ""]

    if provenance:
        for row in provenance:
            lines.append(f"- `{row.get('timestamp')}` — **{row.get('service')}:{row.get('action')}**")
            details = row.get("details", {})
            if details:
                for k, v in details.items():
                    lines.append(f"  - `{k}`: `{v}`")
    else:
        lines.append("_No provenance events found._")

    out = packet / "visual-report.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")

    prov = provenance_write(
        service="visual",
        action="report_created",
        packet=args.packet_name,
        details={
            "report": str(out),
        },
    )

    print(f"Packet: {packet}")
    print(f"Report: {out}")
    print(f"Provenance: {prov}\n")


def publish_visual(_args=None):
    out = publish_dir() / "VISUAL_REPORTS.md"

    lines = [
        "# LAIA Visual Reports",
        "",
        f"Generated: `{datetime.now().isoformat()}`",
        "",
    ]

    visual_dir = packets_dir() / "visual"

    if not visual_dir.exists():
        lines.append("_No visual packets found._")
    else:
        packets = sorted(
            [p for p in visual_dir.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not packets:
            lines.append("_No visual packets found._")
        else:
            for packet in packets:
                report = packet / "visual-report.md"
                inspection = packet / "visual-inspection.json"
                outputs = packet / "outputs"

                lines.append(f"## {packet.name}")
                lines.append("")
                lines.append(f"- Packet: `{packet}`")
                lines.append(f"- Report: `{'PASS' if report.exists() else 'MISSING'}`")
                lines.append(f"- Inspection: `{'PASS' if inspection.exists() else 'MISSING'}`")

                if outputs.exists():
                    output_files = [f for f in outputs.iterdir() if f.is_file()]
                    lines.append(f"- Outputs: `{len(output_files)}`")
                    for f in output_files[:10]:
                        lines.append(f"  - `{f.name}`")
                else:
                    lines.append("- Outputs: `0`")

                if report.exists():
                    lines.append("")
                    lines.append("### Report Preview")
                    lines.append("")
                    preview = report.read_text(encoding="utf-8", errors="replace").splitlines()
                    lines.extend(preview[:40])

                lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Published: {out}")


def visual_lifecycle(args):
    print("\nLAIA VISUAL LIFECYCLE\n")

    class Obj:
        pass

    o = Obj()
    o.packet_name = args.packet_name
    o.limit = getattr(args, "limit", 1)
    o.force = getattr(args, "force", False)

    print("STEP 1 — Collect outputs")
    visual_collect(o)

    print("STEP 2 — Inspect outputs")
    visual_inspect(o)

    print("STEP 3 — Caption output")
    o.model = getattr(args, "model", "llava:latest")
    o.prompt = getattr(args, "caption_prompt", "")
    visual_caption(o)

    print("STEP 4 — Create report")
    visual_report(o)

    print("STEP 5 — Rebuild librarian index")
    librarian_index(None)

    print("STEP 6 — Publish visual dashboard")
    publish_visual(None)

    print("STEP 7 — Publish operational dashboard")
    publish_all(None)

    packet = find_packet("visual", args.packet_name)
    state_file = None
    if packet:
        state_file = packet_state_write(
            packet,
            "lifecycle_completed",
            service="visual",
            details={"workflow": "visual_lifecycle"},
        )

    prov = provenance_write(
        service="visual",
        action="lifecycle_completed",
        packet=args.packet_name,
        details={
            "status": "success",
            "state_file": str(state_file) if state_file else "",
        },
    )

    print(f"Lifecycle provenance: {prov}")
    print("\nLifecycle complete.\n")


PACKET_STATES = [
    "created",
    "submitted",
    "generated",
    "collected",
    "inspected",
    "extracted",
    "captioned",
    "reported",
    "published",
    "needs_review",
    "duplicate",
    "archived",
    "lifecycle_completed",
]


def packet_state_write(packet_path: Path, state: str, service: str = "packet", details: dict | None = None):
    import json

    state_path = packet_path / "packet-state.json"

    old = {}
    if state_path.exists():
        try:
            old = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            old = {}

    history = old.get("history", [])
    event = {
        "timestamp": datetime.now().isoformat(),
        "state": state,
        "service": service,
        "details": details or {},
    }
    history.append(event)

    data = {
        "packet": packet_path.name,
        "path": str(packet_path),
        "state": state,
        "updated_at": event["timestamp"],
        "history": history,
    }

    state_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return state_path


def packets_state(args):
    packet = find_packet(args.category, args.packet_name)

    print("\nLAIA PACKET STATE\n")

    if not packet:
        print("Packet not found. Use: laia packets list\n")
        return

    if args.state not in PACKET_STATES:
        print("Unknown state.")
        print("Allowed:")
        for state in PACKET_STATES:
            print(f"- {state}")
        print("")
        return

    state_path = packet_state_write(
        packet,
        args.state,
        service=args.service,
        details={"note": args.note or ""},
    )

    prov = provenance_write(
        service="packet",
        action="state_changed",
        packet=packet.name,
        details={
            "state": args.state,
            "state_file": str(state_path),
            "service": args.service,
            "note": args.note or "",
        },
    )

    print(f"Packet: {packet}")
    print(f"State: {args.state}")
    print(f"State file: {state_path}")
    print(f"Provenance: {prov}\n")


def packets_state_show(args):
    packet = find_packet(args.category, args.packet_name)

    print("\nLAIA PACKET STATE SHOW\n")

    if not packet:
        print("Packet not found. Use: laia packets list\n")
        return

    state_path = packet / "packet-state.json"

    if not state_path.exists():
        print("No packet-state.json found.\n")
        return

    print(state_path.read_text(encoding="utf-8", errors="replace"))


def publish_states(_args=None):
    import json

    out = publish_dir() / "PACKET_STATES.md"

    lines = [
        "# LAIA Packet States",
        "",
        f"Generated: `{datetime.now().isoformat()}`",
        "",
        "| Category | Packet | State | Updated |",
        "|---|---|---|---|",
    ]

    found = False

    for category, d in packet_categories().items():
        if not d.exists():
            continue

        for packet in sorted([p for p in d.iterdir() if p.is_dir()]):
            state_path = packet / "packet-state.json"

            if state_path.exists():
                data = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
                state = data.get("state", "unknown")
                updated = data.get("updated_at", "")
            else:
                state = "unknown"
                updated = ""

            found = True
            lines.append(f"| `{category}` | `{packet.name}` | `{state}` | `{updated}` |")

    if not found:
        lines.append("| _none_ | _none_ | _none_ | _none_ |")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Published: {out}")


def search_packet_states(args):
    import json

    query = " ".join(args.query).lower()

    print(f"\nLAIA PACKET STATE SEARCH — {query}\n")

    matches = []

    for category, d in packet_categories().items():
        if not d.exists():
            continue

        for packet in [p for p in d.iterdir() if p.is_dir()]:
            state_path = packet / "packet-state.json"

            if not state_path.exists():
                continue

            try:
                data = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue

            text = json.dumps(data).lower()

            if query in text:
                matches.append({
                    "category": category,
                    "packet": packet.name,
                    "state": data.get("state", "unknown"),
                    "updated_at": data.get("updated_at", ""),
                    "path": str(state_path),
                })

    if not matches:
        print("No packet state matches found.\n")
        return

    for row in matches:
        print(
            f"- [{row['category']}] {row['packet']} "
            f"| state={row['state']} "
            f"| updated={row['updated_at']}"
        )
        print(f"  {row['path']}")


def visual_caption(args):
    import subprocess

    packet = find_packet("visual", args.packet_name)

    print("\nLAIA VISUAL CAPTION\n")

    if not packet:
        print("Packet not found.\n")
        return

    outputs_dir = packet / "outputs"

    if not outputs_dir.exists():
        print("No outputs directory found.\n")
        return

    manifest_path = packet / "visual-output-manifest.json"
    image = None

    if manifest_path.exists():
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8", errors="replace"))
            newest = data.get("newest_collected_output", "")
            if newest:
                candidate = Path(newest)
                if candidate.exists():
                    image = candidate
        except Exception:
            image = None

    if image is None:
        files = sorted(
            [f for f in outputs_dir.iterdir() if f.is_file()],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        if not files:
            print("No output files found.\n")
            return

        image = files[0]

    prompt = args.prompt or "Describe this image for an archival visual report."

    cmd = [
        "ollama",
        "run",
        args.model,
        prompt,
        str(image),
    ]

    print(f"Model: {args.model}")
    print(f"Image: {image.name}")
    print("Running caption model...\n")

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("Caption generation failed.\n")
        print(result.stderr)
        return

    caption = result.stdout.strip()

    caption_json = packet / "visual-caption.json"
    caption_md = packet / "visual-caption.md"

    data = {
        "packet": args.packet_name,
        "image": str(image),
        "model": args.model,
        "prompt": prompt,
        "caption": caption,
        "created_at": datetime.now().isoformat(),
    }

    caption_json.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )

    md = f"""# LAIA Visual Caption

- Packet: `{args.packet_name}`
- Image: `{image.name}`
- Model: `{args.model}`
- Generated: `{datetime.now().isoformat()}`

## Prompt

{prompt}

## Caption

{caption}
"""

    caption_md.write_text(md, encoding="utf-8")

    packet_state_write(
        packet,
        "captioned",
        service="visual",
        details={
            "caption_file": str(caption_md),
            "model": args.model,
        },
    )

    prov = provenance_write(
        service="visual",
        action="caption_created",
        packet=args.packet_name,
        details={
            "image": str(image),
            "caption_json": str(caption_json),
            "caption_md": str(caption_md),
            "model": args.model,
        },
    )

    print(f"Caption JSON: {caption_json}")
    print(f"Caption MD:   {caption_md}")
    print(f"Provenance:   {prov}")
    print("\nCaption:\n")
    print(caption)
    print("")


def doctor_phase3(_args=None):
    import json
    import urllib.request
    import subprocess

    print("\nLAIA PHASE 3 DOCTOR\n")

    checks = []

    def check(name, ok, detail=""):
        checks.append((name, ok, detail))
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {name}" + (f" — {detail}" if detail else ""))

    # Phase 2 base checks
    check("LAIA root", LAIA_ROOT.exists(), str(LAIA_ROOT))
    check("Packet index", (LAIA_ROOT / "index" / "packets" / "packet_index.json").exists())
    check("Librarian index", (LAIA_ROOT / "index" / "librarian" / "librarian_index.json").exists())
    check("Dashboard status", (publish_dir() / "LAIA_STATUS.md").exists())
    check("Visual dashboard", (publish_dir() / "VISUAL_REPORTS.md").exists())
    check("Packet states dashboard", (publish_dir() / "PACKET_STATES.md").exists())

    # Services
    try:
        with urllib.request.urlopen("http://127.0.0.1:8188", timeout=3) as r:
            check("ComfyUI", r.status == 200, "http://127.0.0.1:8188")
    except Exception as e:
        check("ComfyUI", False, str(e))

    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=8,
        )
        check("Ollama", result.returncode == 0, "ollama list")
        check("LLaVA model", "llava" in result.stdout.lower(), "llava present")
    except Exception as e:
        check("Ollama", False, str(e))
        check("LLaVA model", False, "ollama unavailable")

    # Visual packet checks
    visual_dir = packets_dir() / "visual"
    visual_packets = [p for p in visual_dir.iterdir() if p.is_dir()] if visual_dir.exists() else []
    check("Visual packets", len(visual_packets) > 0, f"{len(visual_packets)} found")

    latest = None
    if visual_packets:
        latest = sorted(visual_packets, key=lambda p: p.stat().st_mtime, reverse=True)[0]
        check("Latest visual packet", latest.exists(), latest.name)
        check("Prompt ID", (latest / "prompt-id.json").exists())
        check("Output manifest", (latest / "visual-output-manifest.json").exists())
        check("Inspection", (latest / "visual-inspection.json").exists())
        check("Caption", (latest / "visual-caption.json").exists())
        check("Report", (latest / "visual-report.md").exists())
        check("Packet state", (latest / "packet-state.json").exists())

        manifest = latest / "visual-output-manifest.json"
        if manifest.exists():
            try:
                data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
                newest = data.get("newest_collected_output", "")
                check("Newest collected output", bool(newest) and Path(newest).exists(), newest)
                check("Manifest prompt_id", bool(data.get("prompt_id", "")), data.get("prompt_id", ""))
            except Exception as e:
                check("Output manifest readable", False, str(e))

        state_file = latest / "packet-state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text(encoding="utf-8", errors="replace")).get("state", "")
                check("Lifecycle state", state == "lifecycle_completed", state)
            except Exception as e:
                check("Lifecycle state", False, str(e))

    failed = [c for c in checks if not c[1]]
    print("")
    print(f"Checks: {len(checks)}")
    print(f"Failed: {len(failed)}")
    print("")


def ocr_packets_dir():
    d = packets_dir() / "ocr"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ocr_status(_args=None):
    import shutil

    print("\nLAIA OCR STATUS\n")
    print(f"OCR packet dir: {ocr_packets_dir()}")

    for tool in ["tesseract", "pdftotext"]:
        found = shutil.which(tool)
        print(f"{tool}: {'PASS' if found else 'MISSING'}" + (f" — {found}" if found else ""))

    print("")


def ocr_packet(args):
    import shutil
    import json

    source = Path(args.source).expanduser().resolve()

    print("\nLAIA OCR PACKET\n")

    if not source.exists():
        print(f"Missing source: {source}\n")
        return

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    slug = slugify(source.stem)[:60]
    packet = ocr_packets_dir() / f"{stamp}-{slug}"
    packet.mkdir(parents=True, exist_ok=True)

    evidence_dir = packet / "evidence"
    evidence_dir.mkdir(exist_ok=True)

    copied = evidence_dir / source.name
    shutil.copy2(source, copied)

    metadata = {
        "type": "ocr",
        "source": str(source),
        "evidence": str(copied),
        "created_at": datetime.now().isoformat(),
        "status": "created",
    }

    (packet / "ocr-source.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    readme = f"""# LAIA OCR Packet

Type: ocr
Created: {metadata['created_at']}

## Source

- Original: `{source}`
- Evidence copy: `{copied}`

## Rules

- Originals are sacred.
- OCR output requires review before archive action.
"""

    (packet / "README.md").write_text(readme, encoding="utf-8")

    packet_state_write(
        packet,
        "created",
        service="ocr",
        details={"source": str(source), "evidence": str(copied)},
    )

    prov = provenance_write(
        service="ocr",
        action="packet_created",
        packet=packet.name,
        details=metadata,
    )

    print(f"Created OCR packet: {packet}")
    print(f"Evidence copy: {copied}")
    print(f"Provenance: {prov}\n")


def ocr_find_packet(packet_name: str):
    p = ocr_packets_dir() / packet_name
    return p if p.exists() else None


def ocr_extract(args):
    import json
    import subprocess
    import shutil

    packet = ocr_find_packet(args.packet_name)

    print("\nLAIA OCR EXTRACT\n")

    if not packet:
        print("OCR packet not found. Use: laia packets list\n")
        return

    source_meta = packet / "ocr-source.json"

    if not source_meta.exists():
        print("Missing ocr-source.json\n")
        return

    meta = json.loads(source_meta.read_text(encoding="utf-8", errors="replace"))
    evidence = Path(meta["evidence"])

    if not evidence.exists():
        print(f"Missing evidence file: {evidence}\n")
        return

    text = ""
    engine = ""
    stderr = ""

    suffix = evidence.suffix.lower()

    if suffix == ".pdf":
        tool = shutil.which("pdftotext")
        if not tool:
            print("pdftotext missing. Install poppler.\n")
            return

        result = subprocess.run(
            [tool, "-layout", str(evidence), "-"],
            capture_output=True,
            text=True,
        )

        text = result.stdout
        stderr = result.stderr
        engine = "pdftotext"

        # Fallback for scanned/image PDFs
        if len(text.strip()) < 50:
            pdftoppm = shutil.which("pdftoppm")
            tesseract = shutil.which("tesseract")

            if pdftoppm and tesseract:
                pages_dir = packet / "ocr_pages"
                pages_dir.mkdir(exist_ok=True)

                prefix = pages_dir / "page"

                render = subprocess.run(
                    [pdftoppm, "-png", "-r", "300", str(evidence), str(prefix)],
                    capture_output=True,
                    text=True,
                )

                page_files = sorted(pages_dir.glob("page-*.png"))
                page_texts = []

                for page in page_files:
                    ocr = subprocess.run(
                        [tesseract, str(page), "stdout"],
                        capture_output=True,
                        text=True,
                    )
                    page_texts.append(f"\n\n--- PAGE {len(page_texts)+1}: {page.name} ---\n\n{ocr.stdout}")
                    stderr += "\n" + ocr.stderr

                if page_texts:
                    text = "\n".join(page_texts)
                    engine = "pdftotext+tesseract_pdf_fallback"

    else:
        tool = shutil.which("tesseract")
        if not tool:
            print("tesseract missing.\n")
            return

        result = subprocess.run(
            [tool, str(evidence), "stdout"],
            capture_output=True,
            text=True,
        )

        text = result.stdout
        stderr = result.stderr
        engine = "tesseract"

    ocr_txt = packet / "ocr.txt"
    ocr_json = packet / "ocr.json"

    ocr_txt.write_text(text, encoding="utf-8")

    data = {
        "packet": args.packet_name,
        "evidence": str(evidence),
        "engine": engine,
        "extracted_at": datetime.now().isoformat(),
        "text_length": len(text),
        "stderr": stderr[-4000:],
        "text_file": str(ocr_txt),
    }

    ocr_json.write_text(json.dumps(data, indent=2), encoding="utf-8")

    packet_state_write(
        packet,
        "extracted",
        service="ocr",
        details={
            "engine": engine,
            "text_file": str(ocr_txt),
            "text_length": len(text),
        },
    )

    prov = provenance_write(
        service="ocr",
        action="text_extracted",
        packet=args.packet_name,
        details=data,
    )

    print(f"Packet: {packet}")
    print(f"Evidence: {evidence}")
    print(f"Engine: {engine}")
    print(f"Text length: {len(text)}")
    print(f"OCR text: {ocr_txt}")
    print(f"OCR JSON: {ocr_json}")
    print(f"Provenance: {prov}\n")

    preview = text.strip()[:1000]
    if preview:
        print("Preview:")
        print(preview)
        print("")
    else:
        print("No text extracted.\n")


def ocr_report(args):
    import json

    packet = ocr_find_packet(args.packet_name)

    print("\nLAIA OCR REPORT\n")

    if not packet:
        print("OCR packet not found. Use: laia packets list\n")
        return

    source_json = packet / "ocr-source.json"
    ocr_json = packet / "ocr.json"
    ocr_txt = packet / "ocr.txt"

    if not source_json.exists():
        print("Missing ocr-source.json\n")
        return

    source = json.loads(source_json.read_text(encoding="utf-8", errors="replace"))

    ocr = {}
    if ocr_json.exists():
        ocr = json.loads(ocr_json.read_text(encoding="utf-8", errors="replace"))

    text = ""
    if ocr_txt.exists():
        text = ocr_txt.read_text(encoding="utf-8", errors="replace")

    report = packet / "ocr-report.md"

    lines = [
        "# LAIA OCR Report",
        "",
        f"- Packet: `{args.packet_name}`",
        f"- Generated: `{datetime.now().isoformat()}`",
        "",
        "## Source",
        "",
        f"- Original: `{source.get('source', '')}`",
        f"- Evidence: `{source.get('evidence', '')}`",
        "",
        "## OCR",
        "",
        f"- Engine: `{ocr.get('engine', 'not run')}`",
        f"- Text length: `{ocr.get('text_length', len(text))}`",
        f"- Text file: `{ocr.get('text_file', str(ocr_txt))}`",
        "",
        "## Extracted Text Preview",
        "",
        "```text",
        text.strip()[:3000] if text.strip() else "No text extracted.",
        "```",
        "",
        "## Detected Fields",
        "",
        "- Document type: `review needed`",
        "- Vendor / sender: `review needed`",
        "- Amount: `review needed`",
        "- Date: `review needed`",
        "- Account / reference: `review needed`",
        "",
        "## Review Notes",
        "",
        "- Human review required before archive action.",
        "- OCR may be incomplete for scanned, low-contrast, or faxed documents.",
        "",
    ]

    report.write_text("\n".join(lines), encoding="utf-8")

    packet_state_write(
        packet,
        "reported",
        service="ocr",
        details={"report": str(report)},
    )

    prov = provenance_write(
        service="ocr",
        action="report_created",
        packet=args.packet_name,
        details={
            "report": str(report),
            "text_length": len(text),
        },
    )

    print(f"Report: {report}")
    print(f"Provenance: {prov}\n")


def ocr_lifecycle(args):
    print("\nLAIA OCR LIFECYCLE\n")

    class Obj:
        pass

    o = Obj()
    o.packet_name = args.packet_name

    print("STEP 1 — Extract text")
    ocr_extract(o)

    print("STEP 2 — Create OCR report")
    ocr_report(o)

    print("STEP 3 — Rebuild librarian index")
    librarian_index(None)

    print("STEP 4 — Publish operational dashboard")
    publish_all(None)

    packet = ocr_find_packet(args.packet_name)
    state_file = None

    if packet:
        state_file = packet_state_write(
            packet,
            "lifecycle_completed",
            service="ocr",
            details={"workflow": "ocr_lifecycle"},
        )

    prov = provenance_write(
        service="ocr",
        action="lifecycle_completed",
        packet=args.packet_name,
        details={
            "status": "success",
            "state_file": str(state_file) if state_file else "",
        },
    )

    print(f"Lifecycle provenance: {prov}")
    print("\nOCR lifecycle complete.\n")


def publish_ocr(_args=None):
    out = publish_dir() / "OCR_REPORTS.md"

    lines = [
        "# LAIA OCR Reports",
        "",
        f"Generated: `{datetime.now().isoformat()}`",
        "",
    ]

    ocr_dir = packets_dir() / "ocr"

    if not ocr_dir.exists():
        lines.append("_No OCR packets found._")
    else:
        packets = sorted(
            [p for p in ocr_dir.iterdir() if p.is_dir()],
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not packets:
            lines.append("_No OCR packets found._")
        else:
            for packet in packets:
                report = packet / "ocr-report.md"
                ocr_txt = packet / "ocr.txt"
                ocr_json = packet / "ocr.json"
                state = packet / "packet-state.json"

                lines.append(f"## {packet.name}")
                lines.append("")
                lines.append(f"- Packet: `{packet}`")
                lines.append(f"- Report: `{'PASS' if report.exists() else 'MISSING'}`")
                lines.append(f"- OCR text: `{'PASS' if ocr_txt.exists() else 'MISSING'}`")
                lines.append(f"- OCR JSON: `{'PASS' if ocr_json.exists() else 'MISSING'}`")
                lines.append(f"- State: `{'PASS' if state.exists() else 'MISSING'}`")

                if report.exists():
                    lines.append("")
                    lines.append("### Report Preview")
                    lines.append("")
                    preview = report.read_text(encoding="utf-8", errors="replace").splitlines()
                    lines.extend(preview[:60])

                lines.append("")

    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Published: {out}")

def main():
    parser = argparse.ArgumentParser(prog="laia")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("briefing")
    sub.add_parser("doctor")
    sub.add_parser("day")

    # Personal OS commands (Phase 1)
    personal_os_p = sub.add_parser("personal-os")
    personal_os_sub = personal_os_p.add_subparsers(dest="subcommand")

    personal_os_init_p = personal_os_sub.add_parser("init")
    personal_os_init_p.set_defaults(func=personal_os_init)

    personal_os_doctor_p = personal_os_sub.add_parser("doctor")
    personal_os_doctor_p.set_defaults(func=personal_os_doctor)

    personal_os_dashboard_p = personal_os_sub.add_parser("dashboard")
    personal_os_dashboard_p.set_defaults(func=personal_os_dashboard)

    personal_os_sync_obsidian_p = personal_os_sub.add_parser("sync-obsidian")
    personal_os_sync_obsidian_p.set_defaults(func=personal_os_sync_obsidian)

    personal_os_briefing_p = personal_os_sub.add_parser("briefing")
    personal_os_briefing_p.add_argument("--write", action="store_true", dest="write")
    personal_os_briefing_p.set_defaults(func=personal_os_briefing)

    personal_os_validate_p = personal_os_sub.add_parser("validate-phase2")
    personal_os_validate_p.add_argument("--write", action="store_true", dest="write")
    personal_os_validate_p.set_defaults(func=personal_os_validate_phase2)

    paths_p = sub.add_parser("paths")
    paths_sub = paths_p.add_subparsers(dest="subcommand")

    paths_show_p = paths_sub.add_parser("show")
    paths_show_p.set_defaults(func=paths_show)

    paths_doctor_p = paths_sub.add_parser("doctor")
    paths_doctor_p.set_defaults(func=paths_doctor)

    paths_write_map_p = paths_sub.add_parser("write-map")
    paths_write_map_p.set_defaults(func=paths_write_map)

    packet_p = sub.add_parser("packet")
    packet_sub = packet_p.add_subparsers(dest="subcommand")

    packet_create_p = packet_sub.add_parser("create")
    packet_create_p.add_argument("title", nargs="+")
    packet_create_p.add_argument("--type", required=True, dest="type")
    packet_create_p.add_argument("--project", required=True, dest="project")
    packet_create_p.add_argument("--status", default="active", dest="status")
    packet_create_p.set_defaults(func=packet_create)

    packet_list_p = packet_sub.add_parser("list")
    packet_list_p.set_defaults(func=packet_list)

    packet_show_p = packet_sub.add_parser("show")
    packet_show_p.add_argument("packet_id")
    packet_show_p.set_defaults(func=packet_show)

    packet_update_p = packet_sub.add_parser("update")
    packet_update_p.add_argument("packet_id")
    packet_update_p.add_argument("--status", dest="status")
    packet_update_p.add_argument("--summary", dest="summary")
    packet_update_p.add_argument("--project", dest="project")
    packet_update_p.add_argument("--type", dest="type")
    packet_update_p.add_argument("--next-action", dest="next_action")
    packet_update_p.set_defaults(func=packet_update)

    packet_close_p = packet_sub.add_parser("close")
    packet_close_p.add_argument("packet_id")
    packet_close_p.add_argument("--reason", default="", dest="reason")
    packet_close_p.set_defaults(func=packet_close)

    agent_p = sub.add_parser("agent")
    agent_sub = agent_p.add_subparsers(dest="subcommand")

    agent_list_p = agent_sub.add_parser("list")
    agent_list_p.set_defaults(func=agent_list)

    agent_brief_p = agent_sub.add_parser("brief")
    agent_brief_p.add_argument("agent_name", choices=["operator", "librarian", "ingest", "documentation", "all"])
    agent_brief_p.add_argument("--write", action="store_true", dest="write")
    agent_brief_p.set_defaults(func=agent_brief)

    report_p = sub.add_parser("report")
    report_sub = report_p.add_subparsers(dest="subcommand")

    report_create_p = report_sub.add_parser("create")
    report_create_p.add_argument("packet_id")
    report_create_p.set_defaults(func=report_create)

    report_list_p = report_sub.add_parser("list")
    report_list_p.set_defaults(func=report_list)

    report_show_p = report_sub.add_parser("show")
    report_show_p.add_argument("report_id")
    report_show_p.set_defaults(func=report_show)

    # Mode management
    mode_p = sub.add_parser("mode")
    mode_sub = mode_p.add_subparsers(dest="subcommand")

    mode_list_p = mode_sub.add_parser("list")
    mode_list_p.set_defaults(func=mode_list)

    mode_show_p = mode_sub.add_parser("show")
    mode_show_p.set_defaults(func=mode_show)

    mode_set_p = mode_sub.add_parser("set")
    mode_set_p.add_argument("mode")
    mode_set_p.add_argument("--reason", default="")
    mode_set_p.set_defaults(func=mode_set)

    focus_p = sub.add_parser("focus")
    focus_p.add_argument("--energy", default=None)
    focus_p.add_argument("--project", default=None)
    focus_p.add_argument("--max-time", dest="max_time", default=None)

    plan_p = sub.add_parser("plan")
    plan_sub = plan_p.add_subparsers(dest="subcommand")
    plan_sub.add_parser("generate")
    plan_sub.add_parser("today")

    sync_p = sub.add_parser("sync")
    sync_sub = sync_p.add_subparsers(dest="subcommand")
    sync_sub.add_parser("status")

    sync_dry = sync_sub.add_parser("dry-run")
    sync_dry.add_argument("--pull", action="store_true")

    sync_sub.add_parser("push")
    sync_sub.add_parser("pull")

    test_model_p = sub.add_parser("test-model")
    test_model_p.add_argument("model")
    test_model_p.add_argument("prompt", nargs="+")

    dictation_p = sub.add_parser("dictation")
    dictation_sub = dictation_p.add_subparsers(dest="subcommand")

    dict_note = dictation_sub.add_parser("note")
    dict_note.add_argument("text", nargs="+")
    dict_note.set_defaults(func=dictation_note)

    dict_task = dictation_sub.add_parser("task")
    dict_task.add_argument("text", nargs="+")
    dict_task.set_defaults(func=dictation_task)

    dict_meal = dictation_sub.add_parser("meal")
    dict_meal.add_argument("text", nargs="+")
    dict_meal.set_defaults(func=dictation_meal)


    dev_p = sub.add_parser("dev")
    dev_sub = dev_p.add_subparsers(dest="subcommand")

    dev_request_p = dev_sub.add_parser("request")
    dev_request_p.add_argument("text", nargs="+")
    dev_request_p.add_argument("--type", dest="request_type", default="feature_plan")
    dev_request_p.set_defaults(func=dev_request)

    dev_inbox_p = dev_sub.add_parser("inbox")
    dev_inbox_p.set_defaults(func=dev_inbox)

    dev_result_p = dev_sub.add_parser("result")
    dev_result_p.add_argument("request_file")
    dev_result_p.add_argument("text", nargs="+")
    dev_result_p.set_defaults(func=dev_result)

    dev_process_p = dev_sub.add_parser("process-latest")
    dev_process_p.add_argument("--model", default="mistral")
    dev_process_p.set_defaults(func=dev_process_latest)

    dev_process_file_p = dev_sub.add_parser("process")
    dev_process_file_p.add_argument("request_file")
    dev_process_file_p.add_argument("--model", default="mistral")
    dev_process_file_p.set_defaults(func=dev_process_file)

    add_documents_parser(sub)



    nas_p = sub.add_parser("nas")
    nas_sub = nas_p.add_subparsers(dest="subcommand")

    nas_latest_p = nas_sub.add_parser("latest")
    nas_latest_p.set_defaults(func=nas_latest)

    nas_manifests_p = nas_sub.add_parser("manifests")
    nas_manifests_p.set_defaults(func=nas_manifests)

    nas_find_p = nas_sub.add_parser("find")
    nas_find_p.add_argument("query", nargs="+")
    nas_find_p.set_defaults(func=nas_find)


    packets_p = sub.add_parser("packets")
    packets_sub = packets_p.add_subparsers(dest="subcommand")

    packets_create_p = packets_sub.add_parser("create")
    packets_create_p.add_argument("kind")
    packets_create_p.add_argument("query", nargs="+")
    packets_create_p.set_defaults(func=packets_create)

    packets_latest_p = packets_sub.add_parser("latest")
    packets_latest_p.add_argument("category", nargs="?")
    packets_latest_p.set_defaults(func=packets_latest)

    packets_show_p = packets_sub.add_parser("show")
    packets_show_p.add_argument("category_or_name")
    packets_show_p.add_argument("packet_name", nargs="?")
    packets_show_p.set_defaults(func=packets_show)

    packets_list_p = packets_sub.add_parser("list")
    packets_list_p.set_defaults(func=packets_list)

    packets_index_p = packets_sub.add_parser("index")
    packets_index_p.set_defaults(func=packets_index)

    packets_state_p = packets_sub.add_parser("state")
    packets_state_p.add_argument("category")
    packets_state_p.add_argument("packet_name")
    packets_state_p.add_argument("state")
    packets_state_p.add_argument("--service", default="operator")
    packets_state_p.add_argument("--note", default="")
    packets_state_p.set_defaults(func=packets_state)

    packets_state_show_p = packets_sub.add_parser("state-show")
    packets_state_show_p.add_argument("category")
    packets_state_show_p.add_argument("packet_name")
    packets_state_show_p.set_defaults(func=packets_state_show)


    visual_p = sub.add_parser("visual")
    visual_sub = visual_p.add_subparsers(dest="subcommand")

    visual_status_p = visual_sub.add_parser("status")
    visual_status_p.set_defaults(func=visual_status)

    visual_profiles_p = visual_sub.add_parser("profiles")
    visual_profiles_p.set_defaults(func=visual_profiles)

    visual_profile_p = visual_sub.add_parser("profile")
    visual_profile_p.add_argument("name")
    visual_profile_p.set_defaults(func=visual_profile)

    visual_run_p = visual_sub.add_parser("run")
    visual_run_p.add_argument("profile")
    visual_run_p.add_argument("prompt", nargs="*")
    visual_run_p.add_argument("--dry-run", action="store_true")
    visual_run_p.set_defaults(func=visual_run)

    visual_packet_p = visual_sub.add_parser("packet")
    visual_packet_p.add_argument("profile")
    visual_packet_p.add_argument("prompt", nargs="+")
    visual_packet_p.set_defaults(func=visual_packet)

    visual_generate_p = visual_sub.add_parser("generate")
    visual_generate_p.add_argument("--profile", dest="profile")
    visual_generate_p.add_argument("--packet", dest="packet_name")
    visual_generate_p.add_argument("prompt", nargs="*")
    visual_generate_p.add_argument("--dry-run", action="store_true")
    visual_generate_p.set_defaults(func=visual_generate)

    visual_collect_p = visual_sub.add_parser("collect")
    visual_collect_p.add_argument("packet_name")
    visual_collect_p.add_argument("--limit", type=int, default=1)
    visual_collect_p.add_argument("--force", action="store_true")
    visual_collect_p.set_defaults(func=visual_collect)

    visual_outputs_p = visual_sub.add_parser("outputs")
    visual_outputs_p.add_argument("packet_name")
    visual_outputs_p.set_defaults(func=visual_outputs)

    visual_caption_p = visual_sub.add_parser("caption")
    visual_caption_p.add_argument("packet_name")
    visual_caption_p.add_argument("--model", default="llava:latest")
    visual_caption_p.add_argument("--prompt", default="")
    visual_caption_p.set_defaults(func=visual_caption)

    visual_review_p = visual_sub.add_parser("review")
    visual_review_p.add_argument("packet")
    visual_review_p.set_defaults(func=visual_review)

    visual_inspect_p = visual_sub.add_parser("inspect")
    visual_inspect_p.add_argument("packet_name")
    visual_inspect_p.set_defaults(func=visual_inspect)

    visual_report_p = visual_sub.add_parser("report")
    visual_report_p.add_argument("packet_name")
    visual_report_p.set_defaults(func=visual_report)

    visual_lifecycle_p = visual_sub.add_parser("lifecycle")
    visual_lifecycle_p.add_argument("packet_name")
    visual_lifecycle_p.add_argument("--limit", type=int, default=1)
    visual_lifecycle_p.add_argument("--force", action="store_true")
    visual_lifecycle_p.add_argument("--model", default="llava:latest")
    visual_lifecycle_p.add_argument("--caption-prompt", default="")
    visual_lifecycle_p.set_defaults(func=visual_lifecycle)

    visual_submit_p = visual_sub.add_parser("submit")
    visual_submit_p.add_argument("packet_name")
    visual_submit_p.add_argument("workflow")
    visual_submit_p.add_argument("--dry-run", action="store_true")
    visual_submit_p.set_defaults(func=visual_generate_submit)

    visual_inspect_workflow_p = visual_sub.add_parser("inspect-workflow")
    visual_inspect_workflow_p.add_argument("workflow_file")
    visual_inspect_workflow_p.set_defaults(func=visual_inspect_workflow)

    visual_doctor_p = visual_sub.add_parser("doctor")
    visual_doctor_p.set_defaults(func=visual_doctor)


    search_p = sub.add_parser("search")
    search_sub = search_p.add_subparsers(dest="subcommand")

    search_packets_p = search_sub.add_parser("packets")
    search_packets_p.add_argument("query", nargs="+")
    search_packets_p.set_defaults(func=search_packets)

    search_all_p = search_sub.add_parser("all")
    search_all_p.add_argument("query", nargs="+")
    search_all_p.set_defaults(func=search_all)


    provenance_p = sub.add_parser("provenance")
    provenance_sub = provenance_p.add_subparsers(dest="subcommand")

    provenance_log_p = provenance_sub.add_parser("log")
    provenance_log_p.add_argument("service")
    provenance_log_p.add_argument("action")
    provenance_log_p.add_argument("--packet", default="")
    provenance_log_p.add_argument("--detail", nargs="*", default=[])
    provenance_log_p.set_defaults(func=provenance_log)

    provenance_list_p = provenance_sub.add_parser("list")
    provenance_list_p.add_argument("--limit", type=int, default=20)
    provenance_list_p.set_defaults(func=provenance_list)

    provenance_search_p = provenance_sub.add_parser("search")
    provenance_search_p.add_argument("query", nargs="+")
    provenance_search_p.set_defaults(func=provenance_search)

    provenance_packet_p = provenance_sub.add_parser("packet")
    provenance_packet_p.add_argument("packet_name")
    provenance_packet_p.set_defaults(func=provenance_packet)


    nodes_p = sub.add_parser("nodes")
    nodes_sub = nodes_p.add_subparsers(dest="subcommand")

    nodes_list_p = nodes_sub.add_parser("list")
    nodes_list_p.set_defaults(func=nodes_list)

    nodes_show_p = nodes_sub.add_parser("show")
    nodes_show_p.add_argument("node_id")
    nodes_show_p.set_defaults(func=nodes_show)

    nodes_cap_p = nodes_sub.add_parser("capabilities")
    nodes_cap_p.set_defaults(func=nodes_capabilities)


    librarian_p = sub.add_parser("librarian")
    librarian_sub = librarian_p.add_subparsers(dest="subcommand")

    librarian_status_p = librarian_sub.add_parser("status")
    librarian_status_p.add_argument("--root", dest="root", help="Archive root path")
    librarian_status_p.set_defaults(func=librarian_status)

    librarian_scan_p = librarian_sub.add_parser("scan")
    librarian_scan_p.add_argument("--dry-run", action="store_true", dest="dry_run")
    librarian_scan_p.add_argument("--root", dest="root", help="Archive root path")
    librarian_scan_p.set_defaults(func=librarian_scan)

    librarian_find_p = librarian_sub.add_parser("find")
    librarian_find_p.add_argument("query", nargs="+", help="Search query")
    librarian_find_p.set_defaults(func=librarian_find)

    librarian_packet_p = librarian_sub.add_parser("packet")
    librarian_packet_p.add_argument("query", nargs="+", help="Packet query")
    librarian_packet_p.set_defaults(func=librarian_packet)

    librarian_report_p = librarian_sub.add_parser("report")
    librarian_report_p.set_defaults(func=librarian_report)

    librarian_summary_p = librarian_sub.add_parser("summarize")
    librarian_summary_p.set_defaults(func=librarian_summarize)

    librarian_index_p = librarian_sub.add_parser("index")
    librarian_index_p.set_defaults(func=librarian_index)

    librarian_orphaned_p = librarian_sub.add_parser("orphaned")
    librarian_orphaned_p.set_defaults(func=librarian_orphaned)


    jobs_p = sub.add_parser("jobs")
    jobs_sub = jobs_p.add_subparsers(dest="subcommand")

    jobs_create_p = jobs_sub.add_parser("create")
    jobs_create_p.add_argument("title", nargs="+")
    jobs_create_p.add_argument("--packet", default="")
    jobs_create_p.add_argument("--service", default="planner")
    jobs_create_p.set_defaults(func=jobs_create)

    jobs_list_p = jobs_sub.add_parser("list")
    jobs_list_p.set_defaults(func=jobs_list)

    jobs_show_p = jobs_sub.add_parser("show")
    jobs_show_p.add_argument("job_id")
    jobs_show_p.set_defaults(func=jobs_show)

    jobs_approve_p = jobs_sub.add_parser("approve")
    jobs_approve_p.add_argument("job_id")
    jobs_approve_p.set_defaults(func=jobs_approve)

    jobs_complete_p = jobs_sub.add_parser("complete")
    jobs_complete_p.add_argument("job_id")
    jobs_complete_p.set_defaults(func=jobs_complete)

    jobs_reopen_p = jobs_sub.add_parser("reopen")
    jobs_reopen_p.add_argument("job_id")
    jobs_reopen_p.set_defaults(func=jobs_reopen)


    publish_p = sub.add_parser("publish")
    publish_sub = publish_p.add_subparsers(dest="subcommand")

    publish_status_p = publish_sub.add_parser("status")
    publish_status_p.set_defaults(func=publish_status)

    publish_packets_p = publish_sub.add_parser("packets")
    publish_packets_p.set_defaults(func=publish_packets)

    publish_provenance_p = publish_sub.add_parser("provenance")
    publish_provenance_p.set_defaults(func=publish_provenance)

    publish_jobs_p = publish_sub.add_parser("jobs")
    publish_jobs_p.set_defaults(func=publish_jobs)

    publish_visual_p = publish_sub.add_parser("visual")
    publish_visual_p.set_defaults(func=publish_visual)

    publish_states_p = publish_sub.add_parser("states")
    publish_states_p.set_defaults(func=publish_states)

    publish_ocr_p = publish_sub.add_parser("ocr")
    publish_ocr_p.set_defaults(func=publish_ocr)

    publish_all_p = publish_sub.add_parser("all")
    publish_all_p.set_defaults(func=publish_all)

    publish_refresh_p = publish_sub.add_parser("refresh")
    publish_refresh_p.add_argument("--interval", type=int, default=60)
    publish_refresh_p.add_argument("--count", type=int, default=1)
    publish_refresh_p.set_defaults(func=publish_refresh)


    phase2_doctor_p = sub.add_parser("phase2-doctor")
    phase2_doctor_p.set_defaults(func=doctor_phase2)


    phase3_doctor_p = sub.add_parser("phase3-doctor")
    phase3_doctor_p.set_defaults(func=doctor_phase3)


    ocr_p = sub.add_parser("ocr")
    ocr_sub = ocr_p.add_subparsers(dest="subcommand")

    ocr_status_p = ocr_sub.add_parser("status")
    ocr_status_p.set_defaults(func=ocr_status)

    ocr_packet_p = ocr_sub.add_parser("packet")
    ocr_packet_p.add_argument("source")
    ocr_packet_p.set_defaults(func=ocr_packet)

    ocr_extract_p = ocr_sub.add_parser("extract")
    ocr_extract_p.add_argument("packet_name")
    ocr_extract_p.set_defaults(func=ocr_extract)

    ocr_report_p = ocr_sub.add_parser("report")
    ocr_report_p.add_argument("packet_name")
    ocr_report_p.set_defaults(func=ocr_report)

    ocr_lifecycle_p = ocr_sub.add_parser("lifecycle")
    ocr_lifecycle_p.add_argument("packet_name")
    ocr_lifecycle_p.set_defaults(func=ocr_lifecycle)

    args = parser.parse_args()

    if args.command == "briefing":
        briefing(args)
    elif args.command == "doctor":
        doctor(args)
    elif args.command == "day":
        day_command(args)
    elif args.command == "focus":
        focus_task(args)
    elif args.command == "plan" and args.subcommand == "generate":
        plan_generate(args)
    elif args.command == "plan" and args.subcommand == "today":
        plan_today(args)
    elif args.command == "sync" and args.subcommand == "status":
        sync_status(args)
    elif args.command == "sync" and args.subcommand == "dry-run":
        sync_dry_run(args)
    elif args.command == "sync" and args.subcommand == "push":
        sync_push(args)
    elif args.command == "sync" and args.subcommand == "pull":
        sync_pull(args)
    elif args.command == "test-model":
        test_model(args)
    elif args.command == "dictation" and args.subcommand == "note":
        dictation_note(args)
    elif args.command == "dictation" and args.subcommand == "task":
        dictation_task(args)
    elif args.command == "dictation" and args.subcommand == "meal":
        dictation_meal(args)

    elif args.command == "dev" and args.subcommand == "request":
        dev_request(args)
    elif args.command == "dev" and args.subcommand == "inbox":
        dev_inbox(args)
    elif args.command == "dev" and args.subcommand == "result":
        dev_result(args)
    elif args.command == "dev" and args.subcommand == "process-latest":
        dev_process_latest(args)
    elif args.command == "dev" and args.subcommand == "process":
        dev_process_file(args)

    elif hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
