import json
from pathlib import Path
from typing import Optional


EVIDENCE_SOURCE_TYPES = {
    "approved_photo",
    "photo_crop",
    "ocr_candidate",
    "llava_candidate",
    "human_photo_review",
    "physical_inspection",
    "external_catalog",
    "label_photo",
    "matrix_runout_photo",
    "unknown",
}
EVIDENCE_VISIBILITY_VALUES = {
    "clearly_visible",
    "partially_visible",
    "not_readable_in_current_photos",
    "not_photographed",
    "externally_supported",
    "unknown",
}
EVIDENCE_CONFIDENCE_VALUES = {"low", "medium", "high", "confirmed"}
EVIDENCE_FIELDS = {
    "artist",
    "title",
    "label",
    "catalog_number",
    "year",
    "country_or_printing",
    "pressing",
    "matrix_runout",
    "format",
    "spine_text",
    "label_text",
    "back_cover_text",
    "front_cover_text",
}
IDENTITY_FIELDS = [
    "artist",
    "title",
    "label",
    "catalog_number",
    "year",
    "country_or_printing",
    "pressing",
    "matrix_runout",
    "format",
]
CORE_UNCONFIRMED_FIELDS = ["pressing", "matrix_runout"]
PHOTO_SOURCE_TYPES = {"approved_photo", "photo_crop", "human_photo_review", "label_photo", "matrix_runout_photo"}


def registry_module():
    try:
        from projects import registry
    except (ImportError, ModuleNotFoundError):
        from core.projects import registry
    return registry


def sale_items_module():
    try:
        from projects import sale_items
    except (ImportError, ModuleNotFoundError):
        from core.projects import sale_items
    return sale_items


def project_id(identifier: str) -> str:
    return registry_module().find_project(identifier)


def project_folder(identifier: str) -> Path:
    return registry_module().project_folder(project_id(identifier))


def appraisal_root(identifier: str) -> Path:
    return project_folder(identifier) / "appraisal"


def identity_evidence_path(identifier: str) -> Path:
    return appraisal_root(identifier) / "identity_evidence.json"


def identity_evidence_markdown_path(identifier: str) -> Path:
    return appraisal_root(identifier) / "identity_evidence.md"


def read_json(path: Path, default=None):
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {path}: {exc}")


def blank_to_none(value):
    if value in (None, ""):
        return None
    return value


def validate_choice(value: str, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"Invalid {field}: {value}")
    return normalized


def record_identity_from_sale_item(identifier: str) -> dict:
    try:
        item = sale_items_module().load_sale_item(identifier)
    except FileNotFoundError:
        return {}
    metadata = item.get("record_metadata", {})
    return {
        "artist": blank_to_none(metadata.get("artist")),
        "title": blank_to_none(metadata.get("title")),
        "label": blank_to_none(metadata.get("record_label") or item.get("manufacturer")),
        "catalog_number": blank_to_none(metadata.get("catalog_number") or item.get("model")),
        "year": blank_to_none(metadata.get("year")),
        "country_or_printing": blank_to_none(metadata.get("country_or_printing")),
        "pressing": blank_to_none(metadata.get("pressing")),
        "matrix_runout": blank_to_none(metadata.get("matrix_runout")),
        "format": blank_to_none(metadata.get("format") or "LP"),
    }


def latest_field_value(entries: list[dict]) -> Optional[str]:
    confirmed = [
        entry for entry in entries
        if entry.get("confidence") in {"confirmed", "high"} and entry.get("value") not in (None, "")
    ]
    selected = (confirmed or entries)[-1] if entries else {}
    return blank_to_none(selected.get("value"))


def summarize_source_quality(field_evidence: dict) -> dict:
    photo_supported = []
    physical_supported = []
    external_supported = []
    fields_needing_better_photos = []
    for field, entries in field_evidence.items():
        if any(entry.get("source_type") in PHOTO_SOURCE_TYPES for entry in entries):
            photo_supported.append(field)
        if any(entry.get("source_type") == "physical_inspection" for entry in entries):
            physical_supported.append(field)
        if any(entry.get("source_type") == "external_catalog" for entry in entries):
            external_supported.append(field)
        if any(entry.get("visibility") in {"not_readable_in_current_photos", "not_photographed"} for entry in entries):
            fields_needing_better_photos.append(field)
    for field in ["catalog_number", "matrix_runout"]:
        if not field_evidence.get(field) and field not in fields_needing_better_photos:
            fields_needing_better_photos.append(field)
    unconfirmed = [field for field in CORE_UNCONFIRMED_FIELDS if not field_evidence.get(field)]
    return {
        "photo_supported_fields": sorted(set(photo_supported)),
        "physical_inspection_supported_fields": sorted(set(physical_supported)),
        "external_supported_fields": sorted(set(external_supported)),
        "unconfirmed_fields": sorted(set(unconfirmed)),
        "fields_needing_better_photos": sorted(set(fields_needing_better_photos)),
    }


def build_identity_from_evidence(identifier: str, field_evidence: dict) -> dict:
    identity = {
        key: value for key, value in record_identity_from_sale_item(identifier).items()
        if key in IDENTITY_FIELDS and value not in (None, "")
    }
    for field in IDENTITY_FIELDS:
        value = latest_field_value(field_evidence.get(field, []))
        if value is not None:
            identity[field] = value
    return identity


def build_record_identity_evidence(identifier: str, existing: Optional[dict] = None) -> dict:
    project = project_id(identifier)
    item = sale_items_module().load_sale_item(project)
    if str(item.get("category", "")).strip().lower() != "records":
        raise ValueError("Record identity evidence requires a record sale item.")
    existing = existing or {}
    field_evidence = existing.get("field_evidence", {})
    field_evidence = {
        field: entries
        for field, entries in field_evidence.items()
        if field in EVIDENCE_FIELDS and isinstance(entries, list)
    }
    return {
        "project": project,
        "category": "records",
        "identity": build_identity_from_evidence(project, field_evidence),
        "field_evidence": field_evidence,
        "source_quality_summary": summarize_source_quality(field_evidence),
        "generated_at": registry_module().utc_now(),
    }


def read_record_identity_evidence(identifier: str) -> dict:
    path = identity_evidence_path(identifier)
    existing = read_json(path, {}) if path.is_file() else {}
    return build_record_identity_evidence(identifier, existing)


def write_record_identity_evidence(identifier: str, evidence: Optional[dict] = None) -> dict:
    project = project_id(identifier)
    evidence = build_record_identity_evidence(project, evidence or read_json(identity_evidence_path(project), {}))
    evidence["generated_at"] = registry_module().utc_now()
    root = appraisal_root(project)
    root.mkdir(parents=True, exist_ok=True)
    json_path = identity_evidence_path(project)
    md_path = identity_evidence_markdown_path(project)
    registry_module().write_json(json_path, evidence)
    md_path.write_text(render_record_identity_evidence_markdown(evidence), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def add_record_identity_evidence(identifier: str, **values) -> tuple[dict, dict]:
    project = project_id(identifier)
    field = validate_choice(values.get("field"), EVIDENCE_FIELDS, "field")
    source_type = validate_choice(values.get("source_type"), EVIDENCE_SOURCE_TYPES, "source type")
    visibility = validate_choice(values.get("visibility") or "unknown", EVIDENCE_VISIBILITY_VALUES, "visibility")
    confidence = validate_choice(values.get("confidence") or "low", EVIDENCE_CONFIDENCE_VALUES, "confidence")
    value = str(values.get("value") or "").strip()
    if not value:
        raise ValueError("Evidence value is required.")
    evidence = read_record_identity_evidence(project)
    entry = {
        "value": value,
        "source_type": source_type,
        "visibility": visibility,
        "confidence": confidence,
        "note": values.get("note") or "",
        "created_at": registry_module().utc_now(),
    }
    evidence.setdefault("field_evidence", {}).setdefault(field, []).append(entry)
    paths = write_record_identity_evidence(project, evidence)
    return entry, paths


def field_evidence_summary(evidence: dict, field: str) -> Optional[dict]:
    entries = evidence.get("field_evidence", {}).get(field, [])
    if not entries:
        return None
    confirmed = [entry for entry in entries if entry.get("confidence") in {"confirmed", "high"}]
    entry = (confirmed or entries)[-1]
    return {
        "value": entry.get("value"),
        "source_type": entry.get("source_type", "unknown"),
        "visibility": entry.get("visibility", "unknown"),
        "confidence": entry.get("confidence", "low"),
        "note": entry.get("note", ""),
    }


def identity_evidence_summary_lines(evidence: dict) -> list[str]:
    labels = {
        "artist": "Artist",
        "title": "Title",
        "label": "Label",
        "catalog_number": "Catalog number",
        "year": "Year",
        "pressing": "Pressing",
        "matrix_runout": "Matrix/runout",
    }
    lines = []
    for field in ["artist", "title", "label", "catalog_number", "year", "pressing", "matrix_runout"]:
        summary = field_evidence_summary(evidence, field)
        if not summary:
            continue
        detail = f"{summary['confidence']} from {summary['source_type']}"
        if summary.get("visibility"):
            detail += f"; {summary['visibility']}"
        lines.append(f"{labels[field]}: {summary.get('value') or '-'} ({detail})")
    return lines


def render_record_identity_evidence_markdown(evidence: dict) -> str:
    identity = evidence.get("identity", {})
    summary = evidence.get("source_quality_summary", {})
    title_line = " - ".join(value for value in [identity.get("artist"), identity.get("title")] if value) or "-"
    label_line = " ".join(value for value in [identity.get("label"), identity.get("catalog_number")] if value) or "-"
    lines = [
        f"# Record Identity Evidence: {evidence.get('project', '')}",
        "",
        "## Item",
        "",
        f"{title_line}  ",
        label_line,
        "",
        "## Evidence by field",
        "",
        "| Field | Value | Source | Visibility | Confidence | Note |",
        "|---|---|---|---|---|---|",
    ]
    for field in sorted(evidence.get("field_evidence", {})):
        for entry in evidence["field_evidence"][field]:
            note = str(entry.get("note", "")).replace("\n", " ")
            lines.append(
                f"| {field} | {entry.get('value') or '-'} | {entry.get('source_type') or '-'} | "
                f"{entry.get('visibility') or '-'} | {entry.get('confidence') or '-'} | {note} |"
            )
    if not evidence.get("field_evidence"):
        lines.append("| - | - | - | - | - | - |")
    lines.extend(
        [
            "",
            "## Source quality summary",
            "",
            "Photo-supported fields:",
            *[f"- {field}" for field in summary.get("photo_supported_fields", [])],
            *(["- none"] if not summary.get("photo_supported_fields") else []),
            "",
            "Physical-inspection-supported fields:",
            *[f"- {field}" for field in summary.get("physical_inspection_supported_fields", [])],
            *(["- none"] if not summary.get("physical_inspection_supported_fields") else []),
            "",
            "External-supported fields:",
            *[f"- {field}" for field in summary.get("external_supported_fields", [])],
            *(["- none"] if not summary.get("external_supported_fields") else []),
            "",
            "Unconfirmed:",
            *[f"- {field}" for field in summary.get("unconfirmed_fields", [])],
            *(["- none"] if not summary.get("unconfirmed_fields") else []),
            "",
            "Needs better photos:",
            *[f"- {field}" for field in summary.get("fields_needing_better_photos", [])],
            *(["- none"] if not summary.get("fields_needing_better_photos") else []),
            "",
        ]
    )
    return "\n".join(lines)


def print_record_identity_evidence_summary(evidence: dict, paths: dict) -> None:
    identity = evidence.get("identity", {})
    print(f"Record Identity Evidence: {evidence.get('project', '')}")
    print()
    print("Identity:")
    print(f"  Artist: {identity.get('artist') or '-'}")
    print(f"  Title: {identity.get('title') or '-'}")
    print(f"  Label: {identity.get('label') or '-'}")
    print(f"  Catalog number: {identity.get('catalog_number') or '-'}")
    print()
    print("Source quality:")
    summary = evidence.get("source_quality_summary", {})
    print(f"  Photo-supported: {', '.join(summary.get('photo_supported_fields', [])) or '-'}")
    print(f"  Physical inspection: {', '.join(summary.get('physical_inspection_supported_fields', [])) or '-'}")
    print(f"  Needs better photos: {', '.join(summary.get('fields_needing_better_photos', [])) or '-'}")
    print()
    print("Wrote:")
    print(f"  {paths['json']}")
    print(f"  {paths['md']}")


def command_record_identity_evidence(args):
    try:
        evidence = read_record_identity_evidence(args.identifier)
        paths = write_record_identity_evidence(args.identifier, evidence)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    if getattr(args, "json", False):
        print(json.dumps(evidence, indent=2))
    else:
        print_record_identity_evidence_summary(evidence, paths)


def command_record_identity_evidence_add(args):
    values = vars(args).copy()
    values.pop("identifier", None)
    values.pop("func", None)
    values.pop("json", None)
    try:
        entry, paths = add_record_identity_evidence(args.identifier, **values)
    except (FileNotFoundError, ValueError) as exc:
        raise SystemExit(str(exc))
    if getattr(args, "json", False):
        print(json.dumps({"entry": entry, "paths": paths}, indent=2))
    else:
        print(f"Added record identity evidence: {args.field}")
        print("Wrote:")
        print(f"  {paths['json']}")
        print(f"  {paths['md']}")


def command_record_identity_evidence_export(args):
    command_record_identity_evidence(args)


def register_record_identity_evidence_subcommands(projects_sub) -> None:
    evidence_p = projects_sub.add_parser("record-identity-evidence", help="Show record identity evidence provenance")
    evidence_p.add_argument("identifier")
    evidence_p.add_argument("--json", action="store_true")
    evidence_p.set_defaults(func=command_record_identity_evidence)

    add_p = projects_sub.add_parser("record-identity-evidence-add", help="Add field-level record identity evidence")
    add_p.add_argument("identifier")
    add_p.add_argument("--field", choices=sorted(EVIDENCE_FIELDS), required=True)
    add_p.add_argument("--value", required=True)
    add_p.add_argument("--source-type", choices=sorted(EVIDENCE_SOURCE_TYPES), required=True)
    add_p.add_argument("--visibility", choices=sorted(EVIDENCE_VISIBILITY_VALUES), default="unknown")
    add_p.add_argument("--confidence", choices=sorted(EVIDENCE_CONFIDENCE_VALUES), default="low")
    add_p.add_argument("--note", default="")
    add_p.add_argument("--json", action="store_true")
    add_p.set_defaults(func=command_record_identity_evidence_add)

    export_p = projects_sub.add_parser("record-identity-evidence-export", help="Write record identity evidence files")
    export_p.add_argument("identifier")
    export_p.add_argument("--json", action="store_true")
    export_p.set_defaults(func=command_record_identity_evidence_export)
