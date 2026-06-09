import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml


PROFILE_DIR = Path(__file__).resolve().parent / "profiles"
DEFAULT_ROOT = Path.home() / "LAIA" / "Inbox" / "Ingest" / "Scans"


def slugify(value: Optional[str]) -> str:
    text = (value or "inbox").strip().lower()
    chars = []
    for ch in text:
        if ch.isalnum():
            chars.append(ch)
        elif ch in (" ", "-", "_"):
            chars.append("-")
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-") or "inbox"


def parse_tags(value: Optional[str]) -> list[str]:
    if not value:
        return []
    return [tag.strip() for tag in value.split(",") if tag.strip()]


def load_profile(profile_id: str) -> dict[str, Any]:
    path = PROFILE_DIR / f"{profile_id}.yaml"
    if not path.exists():
        available = ", ".join(sorted(p.stem for p in PROFILE_DIR.glob("*.yaml")))
        raise SystemExit(f"Unknown scan profile: {profile_id}. Available: {available}")
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data


def run_command(command: list[str], *, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)


def list_scanners() -> tuple[bool, str]:
    if not shutil.which("scanimage"):
        return False, "scanimage not found"
    result = run_command(["scanimage", "-L"])
    text = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, text.strip()


def parse_scanimage_devices(output: str) -> list[dict[str, str]]:
    devices = []
    pattern = re.compile(r"device `([^`]+)' is a (.+)")
    for line in output.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        device = match.group(1)
        label = match.group(2).strip()
        backend = device.split(":", 1)[0] if ":" in device else device
        devices.append({"device": device, "label": label, "backend": backend})
    return devices


def choose_device(
    devices: list[dict[str, str]],
    requested: Optional[str] = None,
) -> Optional[dict[str, str]]:
    if requested:
        for device in devices:
            if device["device"] == requested:
                return device
        return {"device": requested, "label": requested, "backend": requested.split(":", 1)[0]}

    for device in devices:
        haystack = f"{device['device']} {device['label']}".lower()
        if "dr-3010c" in haystack or "dr3010c" in haystack:
            return device
    for device in devices:
        if device["backend"] == "canon_dr":
            return device
    return devices[0] if devices else None


def packet_timestamp() -> tuple[str, str]:
    now = datetime.now().astimezone()
    folder_stamp = now.strftime("%Y-%m-%d_%H%M%S")
    created_at = now.isoformat(timespec="seconds")
    return folder_stamp, created_at


def build_packet_dir(project: Optional[str], root: Path = DEFAULT_ROOT) -> tuple[Path, str]:
    stamp, created_at = packet_timestamp()
    packet_dir = root / f"{stamp}_{slugify(project)}"
    return packet_dir, created_at


def scan_command(device: str, profile: dict[str, Any]) -> list[str]:
    image_format = str(profile.get("format", "tiff"))
    command = [
        "scanimage",
        "--device-name",
        device,
        "--source",
        str(profile.get("source", "ADF Duplex")),
        "--mode",
        str(profile.get("mode", "Gray")),
        "--resolution",
        str(profile.get("dpi", 300)),
        f"--format={image_format}",
        "--batch=page_%04d.tif",
    ]
    if profile.get("swdeskew", profile.get("deskew")):
        command.append("--swdeskew=yes")
    if "swdespeck" in profile:
        swdespeck = profile["swdespeck"]
        if isinstance(swdespeck, bool) or not isinstance(swdespeck, int):
            raise SystemExit("Invalid profile value for swdespeck: expected integer 0..9")
        if swdespeck < 0 or swdespeck > 9:
            raise SystemExit("Invalid profile value for swdespeck: expected integer 0..9")
        command.append(f"--swdespeck={swdespeck}")
    return command


def make_pdf(source_files: list[Path], output_pdf: Path) -> tuple[bool, str]:
    if not source_files:
        return False, "no source images"
    if not shutil.which("img2pdf"):
        return False, "img2pdf not found"
    command = ["img2pdf", *[str(path) for path in source_files], "-o", str(output_pdf)]
    result = run_command(command)
    if result.returncode != 0:
        return False, ((result.stderr or result.stdout or "").strip() or "img2pdf failed")
    return True, "created"


def run_ocr(profile: dict[str, Any], input_pdf: Path, ocr_pdf: Path, text_path: Path) -> tuple[bool, str]:
    if not profile.get("ocr"):
        return False, "not requested"
    if not input_pdf.exists():
        return False, "scan PDF unavailable"
    if not shutil.which("ocrmypdf"):
        return False, "ocrmypdf not found"

    command = ["ocrmypdf", "--sidecar", str(text_path)]
    if profile.get("deskew"):
        command.append("--deskew")
    if profile.get("rotate_pages"):
        command.append("--rotate-pages")
    if profile.get("clean"):
        command.append("--clean")
    command.extend([str(input_pdf), str(ocr_pdf)])

    result = run_command(command)
    if result.returncode != 0:
        return False, ((result.stderr or result.stdout or "").strip() or "ocrmypdf failed")
    return True, "complete"


def write_packet_metadata(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(json.dumps(metadata, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def print_summary(metadata: dict[str, Any], pdf_status: str, ocr_status: str) -> None:
    paths = metadata["paths"]
    print("\nLAIA Scan Ingest Complete\n")
    print(f"Device: {metadata.get('device_label')}")
    print(f"Profile: {metadata.get('profile')}")
    print(f"Project: {metadata.get('project')}")
    print(f"Pages: {metadata.get('page_count')}")
    print(f"PDF: {paths.get('pdf') if metadata.get('pdf_created') else pdf_status}")
    print(f"OCR: {ocr_status}")
    print(f"Packet: {paths.get('packet_dir')}")
    print("\nNext:")
    print("  laia librarian index --last")
    print("  laia librarian route --last")
    print("")


def command_scan(args) -> None:
    scanimage_available = shutil.which("scanimage") is not None
    ok, scanner_output = list_scanners()
    devices = parse_scanimage_devices(scanner_output if scanner_output else "")
    selected = choose_device(devices, getattr(args, "device", None))

    if getattr(args, "test", False):
        print("\nLAIA Scan Test\n")
        print(f"scanimage: {'available' if scanimage_available else 'missing'}")
        print(f"img2pdf: {'available' if shutil.which('img2pdf') else 'missing'}")
        print(f"ocrmypdf: {'available' if shutil.which('ocrmypdf') else 'missing'}")
        print(f"scanners: {len(devices)}")
        if scanner_output:
            print("\nscanimage -L:")
            print(scanner_output)
        if selected:
            print(f"\nSelected: {selected['label']} ({selected['device']})")
        print("")
        return

    if getattr(args, "list_options", False):
        if not scanimage_available:
            raise SystemExit("scanimage not found")
        if not selected:
            raise SystemExit("No scanner detected")
        result = subprocess.run(
            ["scanimage", "--help", "-d", selected["device"]],
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SystemExit(result.returncode)
        return

    if not scanimage_available:
        raise SystemExit("scanimage is required for scan ingest")
    if not selected:
        raise SystemExit("No scanner detected. Run: laia ingest scan --test")

    profile = load_profile(getattr(args, "profile", "document"))
    project = getattr(args, "project", None) or "Inbox"
    tags = parse_tags(getattr(args, "tags", None))
    packet_dir, created_at = build_packet_dir(project)
    source_dir = packet_dir / "source"
    output_dir = packet_dir / "output"
    logs_dir = packet_dir / "logs"
    scan_log = logs_dir / "scanimage.log"
    pdf_path = output_dir / "scan.pdf"
    ocr_pdf_path = output_dir / "scan_ocr.pdf"
    text_path = output_dir / "scan.txt"
    command = scan_command(selected["device"], profile)

    if getattr(args, "dry_run", False):
        print("\nLAIA Scan Dry Run\n")
        print(f"Device: {selected['label']} ({selected['device']})")
        print(f"Profile: {profile.get('id')}")
        print(f"Project: {project}")
        print(f"Packet: {packet_dir}")
        print("Command:")
        print("  " + " ".join(command))
        print("")
        return

    source_dir.mkdir(parents=True, exist_ok=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)

    scan_result = run_command(command, cwd=source_dir)
    scan_log.write_text(
        "COMMAND\n"
        + " ".join(command)
        + "\n\nSTDOUT\n"
        + (scan_result.stdout or "")
        + "\nSTDERR\n"
        + (scan_result.stderr or ""),
        encoding="utf-8",
    )
    if scan_result.returncode != 0:
        raise SystemExit(f"scanimage failed; see {scan_log}")

    source_files = sorted(source_dir.glob("page_*.tif"))
    pdf_created, pdf_status = make_pdf(source_files, pdf_path)
    ocr_completed, ocr_status = run_ocr(profile, pdf_path, ocr_pdf_path, text_path)

    metadata = {
        "packet_type": "laia.ingest.scan",
        "created_at": created_at,
        "device_label": selected["label"],
        "device_backend": selected["backend"],
        "device": selected["device"],
        "profile": profile.get("id", getattr(args, "profile", "document")),
        "project": project,
        "tags": tags,
        "source": profile.get("source"),
        "mode": profile.get("mode"),
        "dpi": profile.get("dpi"),
        "page_count": len(source_files),
        "ocr_requested": bool(profile.get("ocr")),
        "ocr_completed": ocr_completed,
        "ocr_status": ocr_status,
        "pdf_created": pdf_created,
        "pdf_status": pdf_status,
        "paths": {
            "packet_dir": str(packet_dir),
            "source_dir": str(source_dir),
            "pdf": str(pdf_path) if pdf_created else "",
            "ocr_pdf": str(ocr_pdf_path) if ocr_completed else "",
            "text": str(text_path) if text_path.exists() else "",
            "scan_log": str(scan_log),
        },
    }
    write_packet_metadata(packet_dir / "packet.json", metadata)
    print_summary(metadata, pdf_status, ocr_status)
