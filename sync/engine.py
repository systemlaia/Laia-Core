from pathlib import Path
from sync.discovery import load_sync_config, ssh_core_reachable
from sync.rsync_adapter import build_rsync_command, run_command
from sync.conflict import process_incoming_conflicts, detect_markdown_conflicts
from sync.manifests import write_sync_report


def sync_domain(config, local_root: Path, domain_name: str, domain_cfg: dict, direction="push", dry_run=False):
    remote_base = f"{config['core_user']}@{config['core_host']}:{config['core_root']}"
    mode = domain_cfg.get("mode")
    paths = domain_cfg.get("paths", [])
    lines = []

    for rel_path in paths:
        local_path = local_root / rel_path

        if direction == "push":
            if mode in ("pull_only", "core_dominant"):
                lines.append(f"SKIP {domain_name}: {rel_path} (mode={mode})")
                continue
            source = str(local_path) + "/"
            destination = f"{remote_base}/{rel_path}/"
        else:
            if mode in ("push_only",):
                lines.append(f"SKIP {domain_name}: {rel_path} (mode={mode})")
                continue
            source = f"{remote_base}/{rel_path}/"
            destination = str(local_path) + "/"

        local_path.mkdir(parents=True, exist_ok=True)
        cmd = build_rsync_command(source, destination, dry_run=dry_run)
        result = run_command(cmd)

        if result.returncode == 0:
            lines.append(f"{'DRY-RUN' if dry_run else 'SYNCED'} {domain_name}: {rel_path}")
        else:
            err = (result.stderr or "").strip() or "unknown rsync error"
            lines.append(f"ERROR {domain_name}: {rel_path} — {err}")

    return lines


def sync_status(config_path: Path, local_root: Path):
    config = load_sync_config(config_path)
    return {
        "core_host": config.get("core_host"),
        "core_user": config.get("core_user"),
        "core_reachable": ssh_core_reachable(config["core_user"], config["core_host"]),
        "pending_conflicts": len(detect_markdown_conflicts(local_root)),
    }


def sync_run(config_path: Path, local_root: Path, reviews_dir: Path, direction="push", dry_run=False):
    config = load_sync_config(config_path)

    if not ssh_core_reachable(config["core_user"], config["core_host"]):
        return False, ["Core not reachable"], None

    all_lines = []
    for domain_name, domain_cfg in config.get("domains", {}).items():
        all_lines.extend(sync_domain(config, local_root, domain_name, domain_cfg, direction=direction, dry_run=dry_run))

    if not dry_run:
        conflicts = process_incoming_conflicts(local_root, source_node="core")
        if conflicts:
            all_lines.append(f"Conflicts detected: {len(conflicts)}")
            for c in conflicts[:10]:
                all_lines.append(f"conflict copy: {c}")

    report = write_sync_report(reviews_dir, f"{'dry-run ' if dry_run else ''}{direction}", all_lines)
    return True, all_lines, report
