import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.catalog import catalog_path, latest_catalog_record, load_catalog_records
    from librarian.summarize import load_json, optional_json
except ModuleNotFoundError:
    from core.librarian.catalog import catalog_path, latest_catalog_record, load_catalog_records
    from core.librarian.summarize import load_json, optional_json


SUPPORTED_CATEGORIES = {"receipt", "financial"}
EXTRACTOR = "receipt-regex-v0"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def amount_from_line(line: str) -> Optional[str]:
    matches = re.findall(r"(?<!\d)(?:\$?\s*)(\d+\.\d{2})(?!\d)", line)
    return matches[-1] if matches else None


def all_amounts(text: str) -> list[str]:
    return re.findall(r"(?<!\d)(?:\$?\s*)(\d+\.\d{2})(?!\d)", text)


def find_amount_by_keywords(lines: list[str], keywords: tuple[str, ...]) -> Optional[str]:
    for line in reversed(lines):
        lower = line.lower()
        if any(keyword in lower for keyword in keywords):
            amount = amount_from_line(line)
            if amount:
                return amount
    return None


def find_date(text: str) -> Optional[str]:
    patterns = [
        r"\b\d{4}-\d{2}-\d{2}\b",
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        r"\b\d{1,2}/\d{1,2}/\d{2}\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    return None


def find_time(text: str) -> Optional[str]:
    match = re.search(r"\b\d{1,2}:\d{2}(?:\s*[AP]M)?\b", text, flags=re.IGNORECASE)
    return match.group(0) if match else None


def find_payment_method(text: str) -> Optional[str]:
    lower = text.lower()
    methods = [
        ("mastercard", "mastercard"),
        ("visa", "visa"),
        ("amex", "amex"),
        ("debit", "debit"),
        ("credit", "credit"),
        ("cash", "cash"),
        ("check", "check"),
    ]
    for needle, value in methods:
        if needle in lower:
            return value
    return None


def find_last_four(text: str) -> Optional[str]:
    patterns = [
        r"\*{2,}\s*(\d{4})\b",
        r"\bx\s*(\d{4})\b",
        r"\bending in\s+(\d{4})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def find_phone(text: str) -> Optional[str]:
    match = re.search(r"\b(?:\(\d{3}\)\s*|\d{3}[-. ])\d{3}[-. ]\d{4}\b", text)
    return match.group(0) if match else None


def find_address(lines: list[str]) -> Optional[str]:
    suffixes = r"st|street|ave|avenue|blvd|road|rd|dr|drive|way|ln"
    pattern = re.compile(rf"\b\d{{2,6}}\s+.+\b(?:{suffixes})\.?\b", re.IGNORECASE)
    for line in lines:
        text = line.strip()
        if pattern.search(text):
            return text
    return None


def useful_merchant_line(line: str) -> bool:
    text = line.strip()
    if not text:
        return False
    lower = text.lower()
    if re.fullmatch(r"[\d\s:/.-]+", text):
        return False
    if amount_from_line(text):
        return False
    if find_date(text) or find_time(text):
        return False
    if re.search(r"\b(?:visa|mastercard|amex|debit|credit|cash|check)\b", lower):
        return False
    if re.fullmatch(r"[xX*\d\s-]{4,}", text):
        return False
    return True


def find_merchant(lines: list[str]) -> Optional[str]:
    for line in lines:
        text = line.strip()
        if useful_merchant_line(text):
            return text
    return None


def confidence_for(fields: dict[str, Any], warnings: list[str]) -> float:
    score = 0.2
    for key in ("merchant", "transaction_date", "total", "payment_method"):
        if fields.get(key):
            score += 0.18
    if fields.get("raw_amounts_found"):
        score += 0.08
    if warnings:
        score -= min(0.2, len(warnings) * 0.05)
    return round(max(0.0, min(1.0, score)), 2)


def extract_receipt_fields(text: str, preview_limit: int = 1000) -> tuple[dict[str, Any], list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    raw_amounts = all_amounts(text)
    warnings = []
    total = find_amount_by_keywords(lines, ("total", "amount", "sale", "purchase", "balance"))
    tax = find_amount_by_keywords(lines, ("tax",))
    tip = find_amount_by_keywords(lines, ("tip", "gratuity"))

    fields: dict[str, Any] = {
        "merchant": find_merchant(lines),
        "transaction_date": find_date(text),
        "transaction_time": find_time(text),
        "subtotal": find_amount_by_keywords(lines, ("subtotal", "sub total")),
        "tax": tax,
        "tip": tip,
        "total": total,
        "payment_method": find_payment_method(text),
        "last_four": find_last_four(text),
        "address": find_address(lines),
        "phone": find_phone(text),
        "currency": "USD" if raw_amounts else None,
        "raw_amounts_found": raw_amounts,
        "source_text_preview": text.strip()[:preview_limit],
    }

    for key in ("merchant", "transaction_date", "total"):
        if not fields.get(key):
            warnings.append(f"{key} not found")

    fields["confidence"] = confidence_for(fields, warnings)
    return fields, warnings


def category_for(record: dict[str, Any], packet_dir: Path) -> str:
    final = optional_json(packet_dir / "final" / "final.json") or {}
    classification = optional_json(packet_dir / "classify" / "classification.json") or {}
    return str(
        final.get("approved_category")
        or record.get("approved_category")
        or record.get("category")
        or classification.get("primary_category")
        or ""
    ).lower()


def build_extraction(record: dict[str, Any]) -> dict[str, Any]:
    packet_dir = Path(str(record.get("source_packet_dir") or "")).expanduser()
    category = category_for(record, packet_dir)
    if category not in SUPPORTED_CATEGORIES:
        raise SystemExit("Extraction currently supports receipt and financial packets only.")

    text_path = packet_dir / "output" / "scan.txt"
    if not text_path.exists():
        raise SystemExit("No OCR text found for extraction.")
    text = read_text(text_path).strip()
    if not text:
        raise SystemExit("No OCR text found for extraction.")

    packet = optional_json(packet_dir / "packet.json") or {}
    summary = optional_json(packet_dir / "summary" / "summary.json") or {}
    fields, warnings = extract_receipt_fields(text)

    return {
        "packet_id": record.get("packet_id"),
        "packet_dir": str(packet_dir),
        "category": category,
        "extractor": EXTRACTOR,
        "extracted_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "packet_type": packet.get("packet_type") or record.get("packet_type"),
        "project": packet.get("project") or record.get("project"),
        "summary_available": bool(summary),
        "fields": fields,
        "warnings": warnings,
    }


def markdown_extraction(extraction: dict[str, Any]) -> str:
    fields = extraction.get("fields") or {}
    warnings = extraction.get("warnings") or []
    warning_text = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- none"
    payment = fields.get("payment_method") or "unknown"
    if fields.get("last_four"):
        payment = f"{payment} ending {fields.get('last_four')}"
    return (
        "# LAIA Receipt Extraction\n\n"
        f"Packet ID: {extraction.get('packet_id')}\n\n"
        f"Category: {extraction.get('category')}\n\n"
        f"Merchant: {fields.get('merchant')}\n\n"
        f"Date: {fields.get('transaction_date')}\n\n"
        f"Time: {fields.get('transaction_time')}\n\n"
        f"Total: {fields.get('total')}\n\n"
        f"Payment: {payment}\n\n"
        "Warnings:\n"
        f"{warning_text}\n\n"
        "Source text preview:\n\n"
        f"{fields.get('source_text_preview') or ''}\n"
    )


def write_extraction(record: dict[str, Any], extraction: dict[str, Any]) -> tuple[Path, Path]:
    packet_dir = Path(str(record.get("source_packet_dir") or "")).expanduser()
    extract_dir = packet_dir / "extract"
    extract_dir.mkdir(parents=True, exist_ok=True)
    extract_json = extract_dir / "extract.json"
    extract_md = extract_dir / "extract.md"
    extract_json.write_text(json.dumps(extraction, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    extract_md.write_text(markdown_extraction(extraction), encoding="utf-8")
    return extract_json, extract_md


def record_category(record: dict[str, Any]) -> str:
    return str(record.get("approved_category") or record.get("category") or "").lower()


def select_batch_records(
    records: list[dict[str, Any]],
    *,
    project: str = "",
    category: str = "",
    limit: int = 20,
) -> list[dict[str, Any]]:
    selected = list(records)
    if project:
        selected = [
            record for record in selected
            if str(record.get("project") or "").lower() == project.lower()
        ]
    if category:
        selected = [
            record for record in selected
            if record_category(record) == category.lower()
        ]

    def key(record: dict[str, Any]) -> tuple[str, int]:
        return str(record.get("finalized_at") or ""), records.index(record)

    selected.sort(key=key, reverse=True)
    return selected[:limit]


def extract_record(record: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    packet_dir = Path(str(record.get("source_packet_dir") or "")).expanduser()
    extract_json = packet_dir / "extract" / "extract.json"
    extract_md = packet_dir / "extract" / "extract.md"
    result = {
        "packet_id": record.get("packet_id"),
        "packet_dir": str(packet_dir),
        "category": record_category(record),
        "status": "",
        "merchant": None,
        "total": None,
        "warnings": [],
        "error": "",
    }

    if extract_json.exists() and extract_md.exists() and not force:
        result["status"] = "skipped_existing"
        return result

    category = category_for(record, packet_dir)
    result["category"] = category
    if category not in SUPPORTED_CATEGORIES:
        result["status"] = "skipped_unsupported"
        result["error"] = "Extraction currently supports receipt and financial packets only."
        return result

    text_path = packet_dir / "output" / "scan.txt"
    if not text_path.exists() or not read_text(text_path).strip():
        result["status"] = "skipped_missing_ocr"
        result["error"] = "No OCR text found for extraction."
        return result

    try:
        extraction = build_extraction(record)
        write_extraction(record, extraction)
    except SystemExit as exc:
        message = str(exc)
        if "No OCR text found" in message:
            result["status"] = "skipped_missing_ocr"
        elif "supports receipt and financial" in message:
            result["status"] = "skipped_unsupported"
        else:
            result["status"] = "error"
        result["error"] = message
        return result
    except Exception as exc:
        result["status"] = "error"
        result["error"] = str(exc)
        return result

    fields = extraction.get("fields") or {}
    result["status"] = "extracted"
    result["merchant"] = fields.get("merchant")
    result["total"] = fields.get("total")
    result["warnings"] = extraction.get("warnings") or []
    return result


def batch_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "selected": len(results),
        "extracted": 0,
        "skipped_existing": 0,
        "skipped_unsupported": 0,
        "skipped_missing_ocr": 0,
        "errors": 0,
        "results": results,
    }
    for result in results:
        status = result.get("status")
        if status == "extracted":
            summary["extracted"] += 1
        elif status == "skipped_existing":
            summary["skipped_existing"] += 1
        elif status == "skipped_unsupported":
            summary["skipped_unsupported"] += 1
        elif status == "skipped_missing_ocr":
            summary["skipped_missing_ocr"] += 1
        else:
            summary["errors"] += 1
    return summary


def run_batch(records: list[dict[str, Any]], *, force: bool = False) -> dict[str, Any]:
    return batch_summary([extract_record(record, force=force) for record in records])


def print_summary(extraction: dict[str, Any], extract_json: Path, extract_md: Path) -> None:
    fields = extraction.get("fields") or {}
    packet_dir = Path(str(extraction.get("packet_dir")))
    print("\nLAIA Librarian Extract Complete\n")
    print(f"Packet: {extraction.get('packet_dir')}")
    print(f"Packet ID: {extraction.get('packet_id')}")
    print(f"Category: {extraction.get('category')}")
    print(f"Merchant: {fields.get('merchant')}")
    print(f"Date: {fields.get('transaction_date')}")
    print(f"Total: {fields.get('total')}")
    print(f"Confidence: {fields.get('confidence', 0.0):.2f}")
    print("\nWrote:")
    print(f"  {extract_json.relative_to(packet_dir)}")
    print(f"  {extract_md.relative_to(packet_dir)}")
    print("")


def print_batch_summary(summary: dict[str, Any]) -> None:
    print("\nLAIA Librarian Extract Batch Complete\n")
    print(f"Selected: {summary['selected']}")
    print(f"Extracted: {summary['extracted']}")
    print(f"Skipped existing: {summary['skipped_existing']}")
    print(f"Skipped unsupported: {summary['skipped_unsupported']}")
    print(f"Skipped missing OCR: {summary['skipped_missing_ocr']}")
    print(f"Errors: {summary['errors']}")
    recent = summary.get("results", [])[:10]
    if recent:
        print("\nRecent results:")
        for result in recent:
            warning_text = ", ".join(result.get("warnings") or [])
            if warning_text:
                warning_text = f" warnings={warning_text}"
            print(
                f"  {result.get('packet_id')} {result.get('merchant')} "
                f"total={result.get('total')}{warning_text} status={result.get('status')}"
            )
    print("")


def command_extract(args) -> None:
    path = catalog_path()
    if getattr(args, "last", False):
        record = latest_catalog_record(path)
        extraction = build_extraction(record)
        extract_json, extract_md = write_extraction(record, extraction)
        print_summary(extraction, extract_json, extract_md)
        return

    records = select_batch_records(
        load_catalog_records(path),
        project=getattr(args, "project", "") or "",
        category=getattr(args, "category", "") or "",
        limit=int(getattr(args, "limit", 20) or 20),
    )
    summary = run_batch(records, force=bool(getattr(args, "force", False)))
    if getattr(args, "json", False):
        print(json.dumps(summary, indent=2) + "\n")
        return
    print_batch_summary(summary)
