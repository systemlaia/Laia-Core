import contextlib
import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional

try:
    from ingest.scan import command_scan, parse_tags
    from librarian.index import command_index, find_latest_packet, load_packet
    from librarian.route import command_route
    from librarian.summarize import command_summarize, load_json
    from librarian.classify import command_classify
    from librarian.review import command_review
    from librarian.failures import write_failure
except ModuleNotFoundError:
    from core.ingest.scan import command_scan, parse_tags
    from core.librarian.index import command_index, find_latest_packet, load_packet
    from core.librarian.route import command_route
    from core.librarian.summarize import command_summarize, load_json
    from core.librarian.classify import command_classify
    from core.librarian.review import command_review
    from core.librarian.failures import write_failure


STAGES: list[tuple[str, Callable[[Any], None]]] = [
    ("ingest scan", command_scan),
    ("librarian index", command_index),
    ("librarian route", command_route),
    ("librarian summarize", command_summarize),
    ("librarian classify", command_classify),
    ("librarian review", command_review),
]


def scan_args(args) -> SimpleNamespace:
    return SimpleNamespace(
        test=False,
        list_options=False,
        profile=getattr(args, "profile", "document"),
        project=getattr(args, "project", "Inbox"),
        tags=getattr(args, "tags", ""),
        dry_run=False,
        device=None,
    )


def last_args() -> SimpleNamespace:
    return SimpleNamespace(last=True)


def print_dry_run(args) -> None:
    tags = parse_tags(getattr(args, "tags", ""))
    print("\nLAIA Scan Document Workflow Dry Run\n")
    print("Stages:")
    for index, (label, _func) in enumerate(STAGES, start=1):
        print(f"  {index}. {label}")
    print("\nScan:")
    print(f"  profile: {getattr(args, 'profile', 'document')}")
    print(f"  project: {getattr(args, 'project', 'Inbox')}")
    print(f"  tags: {tags}")
    print("\nNo files written.")
    print("")


def tail_text(text: str, max_lines: int = 10) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) <= max_lines:
        return "\n".join(lines)
    return "\n".join(lines[-max_lines:])


def infer_packet_dir_from_error(text: str) -> Optional[Path]:
    marker = "/logs/scanimage.log"
    if marker not in text:
        return None
    before = text.split(marker, 1)[0]
    start = before.rfind("/")
    if start == -1:
        return None
    # Walk backward to the beginning of the absolute path containing the packet.
    path_text = before[before.rfind(" /") + 1:] if " /" in before else before[start:]
    if not path_text.startswith("/"):
        return None
    return Path(path_text)


def mark_workflow_failure(packet_dir: Optional[Path], label: str, error: str) -> None:
    if not packet_dir:
        return
    try:
        write_failure(packet_dir, stage=label, error=error)
    except Exception:
        return


def run_stage(
    label: str,
    func: Callable[[Any], None],
    args,
    verbose: bool = False,
    packet_dir: Optional[Path] = None,
    mark_failure: bool = False,
) -> None:
    if verbose:
        try:
            func(args)
        except SystemExit as exc:
            print(f"\nLAIA Scan Document Workflow Failed\n\nStage: {label}")
            if mark_failure:
                mark_workflow_failure(packet_dir or infer_packet_dir_from_error(str(exc)), label, str(exc))
            raise exc
        return

    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            func(args)
    except SystemExit as exc:
        output = stdout_buf.getvalue() + stderr_buf.getvalue()
        snippet = tail_text(output) or str(exc)
        print("\nLAIA Scan Document Workflow Failed\n")
        print(f"Stage: {label}")
        if snippet:
            print(f"Error: {snippet}")
        if mark_failure:
            mark_workflow_failure(
                packet_dir or infer_packet_dir_from_error(output + "\n" + str(exc)),
                label,
                snippet,
            )
        raise exc
    except Exception as exc:
        output = stdout_buf.getvalue() + stderr_buf.getvalue()
        snippet = tail_text(output)
        print("\nLAIA Scan Document Workflow Failed\n")
        print(f"Stage: {label}")
        if snippet:
            print(f"Error: {snippet}")
        else:
            print(f"Error: {exc}")
        if mark_failure:
            mark_workflow_failure(
                packet_dir or infer_packet_dir_from_error(output + "\n" + str(exc)),
                label,
                snippet or str(exc),
            )
        raise


def workflow_summary(packet_json: Path) -> dict[str, Any]:
    packet = load_packet(packet_json)
    packet_dir = packet_json.parent
    classification = load_json(packet_dir / "classify" / "classification.json")
    review = load_json(packet_dir / "review" / "review.json")
    return {
        "packet": packet,
        "packet_dir": str(packet_dir),
        "classification": classification,
        "review": review,
    }


def print_summary(summary: dict[str, Any]) -> None:
    packet = summary["packet"]
    classification = summary["classification"]
    review = summary["review"]

    print("\nLAIA Scan Document Workflow Complete\n")
    print(f"Packet: {summary['packet_dir']}")
    print(f"Project: {packet.get('project')}")
    print(f"Profile: {packet.get('profile')}")
    print(f"Pages: {packet.get('page_count')}")
    print(f"OCR: {packet.get('ocr_status')}")
    print(f"Primary Category: {classification.get('primary_category')}")
    print(f"Confidence: {float(classification.get('confidence') or 0.0):.2f}")
    print(f"Review Status: {review.get('review_status')}")
    print(f"Recommended Action: {review.get('recommended_action')}")
    print("\nNext:")
    print("  laia librarian approve --last")
    print("  laia librarian finalize --last")
    print("  laia librarian catalog --last")
    print("")


def run_scan_document_workflow(args) -> Optional[dict[str, Any]]:
    if getattr(args, "dry_run", False):
        print_dry_run(args)
        return None

    verbose = getattr(args, "verbose", False)
    run_stage("ingest scan", command_scan, scan_args(args), verbose=verbose, mark_failure=True)
    packet_json = find_latest_packet()
    packet_dir = packet_json.parent
    run_stage("librarian index", command_index, last_args(), verbose=verbose, packet_dir=packet_dir, mark_failure=True)
    run_stage("librarian route", command_route, last_args(), verbose=verbose, packet_dir=packet_dir, mark_failure=True)
    run_stage("librarian summarize", command_summarize, last_args(), verbose=verbose, packet_dir=packet_dir, mark_failure=True)
    run_stage("librarian classify", command_classify, last_args(), verbose=verbose, packet_dir=packet_dir, mark_failure=True)
    run_stage("librarian review", command_review, last_args(), verbose=verbose, packet_dir=packet_dir, mark_failure=True)

    summary = workflow_summary(packet_json)
    print_summary(summary)
    return summary


def command_scan_document(args) -> None:
    run_scan_document_workflow(args)
