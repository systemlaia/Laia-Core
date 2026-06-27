import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

try:
    from photo_ingest.cohorts import (
        _read_json,
        _write_json,
        add_files,
        build_contact_sheet_html,
        cohort_dir,
        create_cohort,
        export_cohort,
        preview_for,
        read_cohort,
        read_cohort_index,
        update_cohort,
        utc_now,
    )
except ModuleNotFoundError:
    from core.photo_ingest.cohorts import (
        _read_json,
        _write_json,
        add_files,
        build_contact_sheet_html,
        cohort_dir,
        create_cohort,
        export_cohort,
        preview_for,
        read_cohort,
        read_cohort_index,
        update_cohort,
        utc_now,
    )


IMAGE_TYPES = {"cover_front", "cover_back", "label", "vinyl", "spine", "detail", "unknown"}
CONFIDENCE_VALUES = {"low", "medium", "high"}
RECORD_PROMPT = """You are identifying a vinyl record from a photograph.

Return JSON only.

If visible, extract:
- image_type
- artist
- title
- record_label
- catalog_number
- visible_text
- format_hint
- confidence
- uncertainty_note

Allowed image_type values: cover_front, cover_back, label, vinyl, spine, detail, unknown.
Do not invent information that is not visible. If the image is not a front cover or label,
set image_type accordingly."""


def selected_files(cohort: dict, start: Optional[str] = None, end: Optional[str] = None, limit: Optional[int] = None) -> list[dict]:
    files = list(cohort.get("files", []))
    paths = [row["relative_path"] for row in files]
    if start:
        matches = [index for index, value in enumerate(paths) if value == start or Path(value).name == start]
        if not matches:
            raise SystemExit(f"Start file not found in cohort: {start}")
        files = files[matches[0] :]
        paths = [row["relative_path"] for row in files]
    if end:
        matches = [index for index, value in enumerate(paths) if value == end or Path(value).name == end]
        if not matches:
            raise SystemExit(f"End file not found in cohort: {end}")
        files = files[: matches[0] + 1]
    return files[:limit] if limit is not None else files


def parse_vision_json(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, flags=re.S)
        if not match:
            raise ValueError("Model response did not contain a JSON object.")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Model response JSON must be an object.")
    image_type = str(data.get("image_type", "unknown")).strip().lower()
    data["image_type"] = image_type if image_type in IMAGE_TYPES else "unknown"
    confidence = str(data.get("confidence", "low")).strip().lower()
    data["confidence"] = confidence if confidence in CONFIDENCE_VALUES else "low"
    data["visible_text"] = data.get("visible_text", [])
    if not isinstance(data["visible_text"], list):
        data["visible_text"] = [str(data["visible_text"])]
    for key in ["artist", "title", "record_label", "catalog_number", "format_hint", "uncertainty_note"]:
        data[key] = str(data.get(key, "") or "")
    return data


def ollama_preflight(model: str) -> str:
    executable = shutil.which("ollama")
    if not executable:
        raise SystemExit(
            f"Ollama model unavailable: {model}\nInstall or pull with:\n  ollama pull {model}"
        )
    result = subprocess.run([executable, "list"], capture_output=True, text=True, check=False)
    names = {
        line.split()[0]
        for line in result.stdout.splitlines()[1:]
        if line.strip()
    }
    available = any(name == model or name.split(":")[0] == model.split(":")[0] for name in names)
    if result.returncode != 0 or not available:
        raise SystemExit(
            f"Ollama model unavailable: {model}\nInstall or pull with:\n  ollama pull {model}"
        )
    return executable


def run_ollama_image(executable: str, model: str, image: Path) -> str:
    prompt = RECORD_PROMPT + f"\n\nImage file: {image}"
    result = subprocess.run(
        [executable, "run", model, prompt, str(image)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Ollama failed.")
    return result.stdout


def vision_sidecar_path(packet: Path, cohort_id: str, relative_path: str) -> Path:
    relative = Path(relative_path)
    return cohort_dir(packet, cohort_id) / "vision" / relative.parent / f"{relative.name}.record_id.json"


def write_candidate_aggregates(packet: Path, cohort: dict, candidates: list[dict]) -> tuple[Path, Path]:
    root = cohort_dir(packet, cohort["cohort_id"]) / "vision"
    json_path = root / "record_candidates.json"
    markdown_path = root / "record_candidates.md"
    aggregate = {
        "record_type": "laia.photo_record_candidates", "record_version": "0.1",
        "packet_id": packet.name, "cohort_id": cohort["cohort_id"],
        "generated_at": utc_now(), "candidate_count": len(candidates), "candidates": candidates,
    }
    _write_json(json_path, aggregate)
    lines = ["# Record Candidates", ""]
    for row in candidates:
        lines.extend([f"## {row['relative_path']}", ""])
        if row.get("status") == "failed":
            lines.extend(["status: failed", f"error: {row.get('error', '')}", ""])
            continue
        candidate = row["candidate"]
        for key in ["image_type", "artist", "title", "record_label", "catalog_number", "format_hint", "confidence"]:
            lines.append(f"{key}: {candidate.get(key, '')}")
        lines.append("visible text:")
        lines.extend(f"- {value}" for value in candidate.get("visible_text", []))
        lines.extend(["uncertainty:", candidate.get("uncertainty_note", ""), ""])
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def identify_records(
    packet: Path,
    cohort_query: str,
    model: str = "llava",
    limit: Optional[int] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    force: bool = False,
) -> dict:
    cohort = read_cohort(packet, cohort_query)
    files = selected_files(cohort, start, end, limit)
    executable = ollama_preflight(model)
    results = []
    for row in files:
        relative_path = row["relative_path"]
        sidecar = vision_sidecar_path(packet, cohort["cohort_id"], relative_path)
        if sidecar.is_file() and not force:
            results.append(_read_json(sidecar, {}))
            continue
        image = preview_for(packet, relative_path)
        record = {
            "record_type": "laia.photo_record_candidate", "record_version": "0.1",
            "relative_path": relative_path, "source_path": str(image), "model": model,
            "generated_at": utc_now(),
        }
        try:
            raw = run_ollama_image(executable, model, image)
            record.update({"status": "ok", "candidate": parse_vision_json(raw), "raw_response": raw})
        except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
            record.update({"status": "failed", "error": str(exc)})
        _write_json(sidecar, record)
        results.append(record)
    json_path, markdown_path = write_candidate_aggregates(packet, cohort, results)
    return {
        "cohort_id": cohort["cohort_id"], "processed": len(results),
        "successful": sum(row.get("status") == "ok" for row in results),
        "failed": sum(row.get("status") == "failed" for row in results),
        "json_path": str(json_path), "markdown_path": str(markdown_path),
    }


def read_candidates(packet: Path, cohort: dict) -> dict[str, dict]:
    aggregate = _read_json(cohort_dir(packet, cohort["cohort_id"]) / "vision" / "record_candidates.json", {})
    return {
        row.get("relative_path", ""): row.get("candidate", {})
        for row in aggregate.get("candidates", [])
        if row.get("status") == "ok"
    }


def suggest_record_groups(packet: Path, cohort_query: str, group_size: int = 3) -> dict:
    cohort = read_cohort(packet, cohort_query)
    candidates = read_candidates(packet, cohort)
    files = [row["relative_path"] for row in cohort.get("files", [])]
    groups = []
    current = None
    if candidates and all(relative_path in candidates for relative_path in files):
        for relative_path in files:
            candidate = candidates.get(relative_path, {})
            if current is None or (candidate.get("image_type") == "cover_front" and current["files"]):
                current = {"group_id": f"record-{len(groups) + 1:03d}", "files": [], "candidate": {}}
                groups.append(current)
            current["files"].append(relative_path)
            if candidate.get("image_type") == "cover_front":
                current["candidate"] = {
                    key: candidate.get(key, "") for key in ["artist", "title", "confidence"]
                }
    else:
        group_size = max(1, group_size)
        for offset in range(0, len(files), group_size):
            groups.append(
                {
                    "group_id": f"record-{len(groups) + 1:03d}",
                    "files": files[offset : offset + group_size],
                    "candidate": {}, "manual_hint": True,
                }
            )
    root = cohort_dir(packet, cohort["cohort_id"]) / "records"
    json_path = root / "group_suggestions.json"
    markdown_path = root / "group_suggestions.md"
    document = {
        "record_type": "laia.photo_record_group_suggestions", "record_version": "0.1",
        "packet_id": packet.name, "parent_cohort_id": cohort["cohort_id"],
        "generated_at": utc_now(), "groups": groups,
    }
    _write_json(json_path, document)
    lines = ["# Suggested Record Groups", ""]
    for group in groups:
        lines.extend([f"## {group['group_id']}", ""])
        lines.extend(f"- `{value}`" for value in group["files"])
        candidate = group.get("candidate", {})
        if candidate.get("artist") or candidate.get("title"):
            lines.append(f"- Candidate: {candidate.get('artist', '')} - {candidate.get('title', '')}".rstrip(" -"))
        lines.append("")
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return {"groups": groups, "json_path": str(json_path), "markdown_path": str(markdown_path)}


def create_record_cohorts(packet: Path, parent_query: str, limit: Optional[int] = None) -> list[dict]:
    parent = read_cohort(packet, parent_query)
    suggestions = _read_json(
        cohort_dir(packet, parent["cohort_id"]) / "records" / "group_suggestions.json", {}
    )
    groups = suggestions.get("groups", [])
    if not groups:
        raise SystemExit("Record group suggestions not found or empty.")
    if limit is not None:
        groups = groups[:limit]
    created = []
    for group in groups:
        candidate = group.get("candidate", {})
        artist = str(candidate.get("artist", "")).strip()
        title = str(candidate.get("title", "")).strip()
        name = " - ".join(value for value in [artist, title] if value) or group["group_id"]
        child = create_cohort(
            packet, name, subject=parent.get("subject_id"), parent=parent["cohort_id"],
            status="new", cohort_id=group["group_id"],
            description=f"Record group suggested from {parent['cohort_id']}.",
        )
        child, _ = add_files(packet, child["cohort_id"], group["files"], event="record_group_created")
        created.append(child)
    return created


def child_ids_for_parent(packet: Path, parent_id: str) -> set[str]:
    return {
        str(row.get("cohort_id", ""))
        for row in read_cohort_index(packet).get("cohorts", [])
        if row.get("parent_cohort_id") == parent_id
    }


def files_in_child_cohorts(packet: Path, parent_id: str) -> dict[str, str]:
    used = {}
    for child_id in sorted(child_ids_for_parent(packet, parent_id)):
        try:
            child = read_cohort(packet, child_id)
        except SystemExit:
            continue
        for row in child.get("files", []):
            used.setdefault(str(row.get("relative_path", "")), child["cohort_id"])
    return {key: value for key, value in used.items() if key}


def record_pair_suggestions_path(packet: Path, parent_id: str) -> Path:
    return cohort_dir(packet, parent_id) / "records" / "pair_suggestions.json"


def record_pair_suggestions_markdown_path(packet: Path, parent_id: str) -> Path:
    return cohort_dir(packet, parent_id) / "records" / "pair_suggestions.md"


def record_pair_title(child_id: str, prefix: str) -> str:
    suffix = child_id
    if child_id.startswith(f"{prefix}-"):
        suffix = child_id[len(prefix) + 1 :]
    return f"{prefix.replace('-', ' ').title()} {suffix}"


def write_record_pair_suggestions(packet: Path, parent: dict, document: dict) -> tuple[Path, Path]:
    json_path = record_pair_suggestions_path(packet, parent["cohort_id"])
    markdown_path = record_pair_suggestions_markdown_path(packet, parent["cohort_id"])
    _write_json(json_path, document)
    lines = [
        f"# Record Pair Suggestions: {parent['cohort_id']}",
        "",
        f"Packet: {packet.name}",
        f"Mode: {document.get('mode', '')}",
        "Range:",
        f"  start: {document.get('range', {}).get('start') or '-'}",
        f"  end: {document.get('range', {}).get('end') or '-'}",
        "",
        "Suggested pairs:",
    ]
    for suggestion in document.get("suggestions", []):
        files = suggestion.get("files", [])
        lines.extend(
            [
                f"  {suggestion['id']}",
                f"    front: {files[0] if len(files) > 0 else '-'}",
                f"    back:  {files[1] if len(files) > 1 else '-'}",
                f"    status: {suggestion.get('status', '')}",
                "",
            ]
        )
    lines.append("Warnings:")
    warnings = list(document.get("warnings", []))
    for suggestion in document.get("suggestions", []):
        warnings.extend(suggestion.get("warnings", []))
    if warnings:
        lines.extend(f"  {warning}" for warning in warnings)
    else:
        lines.append("  none")
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def suggest_record_pairs(
    packet: Path,
    parent_query: str,
    start: Optional[str] = None,
    end: Optional[str] = None,
    offset: int = 0,
    limit: Optional[int] = None,
    mode: str = "pairs",
    prefix: str = "record",
    start_index: int = 1,
) -> dict:
    if mode != "pairs":
        raise SystemExit(f"Unsupported record pair mode: {mode}")
    parent = read_cohort(packet, parent_query)
    files = selected_files(parent, start=start, end=end)
    if offset:
        files = files[max(0, offset) :]
    paths = [row["relative_path"] for row in files]
    warnings = []
    if len(paths) % 2:
        warnings.append(f"Odd trailing file omitted: {paths[-1]}")
        paths = paths[:-1]
    pair_count = len(paths) // 2
    if limit is not None:
        pair_count = min(pair_count, limit)
    existing_children = child_ids_for_parent(packet, parent["cohort_id"])
    used_files = files_in_child_cohorts(packet, parent["cohort_id"])
    suggestions = []
    for pair_offset in range(pair_count):
        child_number = start_index + pair_offset
        child_id = f"{prefix}-{child_number:03d}"
        front = paths[pair_offset * 2]
        back = paths[pair_offset * 2 + 1]
        item_warnings = []
        status = "new"
        if child_id in existing_children:
            status = "exists"
            item_warnings.append(f"Existing cohort {child_id} will not be overwritten.")
        for relative_path in [front, back]:
            owner = used_files.get(relative_path)
            if owner and owner != child_id:
                status = "blocked"
                item_warnings.append(f"File {relative_path} is already present in child cohort {owner}.")
        suggestions.append(
            {
                "id": child_id,
                "title": record_pair_title(child_id, prefix),
                "files": [front, back],
                "roles": {front: "cover_front", back: "cover_back"},
                "status": status,
                "warnings": item_warnings,
            }
        )
    document = {
        "packet": packet.name,
        "parent_cohort": parent["cohort_id"],
        "mode": mode,
        "range": {"start": start or "", "end": end or ""},
        "suggestions": suggestions,
        "warnings": warnings,
        "generated_at": utc_now(),
    }
    json_path, markdown_path = write_record_pair_suggestions(packet, parent, document)
    return {**document, "json_path": str(json_path), "markdown_path": str(markdown_path)}


def read_record_pair_suggestions(packet: Path, parent_query: str, suggestions_file: Optional[str] = None) -> dict:
    parent = read_cohort(packet, parent_query)
    path = Path(suggestions_file).expanduser() if suggestions_file else record_pair_suggestions_path(packet, parent["cohort_id"])
    document = _read_json(path, {})
    if not document.get("suggestions"):
        raise SystemExit(f"Record pair suggestions not found or empty: {path}")
    return document


def filter_pair_suggestions(suggestions: list[dict], limit: Optional[int] = None, only: Optional[list[str]] = None) -> list[dict]:
    selected = list(suggestions)
    if only:
        allowed = {value.strip() for value in only if value.strip()}
        selected = [item for item in selected if item.get("id") in allowed]
    if limit is not None:
        selected = selected[:limit]
    return selected


def create_record_pair_cohorts(
    packet: Path,
    parent_query: str,
    suggestions_file: Optional[str] = None,
    limit: Optional[int] = None,
    only: Optional[list[str]] = None,
    skip_existing: bool = True,
    force_existing: bool = False,
    mark_ready: bool = False,
    export: bool = False,
    contact_sheets: bool = False,
) -> dict:
    parent = read_cohort(packet, parent_query)
    document = read_record_pair_suggestions(packet, parent["cohort_id"], suggestions_file)
    selected = filter_pair_suggestions(document.get("suggestions", []), limit, only)
    used_files = files_in_child_cohorts(packet, parent["cohort_id"])
    created = []
    skipped = []
    exports = []
    contact_sheet_paths = []
    for suggestion in selected:
        child_id = suggestion["id"]
        existing = child_id in child_ids_for_parent(packet, parent["cohort_id"])
        if existing and skip_existing and not force_existing:
            skipped.append({"id": child_id, "reason": "already exists"})
            continue
        conflict = next(
            (
                (relative_path, owner)
                for relative_path, owner in used_files.items()
                if relative_path in suggestion.get("files", []) and owner != child_id
            ),
            None,
        )
        if conflict:
            skipped.append({"id": child_id, "reason": f"file already in {conflict[1]}", "file": conflict[0]})
            continue
        child = create_cohort(
            packet,
            suggestion.get("title") or child_id,
            subject=parent.get("subject_id"),
            parent=parent["cohort_id"],
            status="new",
            cohort_id=child_id,
            description=f"Record pair split from {parent['cohort_id']}.",
        )
        child, added = add_files(packet, child["cohort_id"], suggestion.get("files", []), event="record_pair_created")
        if mark_ready:
            child = update_cohort(packet, child["cohort_id"], status="ready")
        created.append({"cohort_id": child["cohort_id"], "file_count": len(child.get("files", [])), "added": added})
        for relative_path in child.get("files", []):
            used_files.setdefault(relative_path.get("relative_path", ""), child["cohort_id"])
        if export:
            exports.append({"cohort_id": child["cohort_id"], **export_cohort(packet, child["cohort_id"])})
            child = read_cohort(packet, child["cohort_id"])
        if contact_sheets:
            result = build_contact_sheet_html(packet, child["cohort_id"])
            contact_sheet_paths.append({"cohort_id": child["cohort_id"], "path": result["path"]})
    return {
        "packet": packet.name,
        "parent_cohort": parent["cohort_id"],
        "created": created,
        "skipped": skipped,
        "exports": exports,
        "contact_sheets": contact_sheet_paths,
    }


def confirm_record(
    packet: Path,
    cohort_query: str,
    artist: str,
    title: str,
    label: str = "",
    catalog_number: str = "",
    notes: str = "",
) -> dict:
    cohort = read_cohort(packet, cohort_query)
    metadata = {
        "record_type": "laia.confirmed_record_metadata", "record_version": "0.1",
        "packet_id": packet.name, "cohort_id": cohort["cohort_id"],
        "artist": artist, "title": title, "record_label": label,
        "catalog_number": catalog_number, "notes": notes, "confirmed_at": utc_now(),
    }
    path = cohort_dir(packet, cohort["cohort_id"]) / "record_metadata.json"
    _write_json(path, metadata)
    return {"path": str(path), "metadata": metadata}
