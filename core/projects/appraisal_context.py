import json
from pathlib import Path
from typing import Optional


RECORD_PHOTO_ROLES = [
    "cover_front",
    "cover_back",
    "label_a",
    "label_b",
    "vinyl_a",
    "vinyl_b",
    "spine",
    "matrix",
    "defect",
    "detail",
]


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


def blank_to_none(value):
    if value in (None, ""):
        return None
    return value


def display_missing(value: Optional[str]) -> str:
    return str(value) if value not in (None, "") else "missing"


def appraisal_root(project_id: str) -> Path:
    return registry_module().project_folder(project_id) / "appraisal"


def load_optional_sale_item(project_id: str) -> dict:
    sale_items = sale_items_module()
    try:
        return sale_items.load_sale_item(project_id)
    except FileNotFoundError:
        return {}


def load_optional_photo_edit(project_id: str) -> dict:
    sale_items = sale_items_module()
    return sale_items.migrate_edit_manifest(sale_items.read_json(sale_items.edit_manifest_path(project_id), {}))


def category_profile(sale_item: dict) -> str:
    category = str(sale_item.get("category", "")).strip().lower()
    if category == "records":
        return "records"
    return "generic"


def role_coverage(photo_edit: dict, roles: list[str]) -> dict:
    images = photo_edit.get("images", []) if photo_edit else []
    coverage = {}
    for role in roles:
        role_images = [image for image in images if image.get("role") == role]
        approved = [image for image in role_images if image.get("review_status") == "approved"]
        if len(approved) > 1:
            status = "duplicate"
        elif len(approved) == 1:
            status = "approved"
        elif role_images:
            status = "unapproved"
        else:
            status = "missing"
        files = [
            image.get("work_filename") or image.get("filename", "")
            for image in (approved or role_images)
            if image.get("work_filename") or image.get("filename")
        ]
        coverage[role] = {"status": status, "files": files}
    return coverage


def approved_photo_count(photo_edit: dict) -> int:
    return sum(1 for image in photo_edit.get("images", []) if image.get("review_status") == "approved")


def record_listing_readiness(item: dict, coverage: dict) -> dict:
    metadata = item.get("record_metadata", {})
    pricing = item.get("pricing", {})
    front = coverage.get("cover_front", {}).get("status") == "approved"
    back = coverage.get("cover_back", {}).get("status") == "approved"
    if front and back:
        photo_evidence = "ready_basic"
    elif front:
        photo_evidence = "partial"
    else:
        photo_evidence = "insufficient"
    overall_condition = item.get("condition", {}).get("overall")
    condition_ready = (
        overall_condition not in (None, "", "unassessed")
        or bool(metadata.get("media_condition"))
        or bool(metadata.get("sleeve_condition"))
    )
    readiness = {
        "photo_evidence": photo_evidence,
        "condition": "ready" if condition_ready else "missing",
        "price": "ready" if pricing.get("asking_price") is not None else "missing",
        "description": "ready" if item.get("description") else "missing",
    }
    readiness["overall"] = (
        "ready_basic"
        if all(
            [
                readiness["photo_evidence"] == "ready_basic",
                readiness["condition"] == "ready",
                readiness["price"] == "ready",
                readiness["description"] == "ready",
            ]
        )
        else "not_ready"
    )
    return readiness


def record_known_claims(identity: dict, coverage: dict) -> list[str]:
    claims = []
    if identity.get("artist") and identity.get("title"):
        claims.append("Artist and title confirmed by human review from front/back photos.")
    if coverage.get("cover_front", {}).get("status") == "approved":
        claims.append("Front cover photo approved.")
    if coverage.get("cover_back", {}).get("status") == "approved":
        claims.append("Back cover photo approved.")
    return claims


def record_unverified_claims(identity: dict, condition: dict, item: dict) -> list[str]:
    metadata = item.get("record_metadata", {})
    claims = []
    if not identity.get("pressing"):
        claims.append("Specific pressing/version is not confirmed.")
    if not identity.get("matrix_runout"):
        claims.append("Matrix/runout is not documented.")
    if not condition.get("media_condition"):
        claims.append("Media condition is not graded.")
    if not condition.get("sleeve_condition"):
        claims.append("Sleeve condition is not graded.")
    if not metadata.get("play_tested"):
        claims.append("Playback condition is not tested.")
    claims.append("Completeness such as inserts/posters is not confirmed.")
    return claims


def record_safe_listing_language(condition: dict) -> list[str]:
    safe = ["Used vinyl record."]
    if condition.get("visual_grade_only"):
        safe.append("Visual grade only unless otherwise noted.")
    safe.append("See photos for sleeve condition.")
    if not condition.get("play_tested"):
        safe.append("Playback not tested.")
    return safe


def record_avoid_claiming(identity: dict, condition: dict) -> list[str]:
    avoid = []
    if not identity.get("pressing") or not identity.get("catalog_number") or not identity.get("matrix_runout"):
        avoid.append("Do not claim first pressing without confirmation.")
    if not condition.get("media_condition") or not condition.get("sleeve_condition"):
        avoid.append("Do not claim near mint or excellent condition without grading evidence.")
    if not condition.get("play_tested"):
        avoid.append("Do not claim playback quality unless play-tested.")
    avoid.append("Do not claim complete inserts/posters unless documented.")
    return avoid


def record_next_steps(identity: dict, condition: dict, item: dict, coverage: dict) -> list[dict]:
    steps = []
    if not condition.get("media_condition") or not condition.get("sleeve_condition"):
        steps.append({"priority": "high", "task": "Add media and sleeve condition."})
    if item.get("pricing", {}).get("asking_price") is None:
        steps.append({"priority": "high", "task": "Choose asking price after comparable research."})
    if not identity.get("label") or not identity.get("catalog_number"):
        steps.append({"priority": "medium", "task": "Add label/catalog number if visible."})
    collector_roles = ["label_a", "label_b", "vinyl_a", "vinyl_b", "matrix"]
    if any(coverage.get(role, {}).get("status") == "missing" for role in collector_roles):
        steps.append({"priority": "medium", "task": "Capture label/vinyl/matrix photos if collector pricing matters."})
    return steps


def build_record_appraisal_context(project: dict, sale_item: dict, photo_edit: dict) -> dict:
    metadata = sale_item.get("record_metadata", {})
    identity = {
        "artist": blank_to_none(metadata.get("artist") or sale_item.get("artist")),
        "title": blank_to_none(metadata.get("title") or sale_item.get("title")),
        "label": blank_to_none(metadata.get("record_label") or sale_item.get("manufacturer")),
        "catalog_number": blank_to_none(metadata.get("catalog_number") or sale_item.get("model")),
        "pressing": blank_to_none(metadata.get("pressing")),
        "matrix_runout": blank_to_none(metadata.get("matrix_runout")),
    }
    coverage = role_coverage(photo_edit, RECORD_PHOTO_ROLES)
    condition = {
        "condition": blank_to_none(
            None
            if sale_item.get("condition", {}).get("overall") == "unassessed"
            else sale_item.get("condition", {}).get("overall")
        ),
        "media_condition": blank_to_none(metadata.get("media_condition")),
        "sleeve_condition": blank_to_none(metadata.get("sleeve_condition")),
        "grading_note": blank_to_none(metadata.get("grading_note")),
        "play_tested": bool(metadata.get("play_tested")),
        "visual_grade_only": not bool(metadata.get("play_tested")),
    }
    readiness = record_listing_readiness(sale_item, coverage)
    known_claims = record_known_claims(identity, coverage)
    unverified_claims = record_unverified_claims(identity, condition, sale_item)
    return {
        "project": project.get("project_id", ""),
        "category": sale_item.get("category", ""),
        "profile": "records",
        "identity": identity,
        "evidence": {
            "photo_coverage": coverage,
            "approved_photo_count": approved_photo_count(photo_edit),
            "minimum_listing_photos_met": (
                coverage.get("cover_front", {}).get("status") == "approved"
                and coverage.get("cover_back", {}).get("status") == "approved"
            ),
        },
        "condition": condition,
        "confirmed_facts": known_claims,
        "photo_evidence": coverage,
        "condition_grading_notes": condition,
        "unknowns": unverified_claims,
        "known_claims": known_claims,
        "unverified_claims": unverified_claims,
        "buyer_expectations": [
            "Record buyers care about pressing identity, media grade, sleeve grade, label/catalog details, and visible defects.",
            "Visual grade only should be disclosed unless playback has been tested.",
            "Front/back cover photos are enough for a basic local listing but not enough for high-confidence collector pricing.",
        ],
        "safe_listing_language": record_safe_listing_language(condition),
        "avoid_claiming": record_avoid_claiming(identity, condition),
        "next_steps": record_next_steps(identity, condition, sale_item, coverage),
        "listing_readiness": readiness,
    }


def build_generic_appraisal_context(project: dict, sale_item: dict, photo_edit: dict) -> dict:
    category = sale_item.get("category") or "unknown"
    images = photo_edit.get("images", []) if photo_edit else []
    roles = sorted({image.get("role") for image in images if image.get("role")})
    coverage = role_coverage(photo_edit, roles)
    return {
        "project": project.get("project_id", ""),
        "category": category,
        "profile": "generic",
        "identity": {
            "title": blank_to_none(sale_item.get("title") or project.get("name")),
            "manufacturer": blank_to_none(sale_item.get("manufacturer")),
            "model": blank_to_none(sale_item.get("model")),
        },
        "evidence": {
            "photo_coverage": coverage,
            "approved_photo_count": approved_photo_count(photo_edit),
        },
        "known_claims": ["Sale item metadata exists."] if sale_item else [],
        "unverified_claims": ["Category-specific appraisal rules are not configured."],
        "safe_listing_language": ["Used item."],
        "avoid_claiming": ["Do not claim condition, completeness, or functionality beyond documented evidence."],
        "next_steps": [{"priority": "medium", "task": "Add category-specific condition and pricing details."}],
        "listing_readiness": {
            "photo_evidence": "ready" if approved_photo_count(photo_edit) else "missing",
            "condition": "ready" if sale_item.get("condition", {}).get("overall") not in (None, "", "unassessed") else "missing",
            "price": "ready" if sale_item.get("pricing", {}).get("asking_price") is not None else "missing",
            "description": "ready" if sale_item.get("description") else "missing",
            "overall": "not_ready",
        },
    }


def build_appraisal_context(project_id_or_identifier: str) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    project = registry.load_project(project_id)
    sale_item = load_optional_sale_item(project_id)
    photo_edit = load_optional_photo_edit(project_id)
    if category_profile(sale_item) == "records":
        return build_record_appraisal_context(project, sale_item, photo_edit)
    return build_generic_appraisal_context(project, sale_item, photo_edit)


def render_appraisal_context_markdown(context: dict) -> str:
    if context.get("profile") == "records":
        return render_record_appraisal_context_markdown(context)
    return render_generic_appraisal_context_markdown(context)


def render_record_appraisal_context_markdown(context: dict) -> str:
    identity = context.get("identity", {})
    condition = context.get("condition", {})
    readiness = context.get("listing_readiness", {})
    coverage = context.get("evidence", {}).get("photo_coverage", {})
    functional = "not applicable" if context.get("category") == "records" else ""
    high_steps = [step["task"] for step in context.get("next_steps", []) if step.get("priority") == "high"]
    medium_steps = [step["task"] for step in context.get("next_steps", []) if step.get("priority") == "medium"]
    lines = [
        f"# Appraisal Context: {context.get('project', '')}",
        "",
        "## Item",
        "",
        f"{identity.get('artist') or '-'} - {identity.get('title') or '-'}",
        "",
        f"Category: {context.get('category', '')}  ",
        f"Functional status: {functional}",
        "",
        "## Confirmed facts",
        *(f"- {claim}" for claim in context.get("known_claims", [])),
        *(["- none"] if not context.get("known_claims") else []),
        "",
        "## Photo evidence",
        "",
        "| Role | Status | Files |",
        "|---|---|---|",
    ]
    for role in ["cover_front", "cover_back", "label_a", "label_b", "vinyl_a", "vinyl_b", "matrix"]:
        row = coverage.get(role, {"status": "missing", "files": []})
        files = ", ".join(row.get("files", [])) if row.get("files") else "-"
        lines.append(f"| {role} | {row.get('status', 'missing')} | {files} |")
    lines.extend(
        [
            "",
            "## Condition",
            "",
            f"Media condition: {display_missing(condition.get('media_condition'))}  ",
            f"Sleeve condition: {display_missing(condition.get('sleeve_condition'))}  ",
            f"Grading note: {display_missing(condition.get('grading_note'))}  ",
            f"Playback tested: {'yes' if condition.get('play_tested') else 'no'}  ",
            f"Visual grade only: {'yes' if condition.get('visual_grade_only') else 'no'}",
            "",
            "## Safe claims",
            *(f"- {claim}" for claim in context.get("safe_listing_language", [])),
            "",
            "## Do not claim yet",
            *(f"- {claim}" for claim in context.get("avoid_claiming", [])),
            "",
            "## Buyer expectations",
            "",
            " ".join(context.get("buyer_expectations", [])),
            "",
            "## Recommended next steps",
            "",
            "High:",
            *(f"- {task}" for task in high_steps),
            *(["- none"] if not high_steps else []),
            "",
            "Medium:",
            *(f"- {task}" for task in medium_steps),
            *(["- none"] if not medium_steps else []),
            "",
            "## Listing readiness",
            "",
            f"Photo evidence: {readiness.get('photo_evidence', '')}  ",
            f"Condition: {readiness.get('condition', '')}  ",
            f"Price: {readiness.get('price', '')}  ",
            f"Description: {readiness.get('description', '')}  ",
            f"Overall: {readiness.get('overall', '')}",
            "",
        ]
    )
    return "\n".join(lines)


def render_generic_appraisal_context_markdown(context: dict) -> str:
    readiness = context.get("listing_readiness", {})
    return "\n".join(
        [
            f"# Appraisal Context: {context.get('project', '')}",
            "",
            "## Item",
            "",
            f"Category: {context.get('category', '')}",
            f"Profile: {context.get('profile', '')}",
            "",
            "## Listing readiness",
            "",
            f"Photo evidence: {readiness.get('photo_evidence', '')}",
            f"Condition: {readiness.get('condition', '')}",
            f"Price: {readiness.get('price', '')}",
            f"Description: {readiness.get('description', '')}",
            f"Overall: {readiness.get('overall', '')}",
            "",
        ]
    )


def write_appraisal_context(project_id_or_identifier: str, context: Optional[dict] = None) -> dict:
    registry = registry_module()
    project_id = registry.find_project(project_id_or_identifier)
    context = context or build_appraisal_context(project_id)
    root = appraisal_root(project_id)
    root.mkdir(parents=True, exist_ok=True)
    json_path = root / "context.json"
    md_path = root / "context.md"
    registry.write_json(json_path, context)
    md_path.write_text(render_appraisal_context_markdown(context), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def context_with_paths(project_id_or_identifier: str) -> tuple[dict, dict]:
    context = build_appraisal_context(project_id_or_identifier)
    paths = write_appraisal_context(project_id_or_identifier, context)
    return context, paths


def print_appraisal_context_summary(context: dict, paths: dict) -> None:
    print(f"Appraisal Context: {context.get('project', '')}")
    print(f"Category: {context.get('category', '')}")
    print(f"Profile: {context.get('profile', '')}")
    print()
    if context.get("profile") == "records":
        print_record_summary(context)
    else:
        readiness = context.get("listing_readiness", {})
        print("Listing readiness:")
        for key in ["photo_evidence", "condition", "price", "description", "overall"]:
            print(f"  {key.replace('_', ' ').title()}: {readiness.get(key, '')}")
    print()
    print("Wrote:")
    print(f"  {paths['json']}")
    print(f"  {paths['md']}")


def print_record_summary(context: dict) -> None:
    identity = context.get("identity", {})
    condition = context.get("condition", {})
    readiness = context.get("listing_readiness", {})
    coverage = context.get("evidence", {}).get("photo_coverage", {})
    print("Identity:")
    print(f"  Artist: {identity.get('artist') or '-'}")
    print(f"  Title: {identity.get('title') or '-'}")
    print(f"  Label: {identity.get('label') or '-'}")
    print(f"  Catalog number: {identity.get('catalog_number') or '-'}")
    print()
    print("Evidence:")
    for role in ["cover_front", "cover_back", "label_a", "label_b", "vinyl_a", "vinyl_b", "matrix"]:
        print(f"  {role}: {coverage.get(role, {}).get('status', 'missing')}")
    print()
    print("Condition:")
    print(f"  Media: {display_missing(condition.get('media_condition'))}")
    print(f"  Sleeve: {display_missing(condition.get('sleeve_condition'))}")
    print(f"  Playback tested: {'yes' if condition.get('play_tested') else 'no'}")
    print(f"  Visual grade only: {'yes' if condition.get('visual_grade_only') else 'no'}")
    print()
    print("Listing readiness:")
    print(f"  Photo evidence: {readiness.get('photo_evidence', '')}")
    print(f"  Condition: {readiness.get('condition', '')}")
    print(f"  Price: {readiness.get('price', '')}")
    print(f"  Description: {readiness.get('description', '')}")
    print(f"  Overall: {readiness.get('overall', '')}")
    print()
    print("Next steps:")
    for step in context.get("next_steps", []):
        print(f"  {step.get('priority', '').upper()} {step.get('task', '')}")


def command_appraisal_context(args):
    context, paths = context_with_paths(args.identifier)
    if args.json:
        print(json.dumps(context, indent=2))
    else:
        print_appraisal_context_summary(context, paths)


def command_appraisal_context_export(args):
    context, paths = context_with_paths(args.identifier)
    if getattr(args, "json", False):
        print(json.dumps({"context": context, "paths": paths}, indent=2))
    else:
        print("Appraisal context exported:")
        print(f"  {paths['json']}")
        print(f"  {paths['md']}")


def register_appraisal_context_subcommands(projects_sub) -> None:
    context_p = projects_sub.add_parser("appraisal-context", help="Build appraisal context for a project")
    context_p.add_argument("identifier")
    context_p.add_argument("--json", action="store_true")
    context_p.set_defaults(func=command_appraisal_context)

    export_p = projects_sub.add_parser("appraisal-context-export", help="Write appraisal context files")
    export_p.add_argument("identifier")
    export_p.add_argument("--json", action="store_true")
    export_p.set_defaults(func=command_appraisal_context_export)
