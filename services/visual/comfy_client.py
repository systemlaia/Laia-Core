#!/usr/bin/env python3
"""
LAIA ComfyUI Client

Small boundary layer between LAIA Core and ComfyUI.
Keeps ComfyUI API details out of the rest of the codebase.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from typing import Any


DEFAULT_SERVER = "http://127.0.0.1:8188"


class ComfyClient:
    def __init__(self, server: str = DEFAULT_SERVER):
        self.server = server.rstrip("/")
        self.client_id = str(uuid.uuid4())

    def _get(self, path: str) -> Any:
        url = f"{self.server}{path}"
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode("utf-8"))

    def _post(self, path: str, payload: dict[str, Any]) -> Any:
        url = f"{self.server}{path}"
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} from {url}: {body}") from e

    def health(self) -> bool:
        try:
            self._get("/system_stats")
            return True
        except Exception:
            return False

    def system_stats(self) -> Any:
        return self._get("/system_stats")

    def queue_workflow(self, workflow: dict[str, Any]) -> str:
        payload = {
            "prompt": workflow,
            "client_id": self.client_id,
        }
        result = self._post("/prompt", payload)

        if "prompt_id" not in result:
            raise RuntimeError(f"ComfyUI did not return prompt_id: {result}")

        return result["prompt_id"]

    def queue_workflow_file(self, workflow_path: Path) -> str:
        workflow = json.loads(workflow_path.read_text())
        return self.queue_workflow(workflow)

    def history(self, prompt_id: str | None = None) -> Any:
        if prompt_id:
            return self._get(f"/history/{prompt_id}")
        return self._get("/history")

    def wait_for_prompt(
        self,
        prompt_id: str,
        timeout_seconds: int = 300,
        poll_seconds: float = 2.0,
    ) -> Any:
        start = time.time()

        while time.time() - start < timeout_seconds:
            history = self.history(prompt_id)
            if prompt_id in history:
                return history[prompt_id]
            time.sleep(poll_seconds)

        raise TimeoutError(f"Timed out waiting for prompt {prompt_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="LAIA ComfyUI client")
    parser.add_argument("--server", default=DEFAULT_SERVER)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("ping")
    sub.add_parser("stats")

    queue_parser = sub.add_parser("queue")
    queue_parser.add_argument("workflow", type=Path)
    queue_parser.add_argument("--wait", action="store_true")

    args = parser.parse_args()
    client = ComfyClient(args.server)

    if args.command == "ping":
        if client.health():
            print("ComfyUI: ONLINE")
        else:
            print("ComfyUI: OFFLINE")
            raise SystemExit(1)

    elif args.command == "stats":
        print(json.dumps(client.system_stats(), indent=2))

    elif args.command == "queue":
        prompt_id = client.queue_workflow_file(args.workflow)
        print(f"Queued workflow: {prompt_id}")

        if args.wait:
            result = client.wait_for_prompt(prompt_id)
            print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
