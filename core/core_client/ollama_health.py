from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Iterable

CHAT_PROBE_TEXT = "Reply with exactly: LAIA_HEALTH_OK"
CHAT_PROBE_EXPECTED = "LAIA_HEALTH_OK"
VISION_PROBE_TEXT = "Read the large text in this image. Reply with exactly: LAIA VISION OK"
VISION_PROBE_EXPECTED = "LAIA VISION OK"
EMBED_PROBE_TEXT = "LAIA embedding health check"
HEALTH_SCHEMA_VERSION = "ollama_model_health_v0.1"


CONFIGURED_MODELS = [
    {"name": "llava:latest", "capability": "vision", "role": "baseline_general_vision"},
    {"name": "llama3.2-vision", "capability": "vision", "role": "general_vision_candidate"},
    {"name": "qwen2.5vl", "capability": "vision", "role": "text_document_vision_candidate"},
    {"name": "qwen2.5:7b", "capability": "chat", "role": "primary_local_text"},
    {"name": "phi4-mini:latest", "capability": "chat", "role": "small_local_text"},
    {"name": "mistral:latest", "capability": "chat", "role": "legacy_local_text"},
    {"name": "llama3:latest", "capability": "chat", "role": "legacy_local_text"},
    {"name": "nomic-embed-text", "capability": "embeddings", "role": "local_embeddings"},
    {"name": "mxbai-embed-large", "capability": "embeddings", "role": "local_embeddings"},
]


def laia_root() -> Path:
    return Path(os.environ.get("LAIA_ROOT", os.path.expanduser("~/LAIA")))


def runtime_root() -> Path:
    return Path(os.environ.get("LAIA_RUNTIME_ROOT", laia_root() / "runtime"))


def health_dir() -> Path:
    return runtime_root() / "ollama"


def health_json_path() -> Path:
    return health_dir() / "model_health.json"


def health_markdown_path() -> Path:
    return health_dir() / "model_health.md"


def configured_ollama_host() -> str:
    try:
        from core_client.ollama import ollama_host
    except (ImportError, ModuleNotFoundError):
        try:
            from core.core_client.ollama import ollama_host
        except (ImportError, ModuleNotFoundError):
            return "http://127.0.0.1:11434"
    return ollama_host()


def parse_ollama_list(text: str) -> list[str]:
    models = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("name "):
            continue
        parts = stripped.split()
        if parts:
            models.append(parts[0])
    return models


def model_base(name: str) -> str:
    return str(name or "").split(":", 1)[0]


def has_tag(name: str) -> bool:
    return ":" in str(name or "")


def resolve_model_name(configured: str, installed: Iterable[str]) -> dict:
    installed_names = sorted(set(installed or []))
    if configured in installed_names:
        return {
            "configured": configured,
            "resolved": configured,
            "installed": True,
            "resolution": "exact",
            "candidates": [configured],
        }

    if has_tag(configured):
        return {
            "configured": configured,
            "resolved": configured,
            "installed": False,
            "resolution": "model_not_installed",
            "candidates": [],
        }

    latest = f"{configured}:latest"
    if latest in installed_names:
        return {
            "configured": configured,
            "resolved": latest,
            "installed": True,
            "resolution": "matched_latest",
            "candidates": [latest],
        }

    matches = [name for name in installed_names if model_base(name) == configured]
    if len(matches) == 1:
        return {
            "configured": configured,
            "resolved": matches[0],
            "installed": True,
            "resolution": "matched_single_installed_tag",
            "candidates": matches,
        }
    if len(matches) > 1:
        return {
            "configured": configured,
            "resolved": None,
            "installed": False,
            "resolution": "ambiguous_installed_tags",
            "candidates": matches,
        }
    return {
        "configured": configured,
        "resolved": latest,
        "installed": False,
        "resolution": "model_not_installed",
        "candidates": [],
    }


def classify_ollama_error(error: Exception | str) -> str:
    text = str(error or "").lower()
    if "unknown model architecture" in text:
        return "unsupported_architecture"
    if "llama-server binary not found" in text or "error starting llama-server" in text:
        return "model_runtime_error"
    if "connection refused" in text or "failed to establish" in text or "urlopen error" in text:
        return "ollama_unavailable"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    if "not found" in text or "pull model" in text or "model" in text and "not installed" in text:
        return "model_not_installed"
    if "architecture" in text or "unsupported" in text:
        return "unsupported_architecture"
    if "memory" in text or "resource" in text or "killed" in text or "no space" in text:
        return "resource_limit"
    if "invalid image" in text or "invalid input" in text or "bad request" in text:
        return "invalid_probe_input"
    if "http error 500" in text or "http 500" in text:
        return "model_runtime_error"
    if "ollama_unavailable" in text:
        return "ollama_unavailable"
    return "model_runtime_error"


def read_json_response(request: urllib.request.Request, timeout: int) -> dict:
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = body.strip() or str(exc)
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc


class OllamaClient:
    def __init__(self, host: str | None = None, timeout: int = 60):
        self.host = (host or configured_ollama_host()).rstrip("/")
        self.timeout = timeout

    def version(self) -> dict:
        with urllib.request.urlopen(f"{self.host}/api/version", timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def list_models(self) -> list[str]:
        if shutil.which("ollama"):
            result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                check=False,
                timeout=20,
            )
            if result.returncode == 0:
                return parse_ollama_list(result.stdout)
        request = urllib.request.Request(f"{self.host}/api/tags", method="GET")
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [row.get("name") for row in data.get("models", []) if row.get("name")]

    def generate(self, model: str, prompt: str, images: list[str] | None = None) -> str:
        payload = {"model": model, "prompt": prompt, "stream": False}
        if images:
            payload["images"] = images
        request = urllib.request.Request(
            f"{self.host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        data = read_json_response(request, self.timeout)
        return str(data.get("response", "")).strip()

    def embed(self, model: str, text: str) -> list[float]:
        payload = {"model": model, "prompt": text}
        request = urllib.request.Request(
            f"{self.host}/api/embeddings",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            return data.get("embedding") or []
        except urllib.error.HTTPError:
            payload = {"model": model, "input": text}
            request = urllib.request.Request(
                f"{self.host}/api/embed",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            data = read_json_response(request, self.timeout)
            embeddings = data.get("embeddings") or []
            return embeddings[0] if embeddings else []


FONT = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "K": ("10001", "10010", "10100", "11000", "10100", "10010", "10001"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "N": ("10001", "11001", "10101", "10011", "10001", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "S": ("01111", "10000", "10000", "01110", "00001", "00001", "11110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
}


def write_probe_png(path: Path, text: str = VISION_PROBE_EXPECTED) -> Path:
    width, height, scale = 360, 90, 7
    pixels = bytearray([255] * width * height * 3)

    def dot(x: int, y: int) -> None:
        if 0 <= x < width and 0 <= y < height:
            offset = (y * width + x) * 3
            pixels[offset : offset + 3] = b"\x00\x00\x00"

    x = 18
    y = 20
    for char in text:
        if char == " ":
            x += 4 * scale
            continue
        glyph = FONT.get(char.upper())
        if not glyph:
            x += 6 * scale
            continue
        for gy, row in enumerate(glyph):
            for gx, value in enumerate(row):
                if value == "1":
                    for sy in range(scale):
                        for sx in range(scale):
                            dot(x + gx * scale + sx, y + gy * scale + sy)
        x += 6 * scale

    scanlines = bytearray()
    stride = width * 3
    for row in range(height):
        scanlines.append(0)
        start = row * stride
        scanlines.extend(pixels[start : start + stride])

    def chunk(kind: bytes, data: bytes) -> bytes:
        import struct
        import zlib as _zlib

        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", _zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    import struct

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(bytes(scanlines)))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)
    return path


def run_chat_probe(client, model: str) -> dict:
    response = client.generate(model, CHAT_PROBE_TEXT)
    ok = CHAT_PROBE_EXPECTED in response
    return {"loadable": True, "healthy": ok, "response_excerpt": response[:120], "error_class": None if ok else "unexpected_response"}


def run_vision_probe(client, model: str, image_path: Path) -> dict:
    write_probe_png(image_path)
    image = base64.b64encode(image_path.read_bytes()).decode("ascii")
    response = client.generate(model, VISION_PROBE_TEXT, images=[image])
    ok = VISION_PROBE_EXPECTED in response.upper()
    return {"loadable": True, "healthy": ok, "response_excerpt": response[:120], "error_class": None if ok else "unexpected_response"}


def run_embedding_probe(client, model: str) -> dict:
    vector = client.embed(model, EMBED_PROBE_TEXT)
    ok = bool(vector)
    return {
        "loadable": True,
        "healthy": ok,
        "embedding_dimensions": len(vector or []),
        "error_class": None if ok else "unexpected_response",
    }


def recommendation_for(row: dict) -> str:
    error_class = row.get("error_class")
    if row.get("healthy"):
        return "ready"
    if row.get("resolution") == "ambiguous_installed_tags":
        return f"Use an explicit tag: {', '.join(row.get('candidates') or [])}"
    if row.get("installed") and row.get("loadable") is False:
        return "Installed but not loadable. Inspect the Ollama runtime error and repair the local runner."
    if error_class == "model_not_installed":
        return f"Install with: ollama pull {row.get('resolved_name') or row.get('configured_name')}"
    if error_class == "ollama_unavailable":
        return "Start Ollama and rerun laia dev ollama-health --write"
    if error_class == "unsupported_architecture":
        return "Use a model supported by this Ollama build and hardware"
    if error_class == "resource_limit":
        return "Free memory/disk or choose a smaller model"
    if error_class == "timeout":
        return "Retry after the model finishes loading or increase local resources"
    return "Inspect last_error and retry after fixing the model/runtime issue"


def row_probe_name(capability: str) -> str:
    if capability == "embeddings":
        return "embedding"
    return capability if capability in {"chat", "vision"} else "chat"


def row_status(row: dict) -> str:
    if row.get("healthy"):
        capability = row.get("capability")
        if capability == "embeddings":
            return "embedding-capable"
        return f"{capability}-capable"
    if row.get("error_class") == "unsupported_architecture":
        return "unsupported_architecture"
    if row.get("installed") and not row.get("loadable"):
        return "failed_to_load"
    if row.get("installed"):
        return "installed"
    return row.get("error_class") or "model_not_installed"


def build_model_row(configured: dict, installed_models: list[str], client, probe_root: Path) -> dict:
    resolution = resolve_model_name(configured["name"], installed_models)
    row = {
        "configured_name": configured["name"],
        "resolved_name": resolution.get("resolved"),
        "capability": configured["capability"],
        "probe": row_probe_name(configured["capability"]),
        "role": configured.get("role"),
        "installed": bool(resolution.get("installed")),
        "resolution": resolution.get("resolution"),
        "candidates": resolution.get("candidates") or [],
        "loadable": False,
        "healthy": False,
        "error_class": None,
        "last_error": None,
    }
    if not row["installed"]:
        row["error_class"] = "model_not_installed" if row["resolution"] != "ambiguous_installed_tags" else "ambiguous_installed_tags"
        row["recommendation"] = recommendation_for(row)
        row["status"] = row_status(row)
        add_legacy_model_keys(row)
        return row

    try:
        if row["capability"] == "vision":
            result = run_vision_probe(client, row["resolved_name"], probe_root / "vision_probe.png")
        elif row["capability"] == "embeddings":
            result = run_embedding_probe(client, row["resolved_name"])
        else:
            result = run_chat_probe(client, row["resolved_name"])
        row.update(result)
    except Exception as exc:
        row["error_class"] = classify_ollama_error(exc)
        row["last_error"] = str(exc)
    row["recommendation"] = recommendation_for(row)
    row["status"] = row_status(row)
    add_legacy_model_keys(row)
    return row


def add_legacy_model_keys(row: dict) -> dict:
    row["configured_model"] = row.get("configured_name")
    row["resolved_model"] = row.get("resolved_name")
    return row


def unconfigured_installed_rows(configured_rows: list[dict], installed_models: list[str]) -> list[dict]:
    configured_resolved = {row.get("resolved_name") for row in configured_rows if row.get("resolved_name")}
    rows = []
    for model in sorted(set(installed_models) - configured_resolved):
        row = {
            "configured_name": None,
            "resolved_name": model,
            "capability": "unknown",
            "probe": None,
            "role": "installed_unconfigured",
            "installed": True,
            "resolution": "installed_unconfigured",
            "candidates": [model],
            "loadable": None,
            "healthy": None,
            "error_class": None,
            "last_error": None,
            "recommendation": "Installed in Ollama but not configured in LAIA.",
            "status": "installed",
        }
        add_legacy_model_keys(row)
        rows.append(row)
    return rows


def run_ollama_health(client=None, write: bool = False) -> dict:
    client = client or OllamaClient()
    checked_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    version = None
    server_error = None
    installed_models: list[str] = []
    list_error = None

    try:
        version_data = client.version()
        version = version_data.get("version") if isinstance(version_data, dict) else str(version_data)
    except Exception as exc:
        server_error = str(exc)

    try:
        installed_models = sorted(client.list_models())
    except Exception as exc:
        list_error = str(exc)

    probe_root = health_dir() / "health_probe"
    rows = []
    if server_error:
        for configured in CONFIGURED_MODELS:
            resolution = resolve_model_name(configured["name"], installed_models)
            row = {
                "configured_name": configured["name"],
                "resolved_name": resolution.get("resolved"),
                "capability": configured["capability"],
                "probe": row_probe_name(configured["capability"]),
                "role": configured.get("role"),
                "installed": bool(resolution.get("installed")),
                "resolution": resolution.get("resolution"),
                "candidates": resolution.get("candidates") or [],
                "loadable": False,
                "healthy": False,
                "error_class": "ollama_unavailable",
                "last_error": server_error,
            }
            row["recommendation"] = recommendation_for(row)
            row["status"] = row_status(row)
            add_legacy_model_keys(row)
            rows.append(row)
    else:
        for configured in CONFIGURED_MODELS:
            rows.append(build_model_row(configured, installed_models, client, probe_root))
    rows.extend(unconfigured_installed_rows(rows, installed_models))

    configured_rows = [row for row in rows if row.get("configured_name")]
    healthy = sum(1 for row in configured_rows if row.get("healthy"))
    failed = sum(1 for row in configured_rows if row.get("error_class") or row.get("healthy") is False)
    warnings = sum(1 for row in configured_rows if row.get("resolution") == "ambiguous_installed_tags")
    installed_count = sum(1 for row in rows if row.get("installed"))
    report = {
        "schema": HEALTH_SCHEMA_VERSION,
        "checked_at": checked_at,
        "ollama": {
            "server_available": server_error is None,
            "available": server_error is None,
            "version": version,
            "endpoint": getattr(client, "host", None),
            "host": getattr(client, "host", None),
            "checked_at": checked_at,
            "last_error": server_error,
            "list_error": list_error,
            "installed_models": installed_models,
        },
        "summary": {
            "installed_models": len(installed_models),
            "configured_models": len(CONFIGURED_MODELS),
            "healthy": healthy,
            "failed": failed,
            "warnings": warnings,
            "configured": len(configured_rows),
            "installed": installed_count,
            "unhealthy": len(configured_rows) - healthy,
        },
        "models": rows,
    }
    if write:
        write_health_report(report)
    return report


def render_health_markdown(report: dict) -> str:
    summary = report.get("summary", {})
    ollama = report.get("ollama", {})
    lines = [
        "# Ollama Model Health",
        "",
        f"Checked: {report.get('checked_at')}  ",
        f"Endpoint: {ollama.get('endpoint') or ollama.get('host') or 'unknown'}  ",
        f"Ollama version: {ollama.get('version') or 'unknown'}",
        "",
        "## Summary",
        "",
        f"Installed models: {summary.get('installed_models', 0)}  ",
        f"Configured models: {summary.get('configured_models', summary.get('configured', 0))}  ",
        f"Healthy: {summary.get('healthy', 0)}  ",
        f"Failed: {summary.get('failed', 0)}  ",
        f"Warnings: {summary.get('warnings', 0)}",
        "",
        "## Models",
        "",
        "| Model | Resolved | Capability | Installed | Loadable | Healthy | Notes |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for row in report.get("models", []):
        if not row.get("configured_name"):
            continue
        note = row.get("last_error") or row.get("error_class") or row.get("recommendation") or ""
        lines.append(
            "| {configured_name} | {resolved_name} | {capability} | {installed} | {loadable} | {healthy} | {notes} |".format(
                configured_name=row.get("configured_name") or "",
                resolved_name=row.get("resolved_name") or "",
                capability=row.get("capability") or "",
                installed="yes" if row.get("installed") else "no",
                loadable="yes" if row.get("loadable") else "no",
                healthy="yes" if row.get("healthy") else "no",
                notes=str(note).replace("|", "/"),
            )
        )
    recommendations = [row.get("recommendation") for row in report.get("models", []) if row.get("configured_name") and row.get("recommendation")]
    if recommendations:
        lines.extend(["", "## Recommendations", ""])
        for recommendation in sorted(set(recommendations)):
            lines.append(f"- {recommendation}")
    return "\n".join(lines) + "\n"


def write_health_report(report: dict) -> tuple[Path, Path]:
    health_dir().mkdir(parents=True, exist_ok=True)
    json_path = health_json_path()
    md_path = health_markdown_path()
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_health_markdown(report), encoding="utf-8")
    return json_path, md_path


def read_health_report() -> dict | None:
    path = health_json_path()
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def health_rows_by_model(report: dict | None) -> dict[str, dict]:
    rows = {}
    if not report:
        return rows
    for row in report.get("models", []):
        if row.get("configured_name"):
            rows[row["configured_name"]] = row
        if row.get("configured_model"):
            rows[row["configured_model"]] = row
        if row.get("resolved_name"):
            rows[row["resolved_name"]] = row
        if row.get("resolved_model"):
            rows[row["resolved_model"]] = row
    return rows


def print_human_report(report: dict) -> None:
    summary = report.get("summary", {})
    print("Ollama Model Health")
    print(f"  Ollama: {'available' if report.get('ollama', {}).get('server_available') else 'unavailable'}")
    print(f"  Endpoint: {report.get('ollama', {}).get('endpoint') or 'unknown'}")
    print(f"  Version: {report.get('ollama', {}).get('version') or 'unknown'}")
    print(f"  Healthy: {summary.get('healthy', 0)} / {summary.get('configured_models', summary.get('configured', 0))}")
    print()
    for row in report.get("models", []):
        if not row.get("configured_name"):
            continue
        status = "healthy" if row.get("healthy") else row.get("error_class") or "unhealthy"
        resolved = row.get("resolved_name") or "-"
        print(f"  {row.get('configured_name'):22} {row.get('capability'):10} {status:24} resolved={resolved}")


def command_ollama_health(args) -> None:
    report = run_ollama_health(write=getattr(args, "write", False))
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        print_human_report(report)
        if getattr(args, "write", False):
            print()
            print(f"Wrote {health_json_path()}")
            print(f"Wrote {health_markdown_path()}")
