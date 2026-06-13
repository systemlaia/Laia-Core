import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

try:
    from packets.registry import DEFAULT_PAPER_PACKET_ROOT, PAPER_REQUIRED_ITEMS
    from packets.standard import (
        checksum_path,
        latest_packet as standard_latest_packet,
        packet_manifest_path,
        read_packet_manifest,
        validate_required_items,
        write_packet_manifest,
    )
except ModuleNotFoundError:
    from core.packets.registry import DEFAULT_PAPER_PACKET_ROOT, PAPER_REQUIRED_ITEMS
    from core.packets.standard import (
        checksum_path,
        latest_packet as standard_latest_packet,
        packet_manifest_path,
        read_packet_manifest,
        validate_required_items,
        write_packet_manifest,
    )


PAPER_PACKET_TYPE = "laia.paper_ingest"
PAPER_PACKET_VERSION = "0.1"
PAPER_WORKFLOW_STATE = "paper_workflow_state.json"
PAPER_STATE_SIDECARS = {
    "packet": "packet.json",
    "index": "index/index.json",
    "route": "route/route.json",
    "classify": "classify/classification.json",
    "classification_correction": "classify/correction.json",
    "extract": "extract/extract.json",
    "summary": "summary/summary.json",
    "review": "review/review.json",
    "approval": "approval/approval.json",
    "final": "final/final.json",
    "failure": "failure/failure.json",
}


def config_paper_root() -> Path:
    return Path(os.environ.get("LAIA_PAPER_PACKET_ROOT", DEFAULT_PAPER_PACKET_ROOT)).expanduser()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def human_size(path: Path) -> str:
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    units = ["B", "K", "M", "G", "T"]
    size = float(total)
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{int(size)}{unit}" if unit == "B" else f"{size:.1f}{unit}"
        size /= 1024
    return f"{total}B"


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load_legacy_packet(packet: Path) -> dict:
    path = packet / "packet.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_json_object(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def originals_files(packet: Path):
    originals = packet / "originals"
    if not originals.exists():
        return []
    return sorted(p for p in originals.rglob("*") if p.is_file())


def infer_page_count(packet: Path, legacy: dict) -> int:
    if legacy.get("page_count") not in (None, ""):
        try:
            return int(legacy.get("page_count"))
        except (TypeError, ValueError):
            pass
    pages = packet / "pages"
    if pages.exists():
        return sum(1 for p in pages.rglob("*") if p.is_file())
    source = packet / "source"
    if source.exists():
        return sum(1 for p in source.rglob("*") if p.is_file())
    return len(originals_files(packet))


def infer_source(packet: Path, legacy: dict) -> str:
    paths = legacy.get("paths") if isinstance(legacy.get("paths"), dict) else {}
    return str(
        legacy.get("source")
        or paths.get("source_dir")
        or paths.get("packet_dir")
        or packet
    )


def build_manifest(packet: Path) -> dict:
    legacy = load_legacy_packet(packet)
    page_count = infer_page_count(packet, legacy)
    manifest = {
        "packet_type": PAPER_PACKET_TYPE,
        "packet_version": PAPER_PACKET_VERSION,
        "job_id": str(legacy.get("job_id") or legacy.get("packet_id") or packet.name),
        "source": infer_source(packet, legacy),
        "packet_path": str(packet),
        "asset_count": page_count,
        "page_count": page_count,
        "packet_size": human_size(packet),
        "created_at": str(legacy.get("created_at") or utc_now()),
    }
    ingest_node = legacy.get("ingest_node") or legacy.get("device_label") or legacy.get("device")
    storage_role = legacy.get("storage_role")
    if ingest_node:
        manifest["ingest_node"] = str(ingest_node)
    if storage_role:
        manifest["storage_role"] = str(storage_role)
    return manifest


def ensure_standard_folders(packet: Path) -> None:
    for folder in ("originals", "metadata", "logs", "review"):
        (packet / folder).mkdir(parents=True, exist_ok=True)


def write_checksums(packet: Path, force: bool = False) -> bool:
    path = checksum_path(packet)
    if path.exists() and not force:
        return False
    entries = []
    originals = packet / "originals"
    for file in originals_files(packet):
        rel = "./" + str(file.relative_to(originals))
        entries.append(f"{file_sha256(file)}  {rel}")
    path.write_text("\n".join(entries) + ("\n" if entries else ""), encoding="utf-8")
    return True


def write_ingest_report(packet: Path, manifest: dict, force: bool = False) -> bool:
    path = packet / "ingest_report.md"
    if path.exists() and not force:
        return False
    path.write_text(
        "\n".join(
            [
                "# LAIA Paper Ingest Report",
                "",
                f"Job ID: {manifest.get('job_id', '')}",
                f"Source: {manifest.get('source', '')}",
                f"Packet: {packet}",
                f"Pages: {manifest.get('page_count', '')}",
                f"Packet size: {manifest.get('packet_size', '')}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return True


def state_sidecar_path(packet: Path) -> Path:
    return packet / "metadata" / PAPER_WORKFLOW_STATE


def sidecars_present(packet: Path) -> dict:
    return {
        name: (packet / rel).exists()
        for name, rel in PAPER_STATE_SIDECARS.items()
    }


def first_value(*values):
    for value in values:
        if value not in (None, ""):
            return value
    return None


def build_workflow_state(packet: Path) -> dict:
    present = sidecars_present(packet)
    classification = load_json_object(packet / PAPER_STATE_SIDECARS["classify"])
    approval = load_json_object(packet / PAPER_STATE_SIDECARS["approval"])
    final = load_json_object(packet / PAPER_STATE_SIDECARS["final"])
    review = load_json_object(packet / PAPER_STATE_SIDECARS["review"])

    if present["failure"]:
        workflow_status = "failed"
        review_status = "failed"
    elif present["final"]:
        workflow_status = "finalized"
        review_status = "finalized"
    elif present["approval"]:
        workflow_status = "approved"
        review_status = "approved"
    elif present["review"]:
        workflow_status = "reviewed"
        review_status = "reviewed"
    elif present["summary"]:
        workflow_status = "summarized"
        review_status = "in_review"
    elif present["extract"]:
        workflow_status = "extracted"
        review_status = "in_review"
    elif present["classify"]:
        workflow_status = "classified"
        review_status = "new"
    else:
        workflow_status = "new"
        review_status = "new"

    classification_corrected = present["classification_correction"]
    approved_category = first_value(
        approval.get("approved_category"),
        final.get("approved_category"),
        review.get("approved_category"),
        classification.get("approved_category"),
        classification.get("category"),
    )
    document_type = first_value(
        approval.get("document_type"),
        final.get("document_type"),
        review.get("document_type"),
        classification.get("document_type"),
    )

    return {
        "workflow_status": workflow_status,
        "review_status": review_status,
        "classification_status": "classified" if present["classify"] else "missing",
        "classification_category": str(classification.get("category") or classification.get("approved_category") or ""),
        "classification_corrected": classification_corrected,
        "extraction_status": "extracted" if present["extract"] else "missing",
        "summary_status": "summarized" if present["summary"] else "missing",
        "approval_status": "approved" if present["approval"] else "missing",
        "final_status": "finalized" if present["final"] else "missing",
        "failure_status": "failed" if present["failure"] else "none",
        "route_status": "routed" if present["route"] else "missing",
        "document_type": str(document_type or ""),
        "approved_category": str(approved_category or ""),
        "source_sidecars_present": present,
        "updated_at": utc_now(),
    }


def write_workflow_state(packet: Path) -> dict:
    packet = Path(packet).expanduser()
    (packet / "metadata").mkdir(parents=True, exist_ok=True)
    state = build_workflow_state(packet)
    state_sidecar_path(packet).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    return state


def read_workflow_state(packet: Path) -> dict:
    return load_json_object(state_sidecar_path(packet))


def standardize_packet(packet: Path, force: bool = False) -> dict:
    packet = Path(packet).expanduser()
    if not packet.is_dir():
        raise FileNotFoundError(f"Paper packet not found: {packet}")

    ensure_standard_folders(packet)
    manifest = build_manifest(packet)
    manifest_written = False
    manifest_path = packet_manifest_path(packet)
    if force or not manifest_path.exists():
        write_packet_manifest(packet, manifest)
        manifest_written = True
    else:
        manifest = read_packet_manifest(packet)

    report_written = write_ingest_report(packet, manifest, force=force)
    checksums_written = write_checksums(packet, force=force)
    state = write_workflow_state(packet)
    validation = validate_required_items(packet, PAPER_REQUIRED_ITEMS)
    return {
        "packet": packet,
        "manifest_written": manifest_written,
        "report_written": report_written,
        "checksums_written": checksums_written,
        "workflow_state": state,
        "validation": validation,
    }


def latest_paper_packet(root: Optional[Path] = None) -> Path:
    root = Path(root or config_paper_root()).expanduser()
    try:
        return standard_latest_packet(root, depth=2)
    except FileNotFoundError:
        candidates = []
        if root.exists():
            for packet in root.glob("*"):
                if packet.is_dir() and not (packet.name.isdigit() and len(packet.name) == 4):
                    candidates.append(packet)
        if not candidates:
            raise SystemExit("No paper packets found.")
        return sorted(candidates)[-1]


def print_standardize_result(result: dict) -> None:
    validation = result["validation"]
    print("LAIA Paper Packet Standardize")
    print()
    print(f"Packet:             {result['packet']}")
    print(f"Manifest written:   {str(result['manifest_written']).lower()}")
    print(f"Report written:     {str(result['report_written']).lower()}")
    print(f"Checksums written:  {str(result['checksums_written']).lower()}")
    print(f"Workflow status:    {result['workflow_state'].get('workflow_status', '')}")
    print(f"Review status:      {result['workflow_state'].get('review_status', '')}")
    print(f"Verification:       {'ok' if validation.ok else 'missing_required_items'}")
    print(f"Missing required:   {','.join(validation.missing)}")


def verify_packet(packet: Path) -> int:
    packet = Path(packet).expanduser()
    validation = validate_required_items(packet, PAPER_REQUIRED_ITEMS)
    print("LAIA Paper Packet Verify")
    print()
    print(f"Packet: {packet}")
    for item in PAPER_REQUIRED_ITEMS:
        if item in validation.missing:
            print(f"MISSING: {item}")
        else:
            print(f"OK: {item}")
    print()
    if validation.ok:
        print("PACKET VERIFIED")
        return 0
    print("PACKET HAS WARNINGS OR ERRORS")
    return 2


def command_standardize(args) -> None:
    result = standardize_packet(Path(args.packet), force=getattr(args, "force", False))
    print_standardize_result(result)


def command_verify(args) -> None:
    result = verify_packet(Path(args.packet))
    if result:
        raise SystemExit(result)


def command_standardize_last(args) -> None:
    result = standardize_packet(latest_paper_packet(), force=getattr(args, "force", False))
    print_standardize_result(result)


def command_verify_last(_args) -> None:
    result = verify_packet(latest_paper_packet())
    if result:
        raise SystemExit(result)


def print_state(packet: Path, state: dict) -> None:
    print("LAIA Paper Workflow State")
    print()
    print(f"Packet:                   {packet}")
    print(f"Workflow Status:          {state.get('workflow_status', '')}")
    print(f"Review Status:            {state.get('review_status', '')}")
    print(f"Classification Status:    {state.get('classification_status', '')}")
    print(f"Classification Category:  {state.get('classification_category', '')}")
    print(f"Classification Corrected: {str(bool(state.get('classification_corrected'))).lower()}")
    print(f"Extraction Status:        {state.get('extraction_status', '')}")
    print(f"Summary Status:           {state.get('summary_status', '')}")
    print(f"Approval Status:          {state.get('approval_status', '')}")
    print(f"Final Status:             {state.get('final_status', '')}")
    print(f"Failure Status:           {state.get('failure_status', '')}")
    print(f"Route Status:             {state.get('route_status', '')}")
    print(f"Document Type:            {state.get('document_type', '')}")
    print(f"Approved Category:        {state.get('approved_category', '')}")
    print(f"Updated At:               {state.get('updated_at', '')}")


def command_refresh_state(args) -> None:
    packet = Path(args.packet).expanduser()
    state = write_workflow_state(packet)
    print_state(packet, state)


def command_refresh_state_last(_args) -> None:
    packet = latest_paper_packet()
    state = write_workflow_state(packet)
    print_state(packet, state)


def command_state(args) -> None:
    packet = Path(args.packet).expanduser()
    state = read_workflow_state(packet) or build_workflow_state(packet)
    print_state(packet, state)


def command_state_last(_args) -> None:
    packet = latest_paper_packet()
    state = read_workflow_state(packet) or build_workflow_state(packet)
    print_state(packet, state)


def register_paper_subcommands(sub) -> None:
    paper_p = sub.add_parser("paper", help="Paper packet commands")
    paper_sub = paper_p.add_subparsers(dest="paper_command")

    standardize_p = paper_sub.add_parser("standardize", help="Write paper packet standard sidecars")
    standardize_p.add_argument("packet")
    standardize_p.add_argument("--force", action="store_true")
    standardize_p.set_defaults(func=command_standardize)

    verify_p = paper_sub.add_parser("verify", help="Verify paper packet standard sidecars")
    verify_p.add_argument("packet")
    verify_p.set_defaults(func=command_verify)

    standardize_last_p = paper_sub.add_parser("standardize-last", help="Standardize latest paper packet")
    standardize_last_p.add_argument("--force", action="store_true")
    standardize_last_p.set_defaults(func=command_standardize_last)

    paper_sub.add_parser("verify-last", help="Verify latest paper packet").set_defaults(func=command_verify_last)

    refresh_p = paper_sub.add_parser("refresh-state", help="Refresh derived paper workflow state")
    refresh_p.add_argument("packet")
    refresh_p.set_defaults(func=command_refresh_state)

    paper_sub.add_parser("refresh-state-last", help="Refresh latest paper workflow state").set_defaults(func=command_refresh_state_last)

    state_p = paper_sub.add_parser("state", help="Show paper workflow state")
    state_p.add_argument("packet")
    state_p.set_defaults(func=command_state)

    paper_sub.add_parser("state-last", help="Show latest paper workflow state").set_defaults(func=command_state_last)
