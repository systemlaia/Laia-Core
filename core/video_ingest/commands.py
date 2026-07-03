import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


DEFAULT_PACKET_ROOT = Path("/Volumes/Public/LAIA/packets/video_ingest")
DEFAULT_CATALOG_ROOT = Path("/Volumes/Public/LAIA/catalogs/video_ingest")
DEFAULT_LOCAL_ROOT = Path("~/LAIA/video_ingest").expanduser()
VIDEO_ROLES = {"", "video", "functional_demo", "listing_video", "performance", "interview", "documentation", "archival", "other"}
REVIEW_STATUSES = {"new", "reviewed", "rejected", "archived"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".mkv", ".m4v", ".avi", ".mts", ".m2ts", ".webm"}


@dataclass(frozen=True)
class VideoConfig:
    packet_root: Path
    catalog_root: Path
    local_root: Path

    @property
    def working_root(self) -> Path:
        return self.local_root / "working"


def config_from_env() -> VideoConfig:
    return VideoConfig(
        packet_root=Path(os.environ.get("LAIA_VIDEO_PACKET_ROOT", DEFAULT_PACKET_ROOT)).expanduser(),
        catalog_root=Path(os.environ.get("LAIA_VIDEO_CATALOG_ROOT", DEFAULT_CATALOG_ROOT)).expanduser(),
        local_root=Path(os.environ.get("LAIA_VIDEO_LOCAL_ROOT", DEFAULT_LOCAL_ROOT)).expanduser(),
    )


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def safe_name(value: str) -> str:
    chars = []
    for char in value.strip():
        if char.isalnum() or char in "._-":
            chars.append(char)
        else:
            chars.append("-")
    result = "".join(chars)
    while "--" in result:
        result = result.replace("--", "-")
    return result.strip("-._") or "video"


def file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise FileNotFoundError(f"Required tool not found: {name}")
    return path


def run_logged(command: list[str], log_path: Path, stdout_path: Optional[Path] = None) -> subprocess.CompletedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    if stdout_path:
        with stdout_path.open("w", encoding="utf-8") as output, log_path.open("a", encoding="utf-8") as log:
            return subprocess.run(command, stdout=output, stderr=log, text=True, check=False)
    with log_path.open("a", encoding="utf-8") as log:
        return subprocess.run(command, stdout=log, stderr=log, text=True, check=False)


def probe_video(path: Path, ffprobe: Optional[str] = None) -> dict:
    ffprobe = ffprobe or require_tool("ffprobe")
    result = subprocess.run(
        [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(f"ffprobe could not read video: {path}: {result.stderr.strip()}")
    data = json.loads(result.stdout)
    if not any(stream.get("codec_type") == "video" for stream in data.get("streams", [])):
        raise ValueError(f"No video stream found: {path}")
    return data


def normalized_summary(path: Path, probe: dict, stills: Optional[list] = None) -> dict:
    video = next(stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video")
    audio = next((stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"), {})
    fmt = probe.get("format", {})
    format_name = str(fmt.get("format_name", "")).split(",", 1)[0]
    return {
        "filename": path.name,
        "duration_seconds": float(fmt.get("duration") or video.get("duration") or 0),
        "size_bytes": int(fmt.get("size") or path.stat().st_size),
        "container": format_name,
        "video_codec": str(video.get("codec_name", "")),
        "audio_codec": str(audio.get("codec_name", "")),
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "frame_rate": str(video.get("avg_frame_rate") or video.get("r_frame_rate") or ""),
        "has_audio": bool(audio),
        "sampled_stills": stills or [],
    }


def sample_timestamps(duration: float, count: int) -> list[float]:
    count = max(1, int(count))
    if duration <= 0:
        return [0.0]
    start = duration * 0.05
    end = duration * 0.95
    if duration < 1:
        return [round(duration / 2, 3)]
    end = min(end, duration - max(0.1, duration * 0.005))
    values = [start + (end - start) * index / max(count - 1, 1) for index in range(count)]
    unique = []
    for value in values:
        value = round(min(max(value, 0), max(duration - 0.01, 0)), 3)
        if not unique or abs(value - unique[-1]) >= 0.05:
            unique.append(value)
    return unique or [round(duration / 2, 3)]


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def review_paths(packet: Path) -> tuple[Path, Path]:
    return packet / "review" / "review.json", packet / "review" / "review.md"


def write_review(packet: Path, review: dict) -> dict:
    review["updated_at"] = utc_now()
    json_path, md_path = review_paths(packet)
    write_json(json_path, review)
    md_path.write_text(
        "\n".join(
            [
                "# LAIA Video Review",
                "",
                f"- Status: {review.get('review_status', '')}",
                f"- Role: {review.get('role', '')}",
                f"- Updated: {review.get('updated_at', '')}",
                "",
                review.get("note", ""),
                "",
            ]
        ),
        encoding="utf-8",
    )
    return review


def read_review(packet: Path) -> dict:
    path, _ = review_paths(packet)
    if not path.exists():
        return {"review_status": "new", "role": "", "note": "", "updated_at": ""}
    return json.loads(path.read_text(encoding="utf-8"))


def packet_manifest(packet: Path) -> dict:
    path = packet / "packet_manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing packet manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def resolve_packet(identifier: str) -> Path:
    direct = Path(identifier).expanduser()
    if direct.is_dir():
        return direct.resolve()
    cfg = config_from_env()
    matches = [path for path in cfg.packet_root.glob(f"*/{identifier}") if path.is_dir()]
    if len(matches) == 1:
        return matches[0].resolve()
    try:
        from packets.registry import config_from_env as registry_config, resolve_packet as registry_resolve
    except (ImportError, ModuleNotFoundError):
        from core.packets.registry import config_from_env as registry_config, resolve_packet as registry_resolve
    try:
        row = registry_resolve(identifier, registry_config().db_path)
        path = Path(row["packet_path"])
        if path.is_dir():
            return path.resolve()
    except Exception:
        pass
    raise FileNotFoundError(f"Video packet not found: {identifier}")


def latest_packet() -> Path:
    root = config_from_env().packet_root
    packets = sorted([path for path in root.glob("*/*") if path.is_dir()])
    if not packets:
        raise FileNotFoundError("No video ingest packets found.")
    return packets[-1]


def verification_data(packet: Path) -> dict:
    errors = []
    originals = [path for path in (packet / "originals").glob("*") if path.is_file()] if (packet / "originals").is_dir() else []
    proxies = [path for path in (packet / "proxy").glob("*.mp4") if path.is_file()] if (packet / "proxy").is_dir() else []
    stills = sorted(path for path in (packet / "stills").glob("frame_*.jpg") if path.is_file()) if (packet / "stills").is_dir() else []
    required = [
        "metadata/ffprobe.json",
        "metadata/technical_summary.json",
        "logs",
        "checksums.sha256",
        "packet_manifest.json",
        "ingest_report.md",
        "stills/contact_sheet.jpg",
    ]
    for item in required:
        if not (packet / item).exists():
            errors.append(f"Missing required item: {item}")
    if len(originals) != 1:
        errors.append(f"Expected exactly one original, found {len(originals)}")
    if len(proxies) != 1:
        errors.append(f"Expected exactly one proxy, found {len(proxies)}")
    if not stills:
        errors.append("No sampled stills found.")
    checksum_ok = False
    if len(originals) == 1 and (packet / "checksums.sha256").is_file():
        lines = [line for line in (packet / "checksums.sha256").read_text().splitlines() if line.strip()]
        if len(lines) != 1:
            errors.append(f"Expected one checksum entry, found {len(lines)}")
        else:
            expected = lines[0].split()[0]
            checksum_ok = file_sha256(originals[0]) == expected
            if not checksum_ok:
                errors.append("Original checksum mismatch.")
    manifest = {}
    try:
        manifest = packet_manifest(packet)
    except Exception as exc:
        errors.append(str(exc))
    if len(originals) == 1 and manifest:
        if originals[0].stat().st_size != int(manifest.get("size_bytes", -1)):
            errors.append("Original size does not match manifest.")
    original_probe_ok = False
    proxy_probe_ok = False
    if len(originals) == 1:
        try:
            probe_video(originals[0])
            original_probe_ok = True
        except Exception as exc:
            errors.append(f"Original probe failed: {exc}")
    if len(proxies) == 1:
        try:
            probe_video(proxies[0])
            proxy_probe_ok = True
        except Exception as exc:
            errors.append(f"Proxy probe failed: {exc}")
    return {
        "packet": str(packet),
        "original_count": len(originals),
        "proxy_count": len(proxies),
        "still_count": len(stills),
        "checksum_ok": checksum_ok,
        "original_probe_ok": original_probe_ok,
        "proxy_probe_ok": proxy_probe_ok,
        "contact_sheet_ok": (packet / "stills" / "contact_sheet.jpg").is_file(),
        "errors": errors,
        "status": "ok" if not errors else "failed",
    }


def verify_packet(packet: Path, quiet: bool = False) -> dict:
    result = verification_data(packet)
    if not quiet:
        print("LAIA Video Packet Verification")
        print()
        print(f"Packet: {packet}")
        print(f"Originals: {result['original_count']}")
        print(f"Checksum: {'ok' if result['checksum_ok'] else 'failed'}")
        print(f"Original probe: {'ok' if result['original_probe_ok'] else 'failed'}")
        print(f"Proxy probe: {'ok' if result['proxy_probe_ok'] else 'failed'}")
        print(f"Stills: {result['still_count']}")
        print(f"Contact sheet: {'ok' if result['contact_sheet_ok'] else 'failed'}")
        for error in result["errors"]:
            print(f"ERROR: {error}")
        print(f"Verification status: {result['status']}")
    return result


def failure_report(work: Path, message: str) -> None:
    (work / "failure_report.md").write_text(
        f"# LAIA Video Ingest Failure\n\n- Failed at: {utc_now()}\n- Error: {message}\n- Working packet: {work}\n",
        encoding="utf-8",
    )


def ingest_video(source: Path, name: Optional[str] = None, still_count: int = 8, proxy_width: int = 1280) -> dict:
    cfg = config_from_env()
    source = source.expanduser().resolve()
    if not source.is_file() or not os.access(source, os.R_OK):
        raise FileNotFoundError(f"Source video not found or unreadable: {source}")
    if not cfg.packet_root.is_dir():
        raise FileNotFoundError(
            f"Video packet root is unavailable:\n  {cfg.packet_root}\n\nMount the NAS share and retry."
        )
    if cfg.packet_root.resolve() == source.parent.resolve():
        raise ValueError("Source directory and video packet root must be different.")
    ffprobe = require_tool("ffprobe")
    ffmpeg = require_tool("ffmpeg")
    source_probe = probe_video(source, ffprobe)
    base_name = safe_name(name or source.stem)
    job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}_{base_name}"
    final = cfg.packet_root / datetime.now().strftime("%Y") / job_id
    if final.exists():
        raise FileExistsError(f"Video packet already exists: {final}")
    work = cfg.working_root / job_id
    if work.exists():
        raise FileExistsError(f"Video working packet already exists: {work}")
    for folder in ["originals", "proxy", "stills", "metadata", "review", "logs"]:
        (work / folder).mkdir(parents=True, exist_ok=True)
    ingest_log = work / "logs" / "ingest.log"
    source_checksum = file_sha256(source)
    try:
        copied = work / "originals" / source.name
        shutil.copy2(source, copied)
        copied_checksum = file_sha256(copied)
        if copied_checksum != source_checksum:
            raise ValueError("Copied original checksum does not match source.")
        (work / "checksums.sha256").write_text(f"{copied_checksum}  ./originals/{source.name}\n", encoding="utf-8")
        write_json(work / "metadata" / "ffprobe.json", source_probe)
        if shutil.which("mediainfo"):
            run_logged([shutil.which("mediainfo"), str(copied)], ingest_log, work / "metadata" / "mediainfo.txt")
        initial_summary = normalized_summary(copied, source_probe)
        proxy = work / "proxy" / f"{base_name}_proxy.mp4"
        proxy_command = [
            ffmpeg,
            "-y",
            "-i",
            str(copied),
            "-vf",
            f"scale='min({max(2, proxy_width)},iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "24",
        ]
        if initial_summary["has_audio"]:
            proxy_command += ["-c:a", "aac", "-b:a", "128k"]
        else:
            proxy_command += ["-an"]
        proxy_command += ["-movflags", "+faststart", str(proxy)]
        result = run_logged(proxy_command, work / "logs" / "ffmpeg_proxy.log")
        if result.returncode != 0 or not proxy.is_file():
            raise RuntimeError("Proxy generation failed.")
        sampled = []
        for index, timestamp in enumerate(sample_timestamps(initial_summary["duration_seconds"], still_count), start=1):
            filename = f"frame_{index:04d}.jpg"
            frame = work / "stills" / filename
            result = run_logged(
                [ffmpeg, "-y", "-ss", f"{timestamp:.3f}", "-i", str(copied), "-frames:v", "1", "-q:v", "2", str(frame)],
                work / "logs" / "ffmpeg_stills.log",
            )
            if result.returncode != 0 or not frame.is_file():
                raise RuntimeError(f"Still generation failed at {timestamp:.3f} seconds.")
            sampled.append({"filename": filename, "timestamp_seconds": timestamp})
        contact_files = work / "stills" / "contact_sheet_files.txt"
        contact_files.write_text("\n".join(item["filename"] for item in sampled) + "\n", encoding="utf-8")
        columns = min(4, max(1, len(sampled)))
        rows = math.ceil(len(sampled) / columns)
        contact = work / "stills" / "contact_sheet.jpg"
        result = run_logged(
            [
                ffmpeg,
                "-y",
                "-pattern_type",
                "glob",
                "-i",
                str(work / "stills" / "frame_*.jpg"),
                "-vf",
                f"scale=320:-2,tile={columns}x{rows}",
                "-frames:v",
                "1",
                str(contact),
            ],
            work / "logs" / "ffmpeg_stills.log",
        )
        if result.returncode != 0 or not contact.is_file():
            raise RuntimeError("Contact-sheet generation failed.")
        summary = normalized_summary(copied, source_probe, sampled)
        write_json(work / "metadata" / "technical_summary.json", summary)
        review = write_review(work, {"review_status": "new", "role": "", "note": "", "updated_at": utc_now()})
        manifest = {
            "packet_type": "laia.video_ingest",
            "packet_version": "0.1",
            "job_id": job_id,
            "source": str(source),
            "packet_path": str(final),
            "asset_count": 1,
            "packet_size": str(source.stat().st_size),
            "original_filename": source.name,
            "source_checksum": source_checksum,
            "packet_copy_checksum": copied_checksum,
            "size_bytes": source.stat().st_size,
            "container": summary["container"],
            "duration_seconds": summary["duration_seconds"],
            "video_codec": summary["video_codec"],
            "audio_codec": summary["audio_codec"],
            "width": summary["width"],
            "height": summary["height"],
            "frame_rate": summary["frame_rate"],
            "proxy_filename": proxy.name,
            "still_count": len(sampled),
            "created_at": utc_now(),
        }
        write_json(work / "packet_manifest.json", manifest)
        (work / "ingest_report.md").write_text(
            "\n".join(
                [
                    "# LAIA Video Ingest Report",
                    "",
                    f"- Job ID: {job_id}",
                    f"- Source: {source}",
                    f"- Original: {source.name}",
                    f"- Original checksum: {source_checksum}",
                    f"- Duration: {summary['duration_seconds']:.3f} seconds",
                    f"- Proxy: {proxy.name}",
                    f"- Stills: {len(sampled)}",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        working_verification = verify_packet(work, quiet=True)
        if working_verification["status"] != "ok":
            raise RuntimeError("Working packet verification failed: " + "; ".join(working_verification["errors"]))
        final.parent.mkdir(parents=True, exist_ok=True)
        incoming = final.parent / f".incoming-{job_id}"
        if incoming.exists():
            raise FileExistsError(f"Incoming packet path already exists: {incoming}")
        shutil.copytree(work, incoming, copy_function=shutil.copy2)
        incoming_verification = verify_packet(incoming, quiet=True)
        if incoming_verification["status"] != "ok":
            raise RuntimeError("Published copy verification failed: " + "; ".join(incoming_verification["errors"]))
        os.replace(incoming, final)
        final_verification = verify_packet(final, quiet=True)
        if final_verification["status"] != "ok":
            raise RuntimeError("Final packet verification failed: " + "; ".join(final_verification["errors"]))
        shutil.rmtree(work)
        return {"packet": str(final), "job_id": job_id, "manifest": manifest, "review": review, "verification": final_verification}
    except Exception as exc:
        failure_report(work, str(exc))
        raise


def video_packets() -> list[Path]:
    root = config_from_env().packet_root
    return sorted([path for path in root.glob("*/*") if path.is_dir()], reverse=True)


def packet_details(packet: Path) -> dict:
    manifest = packet_manifest(packet)
    summary_path = packet / "metadata" / "technical_summary.json"
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else {}
    review = read_review(packet)
    verification = verify_packet(packet, quiet=True)
    return {**manifest, "summary": summary, "review": review, "verification": verification}


def print_rows(headers, rows):
    if not rows:
        print("No video packets found.")
        return
    widths = [len(header) for header in headers]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = max(widths[index], len(str(value)))
    print("  ".join(header.ljust(widths[index]) for index, header in enumerate(headers)))
    print("  ".join("-" * width for width in widths))
    for row in rows:
        print("  ".join(str(value).ljust(widths[index]) for index, value in enumerate(row)))


def link_video_project(packet: Path, project_name: str, role: str, note: str = "") -> dict:
    if role not in VIDEO_ROLES - {""}:
        raise ValueError(f"Invalid video role: {role}")
    verification = verify_packet(packet, quiet=True)
    if verification["status"] != "ok":
        raise ValueError("Video packet must verify before project linking.")
    try:
        from projects import registry as projects
    except (ImportError, ModuleNotFoundError):
        from core.projects import registry as projects
    project = projects.ensure_project_record(project_name)
    manifest = packet_manifest(packet)
    now = utc_now()
    packet_info = {"job_id": manifest["job_id"], "packet_type": manifest["packet_type"], "packet_path": str(packet)}
    projects.add_packet_to_project(project["project_id"], packet_info, now)
    proxy = packet / "proxy" / manifest["proxy_filename"]
    projects.add_artifact_to_project(project["project_id"], str(proxy), manifest["job_id"], now, "video_proxy")
    projects.add_video_evidence(
        project["project_id"],
        {
            "packet_id": manifest["job_id"],
            "role": role,
            "original_path": str(packet / "originals" / manifest["original_filename"]),
            "proxy_path": str(proxy),
            "duration_seconds": manifest["duration_seconds"],
            "verification_status": verification["status"],
            "linked_at": now,
            "note": note,
        },
    )
    try:
        from packets.registry import packet_project_link_entry, upsert_packet_project_link
    except (ImportError, ModuleNotFoundError):
        from core.packets.registry import packet_project_link_entry, upsert_packet_project_link
    entry = packet_project_link_entry(
        packet,
        project["project_id"],
        project["name"],
        project["project_type"],
        projects.project_folder(project["project_id"]),
        str(proxy),
        now,
    )
    entry["role"] = role
    entry["note"] = note
    upsert_packet_project_link(packet, entry)
    return {"project": project, "video": projects.project_video_evidence(project["project_id"])[-1]}


def command_ingest(args):
    try:
        result = ingest_video(Path(args.file), args.name, args.stills, args.proxy_width)
        if args.project:
            result["project_link"] = link_video_project(Path(result["packet"]), args.project, args.role, "")
    except Exception as exc:
        raise SystemExit(str(exc))
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Video packet created: {result['packet']}")
        print(f"Verification: {result['verification']['status']}")


def command_verify(args):
    try:
        result = verify_packet(resolve_packet(args.packet))
    except Exception as exc:
        raise SystemExit(str(exc))
    if result["status"] != "ok":
        raise SystemExit(2)


def command_verify_last(_args):
    try:
        result = verify_packet(latest_packet())
    except Exception as exc:
        raise SystemExit(str(exc))
    if result["status"] != "ok":
        raise SystemExit(2)


def command_inspect(args):
    try:
        packet = resolve_packet(args.packet)
        data = packet_details(packet)
    except Exception as exc:
        raise SystemExit(str(exc))
    manifest, summary, review, verification = data, data["summary"], data["review"], data["verification"]
    print("LAIA Video Packet")
    print()
    print(f"Job ID: {manifest.get('job_id', '')}")
    print(f"Packet: {packet}")
    print(f"Original: {manifest.get('original_filename', '')}")
    print("Original checksum:")
    print(manifest.get("packet_copy_checksum", ""))
    print(f"Duration: {summary.get('duration_seconds', 0):.3f} seconds")
    print(f"Video: {summary.get('video_codec', '')} {summary.get('width', 0)}x{summary.get('height', 0)}")
    print(f"Audio: {summary.get('audio_codec') or 'none'}")
    print(f"Proxy: {'present' if manifest.get('proxy_filename') and (packet / 'proxy' / manifest['proxy_filename']).is_file() else 'missing'}")
    print(f"Stills: {len(summary.get('sampled_stills', []))}")
    print(f"Review: {review.get('review_status', '')}")
    print(f"Role: {review.get('role', '')}")
    print(f"Verification: {verification['status']}")


def command_list(_args):
    rows = []
    for packet in video_packets():
        try:
            data = packet_details(packet)
            rows.append((data["job_id"], data["original_filename"], f"{data['duration_seconds']:.1f}", data["review"]["review_status"], data["verification"]["status"]))
        except Exception:
            continue
    print_rows(["job_id", "original", "seconds", "review", "verification"], rows)


def command_recent(args):
    packets = video_packets()[: args.limit]
    rows = []
    for packet in packets:
        try:
            data = packet_details(packet)
            rows.append((data["job_id"], data["created_at"], data["original_filename"], data["packet_path"]))
        except Exception:
            continue
    print_rows(["job_id", "created_at", "original", "packet_path"], rows)


def command_open(args):
    try:
        packet = resolve_packet(args.packet)
    except Exception as exc:
        raise SystemExit(str(exc))
    subprocess.run(["open", str(packet)], check=False)


def command_review(args):
    try:
        packet = resolve_packet(args.packet)
        review = read_review(packet)
        if args.status is not None:
            review["review_status"] = args.status
        if args.role is not None:
            review["role"] = args.role
        if args.note is not None:
            review["note"] = args.note
        write_review(packet, review)
    except Exception as exc:
        raise SystemExit(str(exc))
    print(f"Updated video review: {packet}")


def command_link_project(args):
    try:
        result = link_video_project(resolve_packet(args.packet), args.project, args.role, args.note)
    except Exception as exc:
        raise SystemExit(str(exc))
    print(f"Linked video {args.packet} -> project {result['project']['project_id']}")


def register_video_subcommands(sub):
    video_p = sub.add_parser("video", help="Video ingest commands")
    video_sub = video_p.add_subparsers(dest="video_command")

    ingest_p = video_sub.add_parser("ingest", help="Ingest a video file")
    ingest_p.add_argument("file")
    ingest_p.add_argument("--name")
    ingest_p.add_argument("--project")
    ingest_p.add_argument("--role", choices=sorted(VIDEO_ROLES - {""}), default="video")
    ingest_p.add_argument("--stills", type=int, default=8)
    ingest_p.add_argument("--proxy-width", type=int, default=1280)
    ingest_p.add_argument("--json", action="store_true")
    ingest_p.set_defaults(func=command_ingest)

    verify_p = video_sub.add_parser("verify", help="Verify a video packet")
    verify_p.add_argument("packet")
    verify_p.set_defaults(func=command_verify)
    video_sub.add_parser("verify-last", help="Verify latest video packet").set_defaults(func=command_verify_last)

    inspect_p = video_sub.add_parser("inspect", help="Inspect a video packet")
    inspect_p.add_argument("packet")
    inspect_p.set_defaults(func=command_inspect)
    video_sub.add_parser("list", help="List video packets").set_defaults(func=command_list)

    recent_p = video_sub.add_parser("recent", help="List recent video packets")
    recent_p.add_argument("--limit", type=int, default=10)
    recent_p.set_defaults(func=command_recent)

    open_p = video_sub.add_parser("open", help="Open a video packet")
    open_p.add_argument("packet")
    open_p.set_defaults(func=command_open)

    review_p = video_sub.add_parser("review", help="Update video packet review")
    review_p.add_argument("packet")
    review_p.add_argument("--status", choices=sorted(REVIEW_STATUSES))
    review_p.add_argument("--role", choices=sorted(VIDEO_ROLES - {""}))
    review_p.add_argument("--note")
    review_p.set_defaults(func=command_review)

    link_p = video_sub.add_parser("link-project", help="Link verified video packet to project")
    link_p.add_argument("packet")
    link_p.add_argument("--project", required=True)
    link_p.add_argument("--role", choices=sorted(VIDEO_ROLES - {""}), required=True)
    link_p.add_argument("--note", default="")
    link_p.set_defaults(func=command_link_project)
