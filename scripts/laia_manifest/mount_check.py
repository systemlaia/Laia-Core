#!/usr/bin/env python3
from pathlib import Path
import argparse, json, datetime, subprocess

def run(cmd):
    return subprocess.run(cmd, shell=True, text=True, capture_output=True)

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--path", default="~/NAS/Public")
    p.add_argument("--expect", default="Media/Photos")
    p.add_argument("--out", default="archive/reports")
    args = p.parse_args()

    root = Path(args.path).expanduser()
    expected = root / args.expect
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")

    mount_info = run("mount").stdout
    df_info = run(f'df -h "{root}" 2>/dev/null').stdout

    report = {
        "generated": stamp,
        "root": str(root),
        "expected_path": str(expected),
        "root_exists": root.exists(),
        "expected_exists": expected.exists(),
        "is_mount_visible": str(root) in mount_info or "Public" in mount_info,
        "mount_lines": [line for line in mount_info.splitlines() if "Public" in line or "NAS" in line or "smbfs" in line],
        "df": df_info,
        "status": "ok" if root.exists() and expected.exists() else "missing",
    }

    json_path = out / f"mount_check_{stamp}.json"
    md_path = out / f"mount_check_{stamp}.md"

    json_path.write_text(json.dumps(report, indent=2))

    md_path.write_text(
        "# LAIA NAS Mount Check\n\n"
        f"- Generated: `{stamp}`\n"
        f"- Root: `{root}`\n"
        f"- Expected path: `{expected}`\n"
        f"- Root exists: `{report['root_exists']}`\n"
        f"- Expected exists: `{report['expected_exists']}`\n"
        f"- Status: `{report['status']}`\n\n"
        "## Mount Lines\n\n"
        + "\n".join(f"- `{line}`" for line in report["mount_lines"])
        + "\n\n## Disk Info\n\n```text\n"
        + df_info
        + "\n```\n"
    )

    print(f"JSON: {json_path}")
    print(f"MD:   {md_path}")
    print(f"Status: {report['status']}")

if __name__ == "__main__":
    main()
