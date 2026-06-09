from pathlib import Path
from datetime import datetime


def rename_conflict_copy(file_path: Path, source_node: str):
    ts = datetime.now().strftime("%Y-%m-%d-%H%M")
    name = file_path.name
    if name.endswith(".md.incoming"):
        base = name[:-12]
        new_name = f"{base}.conflict-{source_node}-{ts}.md"
    else:
        new_name = f"{file_path.stem}.conflict-{source_node}-{ts}{file_path.suffix}"
    new_path = file_path.parent / new_name
    file_path.rename(new_path)
    return new_path


def process_incoming_conflicts(local_root: Path, source_node: str = "core"):
    conflicts = []
    for path in local_root.rglob("*.incoming"):
        original_name = path.name[:-9]
        original = path.parent / original_name
        if original.exists():
            new_path = rename_conflict_copy(path, source_node)
            conflicts.append(new_path)
        else:
            path.rename(original)
    return conflicts


def detect_markdown_conflicts(local_root: Path):
    return [p for p in local_root.rglob("*.md") if ".conflict-" in p.name]
