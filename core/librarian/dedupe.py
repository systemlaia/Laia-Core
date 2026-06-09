import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Optional

try:
    from librarian.catalog import catalog_path, load_catalog_records
    from librarian.index import load_packet, path_from_packet
except ModuleNotFoundError:
    from core.librarian.catalog import catalog_path, load_catalog_records
    from core.librarian.index import load_packet, path_from_packet

STOPWORDS = {
    "the", "and", "for", "with", "receipt", "total", "balance", "paid",
    "amount", "mastercard", "visa", "debit", "credit", "transaction",
    "store", "purchase", "item", "qty", "price", "date", "time",
    "subtotal", "tax", "change", "cash", "sale", "thank", "thanks",
    "customer", "service", "account", "card",
}

def normalize_text(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_amounts(text: str) -> set[str]:
    raw = str(text or "")
    matches = re.findall(r"\b\$?(\d+\.\d{2})\b", raw)
    return {m for m in matches if len(m) > 0}


def extract_date_tokens(text: str) -> set[str]:
    normalized = text
    tokens = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", normalized))
    tokens.update(re.findall(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", normalized))
    tokens.update(re.findall(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\.?\s+\d{1,2}\b", normalized, flags=re.IGNORECASE))
    return {token.lower() for token in tokens}


def extract_tokens(text: str, min_length: int = 4) -> set[str]:
    normalized = normalize_text(text)
    tokens = re.findall(r"\b[a-z]{%d,}\b" % min_length, normalized)
    return {token for token in tokens if token not in STOPWORDS}


def extract_merchant_tokens(text: str) -> set[str]:
    lines = str(text or "").splitlines()[:20]
    raw = " ".join(lines)
    tokens = extract_tokens(raw, min_length=4)
    return tokens


def load_text_for_record(record: dict[str, Any]) -> str:
    source = record.get("source_packet_dir")
    if not source:
        return ""
    packet_dir = Path(source).expanduser()
    scan_path = packet_dir / "output" / "scan.txt"
    if scan_path.exists():
        return scan_path.read_text(encoding="utf-8", errors="replace").strip()

    packet_json = packet_dir / "packet.json"
    if packet_json.exists():
        try:
            packet = load_packet(packet_json)
        except SystemExit:
            return ""
        text_path = path_from_packet(packet, "text")
        if text_path and text_path.exists():
            return text_path.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def ocr_similarity(text_a: str, text_b: str) -> float:
    a = normalize_text(text_a)
    b = normalize_text(text_b)
    if not a or not b:
        return 0.0
    return float(SequenceMatcher(None, a, b).ratio())


def candidate_score(target: dict[str, Any], candidate: dict[str, Any], target_text: str, candidate_text: str) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0

    amount_intersection = extract_amounts(target_text) & extract_amounts(candidate_text)
    if amount_intersection:
        amount_value = sorted(amount_intersection)[0]
        reasons.append(f"shared amount: {amount_value}")
        score += 0.35

    merchant_intersection = extract_merchant_tokens(target_text) & extract_merchant_tokens(candidate_text)
    if merchant_intersection:
        token = sorted(merchant_intersection)[0]
        reasons.append(f"shared merchant token: {token}")
        score += 0.25

    item_intersection = extract_tokens(target_text) & extract_tokens(candidate_text)
    if item_intersection:
        token = sorted(item_intersection)[0]
        reasons.append(f"shared item token: {token}")
        score += 0.15

    date_intersection = extract_date_tokens(target_text) & extract_date_tokens(candidate_text)
    if date_intersection:
        token = sorted(date_intersection)[0]
        reasons.append(f"shared date token: {token}")
        score += 0.05

    if target.get("approved_category") and target.get("approved_category") == candidate.get("approved_category"):
        reasons.append(f"same category: {target.get('approved_category')}")
        score += 0.05

    if target.get("page_count") == candidate.get("page_count") and target.get("page_count") is not None:
        reasons.append(f"same page_count: {int(target.get('page_count'))}")
        score += 0.05

    similarity = ocr_similarity(target_text, candidate_text)
    if similarity > 0:
        reasons.append(f"OCR similarity: {similarity:.2f}")
        score += min(similarity, 1.0) * 0.35

    return min(score, 1.0), reasons


def classify_score(score: float) -> str:
    if score >= 0.85:
        return "likely_duplicate"
    if score >= 0.60:
        return "possible_duplicate"
    return "low_confidence"


def build_candidate_matches(target: dict[str, Any], prior_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    target_text = load_text_for_record(target)
    candidates: list[dict[str, Any]] = []
    for candidate in prior_records:
        if candidate.get("packet_id") == target.get("packet_id"):
            continue
        if candidate.get("packet_type") != target.get("packet_type"):
            continue
        if candidate.get("project") != target.get("project"):
            continue

        candidate_text = load_text_for_record(candidate)
        score, reasons = candidate_score(target, candidate, target_text, candidate_text)
        category = classify_score(score)
        if category == "low_confidence":
            continue

        candidates.append({
            "packet_id": candidate.get("packet_id"),
            "source_packet_dir": candidate.get("source_packet_dir"),
            "created_at": candidate.get("created_at"),
            "score": round(score, 2),
            "category": category,
            "reasons": reasons,
        })
    candidates.sort(key=lambda item: item["score"], reverse=True)
    return candidates


def dedupe_record(target: dict[str, Any], prior_records: list[dict[str, Any]]) -> dict[str, Any]:
    matches = build_candidate_matches(target, prior_records)
    return {
        "dedupe_type": "laia.librarian.dedupe",
        "packet_id": target.get("packet_id"),
        "packet_type": target.get("packet_type"),
        "project": target.get("project"),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "approved_category": target.get("approved_category"),
        "page_count": target.get("page_count"),
        "word_count": target.get("word_count"),
        "source_packet_dir": target.get("source_packet_dir"),
        "candidate_count": len(matches),
        "candidates": matches,
    }


def markdown_dedupe(record: dict[str, Any]) -> str:
    header = [
        "# LAIA Librarian Dedupe Complete",
        "",
        f"Packet: {record.get('source_packet_dir')}",
        f"Packet ID: {record.get('packet_id')}",
        f"Candidates: {record.get('candidate_count')}",
        "",
    ]
    for candidate in record.get("candidates", []):
        header.append(f"{candidate.get('category').replace('_', ' ').title()}: {candidate.get('packet_id')}")
        header.append(f"Score: {candidate.get('score'):.2f}")
        header.append("Reasons:")
        for reason in candidate.get("reasons", []):
            header.append(f"  - {reason}")
        header.append("")
    if not record.get("candidates"):
        header.append("No duplicate candidates found.")
        header.append("")

    header.append("Wrote:")
    header.append("  dedupe/dedupe.json")
    header.append("  dedupe/dedupe.md")
    return "\n".join(header) + "\n"


def write_dedupe(packet_json: Path, record: dict[str, Any]) -> tuple[Path, Path]:
    dedupe_dir = packet_json.parent / "dedupe"
    dedupe_dir.mkdir(parents=True, exist_ok=True)
    dedupe_json = dedupe_dir / "dedupe.json"
    dedupe_md = dedupe_dir / "dedupe.md"
    dedupe_json.write_text(json.dumps(record, indent=2, sort_keys=False) + "\n", encoding="utf-8")
    dedupe_md.write_text(markdown_dedupe(record), encoding="utf-8")
    return dedupe_json, dedupe_md


def print_summary(record: dict[str, Any], dedupe_json: Path, dedupe_md: Path) -> None:
    packet_dir = dedupe_json.parent.parent
    print("\nLAIA Librarian Dedupe Complete\n")
    print(f"Packet: {record.get('source_packet_dir')}")
    print(f"Packet ID: {record.get('packet_id')}")
    print(f"Candidates: {record.get('candidate_count')}")
    if record.get('candidate_count'):
        print("")
        for candidate in record.get('candidates', []):
            print(f"  {candidate.get('packet_id')} ({candidate.get('category')}): {candidate.get('score'):.2f}")
    print("\nWrote:")
    print(f"  {dedupe_json.relative_to(packet_dir)}")
    print(f"  {dedupe_md.relative_to(packet_dir)}")
    print("")


def command_dedupe(args) -> None:
    if not getattr(args, "last", False):
        raise SystemExit("Only --last is supported for v0: laia librarian dedupe --last")
    records = load_catalog_records(catalog_path())
    target = records[-1]
    prior = [record for record in records[:-1] if record.get("packet_id") != target.get("packet_id")]
    packet_dir = Path(target.get("source_packet_dir", "")).expanduser()
    packet_json = packet_dir / "packet.json"
    if not packet_json.exists():
        raise SystemExit(f"Latest packet.json not found: {packet_json}")
    packet = load_packet(packet_json)
    if not str(packet.get("packet_type", "")).startswith("laia.ingest."):
        raise SystemExit(f"Unsupported packet_type for librarian dedupe: {packet.get('packet_type')}")
    if target.get("packet_type") != packet.get("packet_type") or target.get("project") != packet.get("project"):
        raise SystemExit("Latest catalog record does not match latest packet metadata")
    dedupe = dedupe_record(target, prior)
    dedupe_json, dedupe_md = write_dedupe(packet_json, dedupe)
    print_summary(dedupe, dedupe_json, dedupe_md)
