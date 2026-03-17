#!/usr/bin/env python3
import argparse
import os
import subprocess
from pathlib import Path
from datetime import date
import yaml

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

def load_yaml_file(path: Path):
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_sync_config():
    path = LAIA_ROOT / "core" / "configs" / "sync-config.yaml"
    data = load_yaml_file(path)
    if not data:
        raise FileNotFoundError(f"Missing sync config: {path}")
    return data

def command_exists(name):
    try:
        result = subprocess.run(["which", name], capture_output=True, text=True, check=False)
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
    scores = {"Critical": 100, "High": 80, "Medium": 50, "Low": 20}
    return scores.get(value, 0)

def time_score(value):
    scores = {"15m": 20, "30m": 18, "1h": 15, "2h": 10, "Half Day": 5, "Full Day": 2}
    return scores.get(value, 0)

def momentum_score(value):
    scores = {"High": 20, "Medium": 10, "Low": 5, "None": 0}
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
    print(f"\\nLAIA DAILY BRIEFING — {date.today()}\\n")
    print("Commands:")
    print("- laia day")
    print("- laia focus")
    print("- laia sync status")
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

            candidates.append((score, fm, project))

    candidates.sort(key=lambda x: x[0], reverse=True)

    print("\\nLAIA FOCUS\\n")
    if not candidates:
        print("No matching ready tasks found.\\n")
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
    body = f"# Daily Plan {date.today()}\\n\\n## Tasks\\n"
    if ready:
        body += "\\n".join([f"- [ ] {t.get('title', 'Untitled')}" for t in ready[:5]]) + "\\n"
    else:
        body += "- No ready tasks found\\n"

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

    content = "---\\n" + yaml.safe_dump(fm, sort_keys=False, allow_unicode=True) + "---\\n\\n" + body
    plan_path.write_text(content, encoding="utf-8")
    print(f"Generated: {plan_path}")

def plan_today(_args=None):
    path = today_plan_path()
    if not path.exists():
        print("No plan found for today. Run: laia plan generate\\n")
        return
    print(path.read_text(encoding="utf-8"))

def sync_status(_args=None):
    print("\\nLAIA SYNC STATUS\\n")
    try:
        config = load_sync_config()
    except Exception as e:
        print(f"Sync config error: {e}\\n")
        return

    print(f"Core Host: {config.get('core_host')}")
    print(f"Core User: {config.get('core_user')}")
    print(f"rsync available: {'Yes' if command_exists('rsync') else 'No'}")
    print(f"ssh available: {'Yes' if command_exists('ssh') else 'No'}")
    print(f"Core reachable: {'Yes' if ssh_core_reachable(config) else 'No'}")
    print("")

def doctor(_args=None):
    print("\\nLAIA DOCTOR REPORT\\n")

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

def day_command(args):
    print(f"\\nLAIA DAY BRIEFING — {date.today()}\\n")
    print("System:")
    sync_status(args)
    if not today_plan_path().exists():
        print("No daily plan found. Generating one.\\n")
        plan_generate(args)
    print("Focus:")
    focus_task(args)

def main():
    parser = argparse.ArgumentParser(prog="laia")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("briefing")
    sub.add_parser("doctor")
    sub.add_parser("day")

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
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
