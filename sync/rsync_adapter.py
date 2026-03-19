import subprocess


def build_rsync_command(source: str, destination: str, dry_run: bool = False):
    cmd = [
        "rsync",
        "-av",
        "--update",
        "--human-readable",
        "--backup",
        "--suffix=.incoming",
    ]
    if dry_run:
        cmd.append("--dry-run")
    cmd.extend([source, destination])
    return cmd


def run_command(cmd):
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
    )
