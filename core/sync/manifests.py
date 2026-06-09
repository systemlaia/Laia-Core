from pathlib import Path
from datetime import datetime


def write_sync_report(reviews_dir: Path, mode: str, lines: list[str]) -> Path:
    reviews_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    path = reviews_dir / f"sync-report-{ts}.md"

    body = "# LAIA Sync Report\n\n"
    body += f"- Time: {datetime.now().isoformat()}\n"
    body += f"- Mode: {mode}\n\n"
    body += "## Details\n\n"
    for line in lines:
        body += f"- {line}\n"

    path.write_text(body, encoding="utf-8")
    return path
