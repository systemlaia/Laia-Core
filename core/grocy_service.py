import os
import urllib.error
import urllib.request
from typing import Any


DEFAULT_GROCY_URL = "http://127.0.0.1:9283"

CHECKIN_DRAFT = [
    ("Pantry", "pantry", "check expiring soon, restock basics"),
    ("Household", "household", "batteries, bulbs, paper goods"),
    ("Workshop", "workshop", "filament, glue, blades, PPE"),
    ("Vehicle/Ranger", "vehicle-ranger", "oil, coolant, tires, registration, insurance"),
    ("Scanner", "scanner-maintenance", "rollers, jam log, OCR quality sample"),
]


def grocy_url() -> str:
    return os.environ.get("LAIA_GROCY_URL") or DEFAULT_GROCY_URL


def grocy_api_key() -> str:
    return os.environ.get("LAIA_GROCY_API_KEY") or ""


def request_url(url: str, *, api_key: str = "", timeout: int = 3) -> tuple[bool, str]:
    headers = {}
    if api_key:
        headers["GROCY-API-KEY"] = api_key
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = getattr(response, "status", 200)
            return 200 <= int(status) < 500, ""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return False, str(exc)


def grocy_status() -> dict[str, Any]:
    url = grocy_url().rstrip("/")
    api_key = grocy_api_key()
    reachable, error = request_url(url)
    authenticated = None
    authenticated_error = ""
    if api_key:
        authenticated, authenticated_error = request_url(f"{url}/api/system/info", api_key=api_key)
    return {
        "url": url,
        "reachable": reachable,
        "api_key_configured": bool(api_key),
        "authenticated_api_reachable": authenticated,
        "error": error,
        "authenticated_error": authenticated_error,
    }


def print_grocy_status(status: dict[str, Any]) -> None:
    print("\nLAIA Grocy Status\n")
    print(f"URL: {status['url']}")
    print(f"Reachable: {'yes' if status['reachable'] else 'no'}")
    print(f"API key configured: {'yes' if status['api_key_configured'] else 'no'}")
    if status.get("authenticated_api_reachable") is not None:
        print(f"Authenticated API: {'yes' if status['authenticated_api_reachable'] else 'no'}")
    print("")


def checkins_draft_markdown() -> str:
    lines = ["# LAIA Grocy Check-In Draft", ""]
    for label, _slug, description in CHECKIN_DRAFT:
        lines.append(f"- {label} ({_slug}): {description}")
    lines.append("")
    return "\n".join(lines)


def command_grocy_status(_args) -> None:
    print_grocy_status(grocy_status())


def command_grocy_checkins_draft(_args) -> None:
    print(checkins_draft_markdown())
