#!/usr/bin/env python3
"""Small standard-library client for the DevConductor Memory Hub."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen


TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_ENDPOINT = "http://127.0.0.1:4328"
DEFAULT_API_KEY_ENV = "DEVCONDUCTOR_MEMORY_API_KEY"
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class MemoryClientError(RuntimeError):
    pass


def _scp_remote(value: str) -> str:
    match = re.fullmatch(r"(?:[^@/\s]+@)?([^:/\s]+):(.+)", value)
    if not match or value.startswith(("http:", "https:", "ssh:", "git:")):
        return value
    return f"ssh://{match.group(1)}/{match.group(2)}"


def normalize_repository_url(value: Any) -> dict[str, str]:
    """Return a path-independent canonical Git URL and shared project key."""
    raw = str(value or "").strip()
    if not raw:
        raise MemoryClientError("Git repository URL is empty.")
    if raw.startswith(("/", "./", "../", "~", "file://")) or re.fullmatch(r"[A-Za-z]:[\\/].*", raw):
        raise MemoryClientError("Local filesystem paths cannot be used as shared project identity.")
    parsed = urlparse(_scp_remote(raw))
    if parsed.scheme not in {"http", "https", "ssh", "git"} or not parsed.hostname:
        raise MemoryClientError("repositoryUrl must be an http(s), ssh, git, or scp-style Git remote.")
    path = re.sub(r"/+", "/", parsed.path or "").strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path or "/" not in path or any(part in {".", ".."} for part in path.split("/")):
        raise MemoryClientError("repositoryUrl must include a repository namespace and name.")
    host = parsed.hostname.lower().rstrip(".")
    port = parsed.port
    authority = f"{host}:{port}" if port and port not in {22, 80, 443} else host
    project_path = path.casefold()
    project_key = f"{authority}/{project_path}"
    return {
        "repositoryUrl": f"https://{authority}/{path}.git",
        "projectKey": project_key,
    }


def git_origin(repo: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), "remote", "get-url", "origin"],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def resolve_repository_identity(repo: Path, override: Any = "") -> dict[str, str]:
    explicit = str(override or "").strip()
    value = explicit or git_origin(repo)
    if not value:
        return {"repositoryUrl": "", "projectKey": ""}
    try:
        return normalize_repository_url(value)
    except MemoryClientError:
        if explicit:
            raise
        return {"repositoryUrl": "", "projectKey": ""}


def validate_memory_settings(value: Any, *, project_key: str) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    enabled = bool(raw.get("enabled", bool(project_key))) and bool(project_key)
    endpoint = str(raw.get("endpoint") or DEFAULT_ENDPOINT).strip().rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path not in {"", "/"}:
        raise MemoryClientError("memory.endpoint must be an http(s) server origin without a path.")
    team_id = str(raw.get("teamId") or "default").strip()
    api_key_env = str(raw.get("apiKeyEnv") or DEFAULT_API_KEY_ENV).strip()
    if not SAFE_ID.fullmatch(team_id):
        raise MemoryClientError("memory.teamId contains unsupported characters.")
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{2,127}", api_key_env):
        raise MemoryClientError("memory.apiKeyEnv must be a safe environment variable name.")

    def bounded(name: str, default: int, low: int, high: int) -> int:
        number = raw.get(name, default)
        if not isinstance(number, int):
            raise MemoryClientError(f"memory.{name} must be an integer.")
        return max(low, min(high, number))

    return {
        "enabled": enabled,
        "endpoint": endpoint,
        "teamId": team_id,
        "apiKeyEnv": api_key_env,
        "maxItems": bounded("maxItems", 8, 1, 20),
        "maxChars": bounded("maxChars", 6000, 500, 20000),
        "timeoutMs": bounded("timeoutMs", 1500, 200, 10000),
    }


def _default_api_key_file() -> Path:
    configured = str(os.environ.get("DEVCONDUCTOR_MEMORY_API_KEY_FILE") or "").strip()
    return Path(configured).expanduser() if configured else TOOL_DIR / ".runtime" / "memory" / "api-key"


class MemoryClient:
    def __init__(self, settings: dict[str, Any]) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.get("enabled"))

    def api_key(self) -> str:
        name = str(self.settings.get("apiKeyEnv") or DEFAULT_API_KEY_ENV)
        value = str(os.environ.get(name) or "").strip()
        if value:
            return value
        path = _default_api_key_file()
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.enabled:
            raise MemoryClientError("Shared memory is disabled for this project.")
        key = self.api_key()
        if not key:
            raise MemoryClientError(f"Memory Hub API key is missing; set {self.settings['apiKeyEnv']}.")
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = Request(
            f"{self.settings['endpoint']}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.settings["timeoutMs"] / 1000) as response:
                result = json.loads(response.read())
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise MemoryClientError(f"Memory Hub HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise MemoryClientError(f"Memory Hub unavailable: {exc}") from exc
        if not isinstance(result, dict) or result.get("ok") is False:
            raise MemoryClientError(str(result.get("error") if isinstance(result, dict) else "Invalid Memory Hub response"))
        return result

    def search(
        self,
        *,
        project_key: str,
        query: str,
        stage: str,
        task_id: str = "",
        user_id: str = "",
    ) -> list[dict[str, Any]]:
        result = self.request("POST", "/v1/memories/search", {
            "teamId": self.settings["teamId"],
            "projectKey": project_key,
            "taskId": task_id,
            "userId": user_id,
            "query": str(query or "")[:4000],
            "stage": str(stage or "")[:80],
            "scopes": ["private", "task", "project", "team", "global"],
            "limit": self.settings["maxItems"],
            "maxChars": self.settings["maxChars"],
        })
        values = result.get("memories") or []
        return [item for item in values if isinstance(item, dict)]

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/v1/memories", payload).get("memory") or {}

    def read(self, memory_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/memories/{quote(memory_id)}").get("memory") or {}

    def set_status(self, memory_id: str, status: str) -> dict[str, Any]:
        if status not in {"active", "candidate", "deprecated"}:
            raise MemoryClientError("Unsupported Memory status.")
        return self.request("POST", f"/v1/memories/{quote(memory_id)}/status", {"status": status}).get("memory") or {}
