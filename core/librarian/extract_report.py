import json
from collections import Counter
from typing import Any

try:
    from librarian.catalog import catalog_path, load_catalog_records
    from librarian.export import (
        correction_values,
        load_correction_for_record,
        load_extract_for_record,
        select_export_records,
    )
except ModuleNotFoundError:
    from core.librarian.catalog import catalog_path, load_catalog_records
    from core.librarian.export import (
        correction_values,
        load_correction_for_record,
        load_extract_for_record,
        select_export_records,
    )


REPORT_FIELDS = [
    "merchant",
    "transaction_date",
    "transaction_time",
    "subtotal",
    "tax",
    "tip",
    "total",
    "payment_method",
    "last_four",
    "currency",
]


def is_filled(value: Any) -> bool:
    return value is not None and str(value).strip() != ""


def review_reasons(fields: dict[str, Any], warnings: list[str]) -> list[str]:
    reasons = []
    for field in ("merchant", "transaction_date", "total"):
        if not is_filled(fields.get(field)):
            reasons.append(f"{field} missing")
    if warnings:
        reasons.append("warnings present")
    confidence = fields.get("confidence")
    if confidence is not None:
        try:
            if float(confidence) < 0.70:
                reasons.append("confidence below 0.70")
        except (TypeError, ValueError):
            pass
    return reasons


def merged_fields(
    fields: dict[str, Any],
    correction: dict[str, Any],
    *,
    apply_corrections: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    merged = dict(fields)
    corrected_values, corrected_fields = correction_values(correction)
    if apply_corrections:
        merged.update(corrected_values)
    else:
        corrected_fields = []
    return merged, corrected_fields


def unresolved_warnings(
    warnings: list[str],
    fields: dict[str, Any],
    corrected_fields: list[str],
) -> list[str]:
    unresolved = []
    for warning in warnings:
        normalized = warning.strip().lower()
        if (
            normalized == "total not found"
            and "total" in corrected_fields
            and is_filled(fields.get("total"))
        ):
            continue
        if (
            normalized == "transaction_date not found"
            and "transaction_date" in corrected_fields
            and is_filled(fields.get("transaction_date"))
        ):
            continue
        unresolved.append(warning)
    return unresolved


def empty_completeness() -> dict[str, dict[str, int]]:
    return {field: {"filled": 0, "total": 0} for field in REPORT_FIELDS}


def count_completeness(completeness: dict[str, dict[str, int]], fields: dict[str, Any]) -> None:
    for field in REPORT_FIELDS:
        completeness[field]["total"] += 1
        if is_filled(fields.get(field)):
            completeness[field]["filled"] += 1


def build_extract_report(
    records: list[dict[str, Any]],
    filters: dict[str, Any],
    *,
    use_corrections: bool = True,
) -> dict[str, Any]:
    raw_completeness = empty_completeness()
    corrected_completeness = empty_completeness()
    warning_counts: Counter[str] = Counter()
    needs_review = []
    corrections = []
    corrections_found = 0
    extracts_found = 0
    missing_extracts = 0
    invalid_extracts = 0

    for record in records:
        extraction, status = load_extract_for_record(record)
        if status == "missing":
            missing_extracts += 1
            continue
        if status == "invalid":
            invalid_extracts += 1
            continue

        extracts_found += 1
        extraction = extraction or {}
        fields = dict(extraction.get("fields") or {})
        warnings = [str(warning) for warning in (extraction.get("warnings") or [])]
        correction = load_correction_for_record(record)
        corrected_values, correction_fields = correction_values(correction)
        if correction_fields:
            corrections_found += 1
            corrections.append({
                "packet_id": record.get("packet_id"),
                "fields": correction_fields,
                "changes": correction.get("corrections") or {},
                "source_packet_dir": record.get("source_packet_dir"),
            })

        corrected_fields, corrected_field_names = merged_fields(
            fields,
            correction,
            apply_corrections=True,
        )
        review_fields = corrected_fields if use_corrections else fields
        review_warnings = (
            unresolved_warnings(warnings, corrected_fields, corrected_field_names)
            if use_corrections
            else warnings
        )

        count_completeness(raw_completeness, fields)
        count_completeness(corrected_completeness, corrected_fields)
        for warning in warnings:
            warning_counts[warning] += 1

        reasons = review_reasons(review_fields, review_warnings)
        if reasons:
            needs_review.append({
                "packet_id": record.get("packet_id"),
                "missing": [
                    field for field in ("merchant", "transaction_date", "total")
                    if not is_filled(review_fields.get(field))
                ],
                "warnings": review_warnings,
                "confidence": review_fields.get("confidence"),
                "reasons": reasons,
                "source_packet_dir": record.get("source_packet_dir"),
            })

    return {
        "filters": filters,
        "selected": len(records),
        "extracts_found": extracts_found,
        "missing_extracts": missing_extracts,
        "invalid_extracts": invalid_extracts,
        "corrections_found": corrections_found,
        "raw_field_completeness": raw_completeness,
        "corrected_field_completeness": corrected_completeness,
        "field_completeness": corrected_completeness,
        "corrections": corrections,
        "warnings": [
            {"warning": warning, "count": count}
            for warning, count in warning_counts.most_common()
        ],
        "needs_review": needs_review,
    }


def report_from_args(args) -> dict[str, Any]:
    limit_value = getattr(args, "limit", None)
    limit = int(limit_value) if limit_value is not None else None
    filters = {
        "project": getattr(args, "project", "") or "",
        "category": getattr(args, "category", "") or "",
        "limit": limit,
        "raw": bool(getattr(args, "raw", False)),
    }
    records = select_export_records(
        load_catalog_records(catalog_path()),
        project=filters["project"],
        category=filters["category"],
        limit=limit,
    )
    return build_extract_report(records, filters, use_corrections=not filters["raw"])


def print_report(report: dict[str, Any]) -> None:
    filters = report.get("filters") or {}
    print("\nLAIA Librarian Extract Report\n")
    if filters.get("project"):
        print(f"Project: {filters.get('project')}")
    if filters.get("category"):
        print(f"Category: {filters.get('category')}")
    print(f"Selected: {report['selected']}")
    print(f"Extracts found: {report['extracts_found']}")
    print(f"Missing extracts: {report['missing_extracts']}")
    print(f"Invalid extracts: {report['invalid_extracts']}")
    print(f"Corrections found: {report.get('corrections_found', 0)}")
    print("\nRaw Field Completeness:")
    for field in REPORT_FIELDS:
        item = report["raw_field_completeness"][field]
        print(f"  {field:<18} {item['filled']}/{item['total']}")

    print("\nCorrected Field Completeness:")
    for field in REPORT_FIELDS:
        item = report["corrected_field_completeness"][field]
        print(f"  {field:<18} {item['filled']}/{item['total']}")

    print("\nCorrections:")
    if report.get("corrections"):
        for item in report["corrections"]:
            print(f"  {item.get('packet_id')}")
            for field, change in (item.get("changes") or {}).items():
                if not isinstance(change, dict):
                    continue
                print(f"    {field}: {change.get('original')} -> {change.get('corrected')}")
    else:
        print("  none")

    print("\nWarnings:")
    if report["warnings"]:
        for item in report["warnings"]:
            print(f"  {item['count']}  {item['warning']}")
    else:
        print("  none")

    print(f"\nNeeds Review: {len(report['needs_review'])}")
    for index, item in enumerate(report["needs_review"][:20], start=1):
        missing = ", ".join(item.get("missing") or []) or "none"
        warnings = "; ".join(item.get("warnings") or []) or "none"
        print("")
        print(f"{index}. {item.get('packet_id')}")
        print(f"   Missing: {missing}")
        print(f"   Warnings: {warnings}")
        print(f"   Source: {item.get('source_packet_dir')}")
    print("")


def command_extract_report(args) -> None:
    report = report_from_args(args)
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2) + "\n")
        return
    print_report(report)
