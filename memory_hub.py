#!/usr/bin/env python3
"""Lightweight shared Memory Hub for DevConductor and its Codex plugin."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import sqlite3
import sys
import threading
import uuid
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from memory_client import MemoryClientError, normalize_repository_url


TOOL_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = TOOL_DIR / ".runtime" / "memory"
MAX_BODY_BYTES = 512 * 1024
SCOPES = {"private", "task", "project", "team", "global-candidate", "global"}
STATUSES = {"candidate", "active", "deprecated"}
KINDS = {"fact", "decision", "runbook", "pitfall", "acceptance", "skill", "automation", "note"}
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class HubError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean_text(value: Any, limit: int) -> str:
    return str(value or "").replace("\x00", " ").strip()[:limit]


def clean_id(value: Any, label: str, *, required: bool = True) -> str:
    result = clean_text(value, 128)
    if not result and not required:
        return ""
    if not SAFE_ID.fullmatch(result):
        raise HubError(f"{label} contains unsupported characters.")
    return result


def clean_strings(value: Any, limit: int = 20, item_limit: int = 300) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = clean_text(item, item_limit)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def memory_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HubError("Memory payload must be a JSON object.")
    team_id = clean_id(value.get("teamId"), "teamId")
    scope = clean_text(value.get("scope") or "project", 40)
    status = clean_text(value.get("status") or "active", 40)
    kind = clean_text(value.get("kind") or "note", 40)
    if scope not in SCOPES:
        raise HubError("Unsupported memory scope.")
    if status not in STATUSES:
        raise HubError("Unsupported memory status.")
    if kind not in KINDS:
        raise HubError("Unsupported memory kind.")
    project_key = clean_text(value.get("projectKey"), 512).casefold()
    repository_url = clean_text(value.get("repositoryUrl"), 1200)
    if repository_url:
        identity = normalize_repository_url(repository_url)
        if project_key and project_key != identity["projectKey"]:
            raise HubError("projectKey does not match repositoryUrl.")
        project_key = identity["projectKey"]
        repository_url = identity["repositoryUrl"]
    if scope in {"task", "project"} and not project_key:
        raise HubError(f"{scope} memories require projectKey or repositoryUrl.")
    task_id = clean_id(value.get("taskId"), "taskId", required=False)
    owner_id = clean_id(value.get("userId"), "userId", required=False)
    if scope == "task" and not task_id:
        raise HubError("task memories require taskId.")
    if scope == "private" and not owner_id:
        raise HubError("private memories require userId.")
    title = clean_text(value.get("title"), 240)
    content = clean_text(value.get("content"), 20000)
    if not title or not content:
        raise HubError("Memory title and content are required.")
    evidence = value.get("evidence") if isinstance(value.get("evidence"), list) else []
    evidence = [item for item in evidence[:12] if isinstance(item, dict)]
    source_key = clean_text(value.get("sourceKey"), 512) or None
    return {
        "team_id": team_id,
        "project_key": project_key,
        "repository_url": repository_url,
        "task_id": task_id,
        "owner_id": owner_id,
        "scope": scope,
        "kind": kind,
        "title": title,
        "content": content,
        "tags_json": json.dumps(clean_strings(value.get("tags")), ensure_ascii=False),
        "evidence_json": json.dumps(evidence, ensure_ascii=False),
        "status": status,
        "source": clean_text(value.get("source") or "manual", 80),
        "source_key": source_key,
        "created_by": clean_text(value.get("createdBy") or owner_id or "unknown", 160),
    }


class MemoryStore:
    def __init__(self, database: Path) -> None:
        self.database = database.resolve(strict=False)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.initialize()

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    team_id TEXT NOT NULL,
                    project_key TEXT NOT NULL DEFAULT '',
                    repository_url TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    owner_id TEXT NOT NULL DEFAULT '',
                    scope TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    evidence_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'manual',
                    source_key TEXT,
                    created_by TEXT NOT NULL DEFAULT 'unknown',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_memories_source
                    ON memories(team_id, source_key) WHERE source_key IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_memories_recall
                    ON memories(team_id, status, scope, project_key, task_id, owner_id);
                CREATE INDEX IF NOT EXISTS idx_memories_updated
                    ON memories(team_id, updated_at DESC);
            """)

    @staticmethod
    def row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["tags"] = json.loads(result.pop("tags_json") or "[]")
        result["evidence"] = json.loads(result.pop("evidence_json") or "[]")
        return {
            "id": result["id"],
            "teamId": result["team_id"],
            "projectKey": result["project_key"],
            "repositoryUrl": result["repository_url"],
            "taskId": result["task_id"],
            "userId": result["owner_id"],
            "scope": result["scope"],
            "kind": result["kind"],
            "title": result["title"],
            "content": result["content"],
            "tags": result["tags"],
            "evidence": result["evidence"],
            "status": result["status"],
            "source": result["source"],
            "sourceKey": result["source_key"] or "",
            "createdBy": result["created_by"],
            "createdAt": result["created_at"],
            "updatedAt": result["updated_at"],
        }

    def create(self, value: Any) -> dict[str, Any]:
        item = memory_payload(value)
        stamp = now_iso()
        with self._lock, self.connect() as connection:
            existing = None
            if item["source_key"]:
                existing = connection.execute(
                    "SELECT id, created_at FROM memories WHERE team_id = ? AND source_key = ?",
                    (item["team_id"], item["source_key"]),
                ).fetchone()
            memory_id = str(existing["id"]) if existing else str(uuid.uuid4())
            created_at = str(existing["created_at"]) if existing else stamp
            columns = [
                "team_id", "project_key", "repository_url", "task_id", "owner_id", "scope", "kind",
                "title", "content", "tags_json", "evidence_json", "status", "source", "source_key", "created_by",
            ]
            if existing:
                assignments = ", ".join(f"{column} = ?" for column in columns)
                connection.execute(
                    f"UPDATE memories SET {assignments}, updated_at = ? WHERE id = ?",
                    [*(item[column] for column in columns), stamp, memory_id],
                )
            else:
                connection.execute(
                    f"INSERT INTO memories (id, {', '.join(columns)}, created_at, updated_at) "
                    f"VALUES ({', '.join('?' for _ in range(len(columns) + 3))})",
                    [memory_id, *(item[column] for column in columns), created_at, stamp],
                )
            row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        assert row is not None
        return self.row(row)

    def read(self, memory_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if row is None:
            raise HubError("Memory not found.")
        return self.row(row)

    def set_status(self, memory_id: str, status: str) -> dict[str, Any]:
        if status not in STATUSES:
            raise HubError("Unsupported memory status.")
        with self._lock, self.connect() as connection:
            cursor = connection.execute(
                "UPDATE memories SET status = ?, updated_at = ? WHERE id = ?",
                (status, now_iso(), memory_id),
            )
            if cursor.rowcount != 1:
                raise HubError("Memory not found.")
        return self.read(memory_id)

    def search(self, value: Any) -> list[dict[str, Any]]:
        if not isinstance(value, dict):
            raise HubError("Search payload must be a JSON object.")
        team_id = clean_id(value.get("teamId"), "teamId")
        project_key = clean_text(value.get("projectKey"), 512).casefold()
        task_id = clean_id(value.get("taskId"), "taskId", required=False)
        user_id = clean_id(value.get("userId"), "userId", required=False)
        scopes = set(clean_strings(value.get("scopes"), 8, 40)) or {"project", "team", "global"}
        if not scopes.issubset(SCOPES):
            raise HubError("Search contains an unsupported scope.")
        limit = value.get("limit", 8)
        max_chars = value.get("maxChars", 6000)
        limit = max(1, min(20, limit if isinstance(limit, int) else 8))
        max_chars = max(500, min(20000, max_chars if isinstance(max_chars, int) else 6000))
        query = clean_text(value.get("query"), 4000).casefold()
        tokens = set(re.findall(r"[\w.-]{2,}", query, flags=re.UNICODE))
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE team_id = ? AND status = 'active' ORDER BY updated_at DESC LIMIT 500",
                (team_id,),
            ).fetchall()
        ranked: list[tuple[int, str, dict[str, Any]]] = []
        for raw in rows:
            item = self.row(raw)
            scope = item["scope"]
            if scope not in scopes:
                continue
            if scope == "private" and (not user_id or item["userId"] != user_id):
                continue
            if scope == "task" and (not task_id or item["taskId"] != task_id or item["projectKey"] != project_key):
                continue
            if scope == "project" and (not project_key or item["projectKey"] != project_key):
                continue
            haystack = f"{item['title']} {item['content']} {' '.join(item['tags'])}".casefold()
            score = sum(4 if token in item["title"].casefold() else 1 for token in tokens if token in haystack)
            score += {"task": 6, "project": 4, "private": 3, "team": 2, "global": 1}.get(scope, 0)
            ranked.append((score, item["updatedAt"], item))
        ranked.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        result: list[dict[str, Any]] = []
        used = 0
        for _, _, item in ranked:
            size = len(item["title"]) + len(item["content"])
            if result and used + size > max_chars:
                continue
            result.append(item)
            used += size
            if len(result) >= limit or used >= max_chars:
                break
        return result


STORE: MemoryStore
API_KEY = ""


class MemoryHandler(BaseHTTPRequestHandler):
    server_version = "DevConductorMemory/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"[{now_iso()}] {self.client_address[0]} {fmt % args}\n")

    def authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        return header.startswith("Bearer ") and secrets.compare_digest(header[7:], API_KEY)

    def send_json(self, value: Any, status: int = 200) -> None:
        body = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise HubError("Invalid Content-Length.") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise HubError("Request body is empty or too large.")
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError as exc:
            raise HubError("Request body is not valid JSON.") from exc
        if not isinstance(value, dict):
            raise HubError("Request JSON must be an object.")
        return value

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/health":
            self.send_json({"ok": True, "service": "DevConductor Memory Hub", "version": 1})
            return
        if not self.authorized():
            self.send_json({"ok": False, "error": "Invalid Memory Hub API key."}, HTTPStatus.UNAUTHORIZED)
            return
        match = re.fullmatch(r"/v1/memories/([0-9a-f-]+)", path)
        if not match:
            self.send_json({"ok": False, "error": "Unknown API."}, HTTPStatus.NOT_FOUND)
            return
        try:
            self.send_json({"ok": True, "memory": STORE.read(unquote(match.group(1)))})
        except HubError as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if not self.authorized():
            self.send_json({"ok": False, "error": "Invalid Memory Hub API key."}, HTTPStatus.UNAUTHORIZED)
            return
        path = urlparse(self.path).path
        try:
            payload = self.read_json()
            if path == "/v1/memories/search":
                self.send_json({"ok": True, "memories": STORE.search(payload)})
                return
            if path == "/v1/memories":
                self.send_json({"ok": True, "memory": STORE.create(payload)}, HTTPStatus.CREATED)
                return
            match = re.fullmatch(r"/v1/memories/([0-9a-f-]+)/status", path)
            if match:
                self.send_json({"ok": True, "memory": STORE.set_status(match.group(1), clean_text(payload.get("status"), 40))})
                return
            self.send_json({"ok": False, "error": "Unknown API."}, HTTPStatus.NOT_FOUND)
        except (HubError, MemoryClientError) as exc:
            self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)


def load_api_key(host: str, api_key_file: Path) -> str:
    value = str(os.environ.get("DEVCONDUCTOR_MEMORY_API_KEY") or "").strip()
    if value:
        return value
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise HubError("A non-loopback Memory Hub requires DEVCONDUCTOR_MEMORY_API_KEY.")
    try:
        existing = api_key_file.read_text(encoding="utf-8").strip()
    except OSError:
        existing = ""
    if existing:
        return existing
    api_key_file.parent.mkdir(parents=True, exist_ok=True)
    value = secrets.token_urlsafe(32)
    temporary = api_key_file.with_suffix(".tmp")
    temporary.write_text(value + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    temporary.replace(api_key_file)
    return value


def main() -> int:
    global STORE, API_KEY
    parser = argparse.ArgumentParser(description="Run the DevConductor shared Memory Hub.")
    parser.add_argument("--host", default=os.environ.get("DEVCONDUCTOR_MEMORY_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("DEVCONDUCTOR_MEMORY_PORT", "4328")))
    parser.add_argument("--database", type=Path, default=Path(os.environ.get("DEVCONDUCTOR_MEMORY_DB", str(DEFAULT_DATA_DIR / "memory.db"))))
    parser.add_argument("--api-key-file", type=Path, default=Path(os.environ.get("DEVCONDUCTOR_MEMORY_API_KEY_FILE", str(DEFAULT_DATA_DIR / "api-key"))))
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("Memory Hub port must be between 1024 and 65535.")
    try:
        API_KEY = load_api_key(args.host, args.api_key_file.expanduser())
    except HubError as exc:
        raise SystemExit(str(exc)) from exc
    STORE = MemoryStore(args.database.expanduser())
    server = ThreadingHTTPServer((args.host, args.port), MemoryHandler)
    print(f"DevConductor Memory Hub: http://{args.host}:{args.port}")
    print(f"Database: {STORE.database}")
    print("Real memory data and API keys remain outside Git under .runtime by default.")
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
