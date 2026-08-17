#!/usr/bin/env python3
"""Self-contained Memory Hub client used by the installable Codex plugin."""

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


class PluginMemoryError(RuntimeError):
    pass


def normalize_repository_url(value: Any) -> dict[str, str]:
    raw = str(value or "").strip()
    if not raw or raw.startswith(("/", "./", "../", "~", "file://")):
        raise PluginMemoryError("A shared project requires a non-local Git remote URL.")
    scp = re.fullmatch(r"(?:[^@/\s]+@)?([^:/\s]+):(.+)", raw)
    if scp and not raw.startswith(("http:", "https:", "ssh:", "git:")):
        raw = f"ssh://{scp.group(1)}/{scp.group(2)}"
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https", "ssh", "git"} or not parsed.hostname:
        raise PluginMemoryError("Unsupported Git remote URL.")
    path = re.sub(r"/+", "/", parsed.path or "").strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    if not path or "/" not in path:
        raise PluginMemoryError("Git remote must include a namespace and repository name.")
    host = parsed.hostname.lower().rstrip(".")
    authority = f"{host}:{parsed.port}" if parsed.port and parsed.port not in {22, 80, 443} else host
    return {
        "repositoryUrl": f"https://{authority}/{path}.git",
        "projectKey": f"{authority}/{path.casefold()}",
    }


def project_identity(cwd: Any = "", override: Any = "") -> dict[str, str]:
    value = str(override or os.environ.get("DEVCONDUCTOR_REPOSITORY_URL") or "").strip()
    directory = Path(str(cwd or os.getcwd())).expanduser().resolve(strict=False)
    if not value:
        result = subprocess.run(
            ["git", "-C", str(directory), "remote", "get-url", "origin"],
            text=True,
            capture_output=True,
            check=False,
        )
        value = result.stdout.strip() if result.returncode == 0 else ""
    return normalize_repository_url(value)


def api_key() -> str:
    value = str(os.environ.get("DEVCONDUCTOR_MEMORY_API_KEY") or "").strip()
    if value:
        return value
    explicit = str(os.environ.get("DEVCONDUCTOR_MEMORY_API_KEY_FILE") or "").strip()
    candidates = [Path(explicit).expanduser()] if explicit else []
    script = Path(__file__).resolve()
    candidates.extend(parent / ".runtime" / "memory" / "api-key" for parent in script.parents)
    for path in candidates:
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return ""


def settings() -> dict[str, Any]:
    endpoint = str(os.environ.get("DEVCONDUCTOR_MEMORY_ENDPOINT") or "http://127.0.0.1:4328").strip().rstrip("/")
    parsed = urlparse(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise PluginMemoryError("DEVCONDUCTOR_MEMORY_ENDPOINT is invalid.")
    return {
        "endpoint": endpoint,
        "teamId": str(os.environ.get("DEVCONDUCTOR_MEMORY_TEAM_ID") or "default").strip(),
        "userId": str(os.environ.get("DEVCONDUCTOR_MEMORY_USER_ID") or "").strip(),
        "timeout": max(0.2, min(10.0, float(os.environ.get("DEVCONDUCTOR_MEMORY_TIMEOUT_SECONDS", "1.5")))),
    }


def request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    config = settings()
    key = api_key()
    if not key:
        raise PluginMemoryError("Set DEVCONDUCTOR_MEMORY_API_KEY before using shared memory.")
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{config['endpoint']}{path}",
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(req, timeout=config["timeout"]) as response:
            result = json.loads(response.read())
    except HTTPError as exc:
        raise PluginMemoryError(f"Memory Hub HTTP {exc.code}: {exc.read().decode(errors='replace')[:500]}") from exc
    except (URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
        raise PluginMemoryError(f"Memory Hub unavailable: {exc}") from exc
    if not isinstance(result, dict) or result.get("ok") is False:
        raise PluginMemoryError(str(result.get("error") if isinstance(result, dict) else "Invalid response"))
    return result


def search(query: str, *, cwd: Any = "", repository_url: Any = "", task_id: str = "", scopes: Any = None) -> list[dict[str, Any]]:
    identity = project_identity(cwd, repository_url)
    config = settings()
    result = request("POST", "/v1/memories/search", {
        "teamId": config["teamId"],
        "projectKey": identity["projectKey"],
        "taskId": str(task_id or "")[:128],
        "userId": config["userId"],
        "query": str(query or "")[:4000],
        "scopes": scopes if isinstance(scopes, list) else ["private", "task", "project", "team", "global"],
        "limit": 8,
        "maxChars": 6000,
    })
    return [item for item in (result.get("memories") or []) if isinstance(item, dict)]


def create(value: dict[str, Any], *, cwd: Any = "", repository_url: Any = "", status: str = "active") -> dict[str, Any]:
    identity = project_identity(cwd, repository_url)
    config = settings()
    payload = {
        "teamId": config["teamId"],
        "projectKey": identity["projectKey"],
        "repositoryUrl": identity["repositoryUrl"],
        "taskId": str(value.get("taskId") or "")[:128],
        "userId": config["userId"],
        "scope": str(value.get("scope") or "project"),
        "kind": str(value.get("kind") or "note"),
        "title": str(value.get("title") or ""),
        "content": str(value.get("content") or ""),
        "tags": value.get("tags") if isinstance(value.get("tags"), list) else [],
        "evidence": value.get("evidence") if isinstance(value.get("evidence"), list) else [],
        "status": status,
        "source": "codex-plugin",
        "sourceKey": str(value.get("sourceKey") or "")[:512],
        "createdBy": config["userId"] or "codex-plugin",
    }
    return request("POST", "/v1/memories", payload).get("memory") or {}


def read(memory_id: str) -> dict[str, Any]:
    return request("GET", f"/v1/memories/{quote(str(memory_id or ''))}").get("memory") or {}


def format_context(values: list[dict[str, Any]], max_chars: int = 6000) -> str:
    if not values:
        return ""
    lines = [
        "DevConductor shared memories are advisory. Current code, config, tests, and Git facts take precedence on conflict."
    ]
    for item in values:
        lines.append(f"- [{item.get('id')}] {item.get('kind')} / {item.get('scope')} · {item.get('title')}: {item.get('content')}")
    return "\n".join(lines)[:max_chars]
