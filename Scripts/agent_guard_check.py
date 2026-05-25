#!/usr/bin/env python3
import argparse
import subprocess
import sys

SUSPICIOUS_PATTERNS = [
    "rm -rf",
    "os.remove",
    "os.rename",
    "os.rmdir",
    "shutil.move",
    "Path.unlink",
    ".unlink(",
    "rmtree",
    "write_text(",
    'open("/Volumes/Public"',
    "/Volumes/Public",
    "librarian retrieve",
    "--execute",
]

def main() -> int:
    parser = argparse.ArgumentParser(description="Heuristic LAIA agent guard check.")
    parser.add_argument("--strict", action="store_true", help="Exit nonzero if warnings are found.")
    args = parser.parse_args()

    try:
        result = subprocess.run(
            ["git", "--no-pager", "diff"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        print("FAIL: could not read git diff")
        print(exc.stderr)
        return 2

    diff = result.stdout

    if not diff.strip():
        print("PASS: git diff is empty; no guard warnings.")
        return 0

    warnings = []
    for pattern in SUSPICIOUS_PATTERNS:
        if pattern in diff:
            warnings.append(pattern)

    if warnings:
        print("WARN: suspicious patterns found in git diff:")
        for pattern in warnings:
            print(f"- {pattern}")
        print()
        print("This is a heuristic guard, not a security boundary.")
        if args.strict:
            return 1
    else:
        print("PASS: no suspicious guard patterns found in git diff.")

    return 0

if __name__ == "__main__":
    sys.exit(main())
