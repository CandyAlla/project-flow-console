#!/usr/bin/env python3
"""Local multi-project hub for isolated DevConductor project workers."""

from __future__ import annotations

import argparse
import http.client
import json
import mimetypes
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlparse

import server as controller


TOOL_DIR = Path(__file__).resolve().parent
PROFILE_DIR = TOOL_DIR / "profiles"
RUNTIME_ROOT = TOOL_DIR / ".runtime" / "hub"
REGISTRY_PATH = RUNTIME_ROOT / "projects.json"
SETUP_SCRIPT = TOOL_DIR / "skills" / "project-flow-setup" / "scripts" / "configure_project.py"
SERVER_SCRIPT = TOOL_DIR / "server.py"
MAX_BODY_BYTES = 12 * 1024 * 1024
HUB_TOKEN = secrets.token_urlsafe(32)
PROJECT_ROUTE = re.compile(r"/api/projects/([a-z0-9]+(?:-[a-z0-9]+)*)(/.*)?")
PROJECT_HTML_ROUTE = re.compile(r"/projects/([a-z0-9]+(?:-[a-z0-9]+)*)/task-html/(.+)")
HUB_PROJECT_ACTION_ROUTE = re.compile(
    r"/api/hub/projects/([a-z0-9]+(?:-[a-z0-9]+)*)/(config|open)"
)
PROJECT_CONFIG_FIELDS = (
    "name",
    "repositoryUrl",
    "workspaceRoot",
    "repoRoot",
    "docsRoot",
    "worktreesRoot",
    "htmlTaskRoot",
    "defaultBaseBranch",
    "worktreeNamePrefix",
)


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_log(value: Any, limit: int = 2000) -> str:
    return re.sub(r"\s+", " ", str(value or "").replace("\x00", " ")).strip()[:limit]


def bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(os.environ.get(name, str(default)))))
    except ValueError:
        return default


def task_state(task: dict[str, Any]) -> str:
    if task.get("archivedAt"):
        return "archived"
    if task.get("activeJob"):
        return "queued" if task.get("jobState") == "queued" else "running"
    if task.get("git", {}).get("committed"):
        return "done"
    sections = [task.get(name) for name in ("discussion", "plan", "worktree", "execution")]
    if any(isinstance(section, dict) and section.get("status") in {"error", "interrupted"} for section in sections):
        return "error"
    return "attention"


def runtime_summary(project_id: str, runtime_base: Path = TOOL_DIR / ".runtime") -> dict[str, int]:
    counts = {
        "total": 0, "active": 0, "running": 0, "queued": 0,
        "attention": 0, "done": 0, "archived": 0, "knowledgePending": 0,
    }
    task_root = runtime_base / project_id / "tasks"
    for path in task_root.glob("*/task.json"):
        try:
            task = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(task, dict):
            continue
        state = task_state(task)
        counts["total"] += 1
        if state == "archived":
            counts["archived"] += 1
        else:
            counts["active"] += 1
            if state in counts:
                counts[state] += 1
        candidates = task.get("knowledge", {}).get("candidates") or []
        counts["knowledgePending"] += sum(
            1 for item in candidates if isinstance(item, dict) and item.get("status") == "pending"
        )
    return counts


class ProjectRegistry:
    def __init__(
        self,
        profiles_dir: Path = PROFILE_DIR,
        registry_path: Path = REGISTRY_PATH,
        runtime_base: Path = TOOL_DIR / ".runtime",
    ) -> None:
        self.profiles_dir = profiles_dir.resolve()
        self.registry_path = registry_path.resolve()
        self.runtime_base = runtime_base.resolve()
        self._lock = threading.RLock()

    def _registered_paths(self) -> list[Path]:
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []
        values = payload.get("profiles") if isinstance(payload, dict) else []
        if not isinstance(values, list):
            return []
        result: list[Path] = []
        for value in values:
            path = Path(str(value or "")).expanduser()
            if path.is_absolute():
                result.append(path.resolve(strict=False))
        return result

    def _candidate_paths(self) -> list[Path]:
        local = [path.resolve() for path in self.profiles_dir.glob("*.json") if path.name != "example.json"]
        return list(dict.fromkeys([*local, *self._registered_paths()]))

    def discover(self) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
        projects: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        seen: dict[str, Path] = {}
        with self._lock:
            for path in self._candidate_paths():
                try:
                    profile = controller.load_project_profile(path)
                    project_id = profile["id"]
                    if project_id in seen and seen[project_id] != path:
                        raise controller.WorkflowError(
                            f"项目 id {project_id} 与 {seen[project_id]} 重复。"
                        )
                    seen[project_id] = path
                    projects.append({
                        "id": project_id,
                        "name": profile["name"],
                        "profilePath": str(path),
                        "workspaceRoot": profile["workspaceRoot"],
                        "repoRoot": profile["repoRoot"],
                        "repositoryUrl": profile.get("repositoryUrl", ""),
                        "repositoryKey": profile.get("repositoryKey", ""),
                        "memory": profile.get("memory", {}),
                        "docsRoot": profile["docsRoot"],
                        "worktreesRoot": profile["worktreesRoot"],
                        "htmlTaskRoot": profile["htmlTaskRoot"],
                        "defaultBaseBranch": profile["defaultBaseBranch"],
                        "worktreeNamePrefix": profile["worktreeNamePrefix"],
                        "counts": runtime_summary(project_id, self.runtime_base),
                    })
                except (controller.WorkflowError, OSError) as exc:
                    errors.append({"profilePath": str(path), "error": safe_log(exc)})
        projects.sort(key=lambda item: (item["name"].casefold(), item["id"]))
        return projects, errors

    def get(self, project_id: str) -> dict[str, Any]:
        projects, _ = self.discover()
        for project in projects:
            if project["id"] == project_id:
                return project
        raise controller.WorkflowError(f"项目未注册或 Profile 无效：{project_id}")

    def _write_registered_paths(self, paths: list[Path]) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        target = self.registry_path
        temporary = target.with_suffix(".tmp")
        payload = {"schemaVersion": 1, "profiles": [str(path) for path in paths]}
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(target)

    def register_profile(self, profile_path: Path | str) -> dict[str, Any]:
        path = Path(profile_path).expanduser()
        if not path.is_absolute():
            raise controller.WorkflowError("Project Profile 路径必须是绝对路径。")
        path = path.resolve(strict=False)
        profile = controller.load_project_profile(path)
        with self._lock:
            registered = self._registered_paths()
            if not path.is_relative_to(self.profiles_dir) and path not in registered:
                registered.append(path)
                self._write_registered_paths(registered)
        return {**profile, "profilePath": str(path)}

    def update_project(self, project_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        project = self.get(project_id)
        profile_path = Path(project["profilePath"])
        try:
            original = json.loads(profile_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise controller.WorkflowError(f"Project Profile 不是有效 JSON：{exc}") from exc
        if not isinstance(original, dict):
            raise controller.WorkflowError("Project Profile 顶层必须是 JSON 对象。")
        if str(original.get("id") or "") != project_id:
            raise controller.WorkflowError("项目 ID 与注册的 Project Profile 不一致。")

        updated = dict(original)
        for field in PROJECT_CONFIG_FIELDS:
            if field in payload:
                updated[field] = payload[field]
        updated["id"] = project_id
        validated = controller.validate_project_profile(updated)

        with self._lock:
            temporary = profile_path.with_name(f".{profile_path.name}.tmp")
            try:
                temporary.write_text(
                    json.dumps(validated, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                temporary.replace(profile_path)
            finally:
                if temporary.exists():
                    temporary.unlink()
        return {**validated, "profilePath": str(profile_path)}

    def open_project_directory(self, project_id: str, target: str = "repo") -> Path:
        if target != "repo":
            raise controller.WorkflowError("只允许打开项目 Profile 中配置的本地仓库目录。")
        directory = Path(self.get(project_id)["repoRoot"]).resolve(strict=False)
        if not directory.is_dir():
            raise controller.WorkflowError(f"本地仓库目录不存在：{directory}")
        if sys.platform == "darwin":
            command = ["open", str(directory)]
        elif sys.platform == "win32":
            command = ["explorer", str(directory)]
        else:
            command = ["xdg-open", str(directory)]
        subprocess.Popen(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return directory

    def setup_project(self, payload: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
        profile_path = str(payload.get("profilePath") or "").strip()
        if profile_path:
            path = Path(profile_path).expanduser()
            if not path.is_absolute():
                raise controller.WorkflowError("Project Profile 路径必须是绝对路径。")
            profile = controller.load_project_profile(path)
            if not dry_run:
                self.register_profile(path)
            return {"profile": profile, "profilePath": str(path.resolve()), "warnings": []}

        repo_root = str(payload.get("repoRoot") or "").strip()
        repo = Path(repo_root).expanduser()
        if not repo_root or not repo.is_absolute():
            raise controller.WorkflowError("Git 项目根目录必须是绝对路径。")
        command = [
            sys.executable, str(SETUP_SCRIPT), str(repo.resolve(strict=False)),
            "--profiles-dir", str(self.profiles_dir),
        ]
        name = str(payload.get("name") or "").strip()
        project_id = str(payload.get("id") or "").strip()
        repository_url = str(payload.get("repositoryUrl") or "").strip()
        if name:
            command.extend(["--name", name])
        if project_id:
            command.extend(["--id", project_id])
        if repository_url:
            command.extend(["--repository-url", repository_url])
        if dry_run:
            command.append("--dry-run")
        result = subprocess.run(command, cwd=TOOL_DIR, text=True, capture_output=True, check=False, timeout=30)
        if result.returncode != 0:
            raise controller.WorkflowError(safe_log(result.stderr or result.stdout or "项目扫描失败。"))
        try:
            profile, _ = json.JSONDecoder().raw_decode(result.stdout)
        except json.JSONDecodeError as exc:
            raise controller.WorkflowError("项目配置脚本没有返回有效 Profile。") from exc
        target_match = re.search(r"^Profile target:\s*(.+)$", result.stdout, re.MULTILINE)
        target = Path(target_match.group(1).strip()) if target_match else self.profiles_dir / f"{profile['id']}.json"
        warnings = [line.strip() for line in result.stderr.splitlines() if line.strip()]
        if not dry_run:
            self.register_profile(target)
        return {"profile": profile, "profilePath": str(target.resolve(strict=False)), "warnings": warnings}


class ProjectWorker:
    def __init__(self, project: dict[str, Any], port: int, process: subprocess.Popen[bytes], log_file: Any) -> None:
        self.project = project
        self.port = port
        self.process = process
        self.log_file = log_file
        self.token = ""

    @property
    def running(self) -> bool:
        return self.process.poll() is None

    def close(self) -> None:
        if self.running:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2)
        self.log_file.close()


class WorkerManager:
    def __init__(self, registry: ProjectRegistry, runtime_root: Path = RUNTIME_ROOT) -> None:
        self.registry = registry
        self.runtime_root = runtime_root.resolve()
        self._workers: dict[str, ProjectWorker] = {}
        self._lock = threading.RLock()
        self.project_concurrency = bounded_env_int("PROJECT_FLOW_PROJECT_CONCURRENCY", 2, 1, 4)
        self.global_concurrency = bounded_env_int("PROJECT_FLOW_GLOBAL_CONCURRENCY", 4, 1, 16)

    @staticmethod
    def _free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            return int(probe.getsockname()[1])

    @staticmethod
    def _connection(port: int, timeout: float = 30) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)

    def _start(self, project_id: str) -> ProjectWorker:
        project = self.registry.get(project_id)
        port = self._free_port()
        log_root = self.runtime_root / "logs"
        log_root.mkdir(parents=True, exist_ok=True)
        log_file = (log_root / f"{project_id}.log").open("ab", buffering=0)
        environment = os.environ.copy()
        environment.update({
            "PROJECT_FLOW_PROFILE": project["profilePath"],
            "PROJECT_FLOW_CONCURRENCY": str(self.project_concurrency),
            "PROJECT_FLOW_GLOBAL_CONCURRENCY": str(self.global_concurrency),
            "PROJECT_FLOW_GLOBAL_SLOT_DIR": str(self.runtime_root / "job-slots"),
            "PROJECT_FLOW_RUNTIME_BASE": str(self.runtime_root.parent),
        })
        process = subprocess.Popen(
            [sys.executable, str(SERVER_SCRIPT), "--profile", project["profilePath"], "--port", str(port)],
            cwd=TOOL_DIR,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
        worker = ProjectWorker(project, port, process, log_file)
        deadline = time.monotonic() + 12
        last_error = "Worker 启动超时。"
        while time.monotonic() < deadline and worker.running:
            try:
                status, _, body = self._raw_request(worker, "GET", "/api/health", b"", {})
                if status == 200:
                    payload = json.loads(body)
                    worker.token = str(payload.get("token") or "")
                    if worker.token:
                        return worker
            except (ConnectionError, OSError, json.JSONDecodeError, http.client.HTTPException) as exc:
                last_error = safe_log(exc)
            time.sleep(0.1)
        if not worker.running:
            try:
                log_lines = Path(worker.log_file.name).read_text(encoding="utf-8", errors="replace").splitlines()
                last_error = safe_log(" ".join(log_lines[-8:])) or last_error
            except OSError:
                pass
        worker.close()
        raise controller.WorkflowError(f"{project['name']} Worker 启动失败：{last_error}")

    def ensure(self, project_id: str) -> ProjectWorker:
        with self._lock:
            worker = self._workers.get(project_id)
            if worker and worker.running:
                return worker
            if worker:
                worker.close()
                self._workers.pop(project_id, None)
            worker = self._start(project_id)
            self._workers[project_id] = worker
            return worker

    def status(self, project_id: str) -> str:
        with self._lock:
            worker = self._workers.get(project_id)
            if not worker:
                return "stopped"
            return "running" if worker.running else "error"

    def configuration_pending(self, project: dict[str, Any]) -> bool:
        with self._lock:
            worker = self._workers.get(project["id"])
            if not worker or not worker.running:
                return False
            return any(worker.project.get(field) != project.get(field) for field in PROJECT_CONFIG_FIELDS)

    def _raw_request(
        self, worker: ProjectWorker, method: str, path: str, body: bytes, headers: dict[str, str]
    ) -> tuple[int, dict[str, str], bytes]:
        connection = self._connection(worker.port)
        try:
            connection.request(method, path, body=body or None, headers=headers)
            response = connection.getresponse()
            return response.status, {key: value for key, value in response.getheaders()}, response.read()
        finally:
            connection.close()

    def request(
        self, project_id: str, method: str, path: str, body: bytes = b"", content_type: str = "application/json"
    ) -> tuple[int, dict[str, str], bytes]:
        worker = self.ensure(project_id)
        headers = {"Host": f"127.0.0.1:{worker.port}"}
        if content_type:
            headers["Content-Type"] = content_type
        if path != "/api/health":
            headers["X-Requirement-Flow-Token"] = worker.token
        return self._raw_request(worker, method, path, body, headers)

    def stop_all(self) -> None:
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.close()


REGISTRY = ProjectRegistry()
WORKERS = WorkerManager(REGISTRY)


def rewrite_project_urls(value: Any, project_id: str) -> Any:
    if isinstance(value, dict):
        return {key: rewrite_project_urls(item, project_id) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_project_urls(item, project_id) for item in value]
    if isinstance(value, str) and value.startswith("/task-html/"):
        return f"/projects/{quote(project_id)}/task-html/{value.removeprefix('/task-html/')}"
    return value


def worker_json(project_id: str, method: str, path: str, body: bytes = b"") -> tuple[int, dict[str, Any]]:
    status, _, raw = WORKERS.request(project_id, method, path, body)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise controller.WorkflowError(f"{project_id} Worker 返回了无效 JSON。") from exc
    if path == "/api/health" and isinstance(payload, dict):
        payload["token"] = HUB_TOKEN
        payload.setdefault("features", {})["multiProjectHub"] = True
    return status, rewrite_project_urls(payload, project_id)


def projects_payload() -> dict[str, Any]:
    projects, errors = REGISTRY.discover()
    for project in projects:
        project["workerState"] = WORKERS.status(project["id"])
        project["configurationPending"] = WORKERS.configuration_pending(project)
    return {
        "ok": True,
        "service": "DevConductor Project Hub",
        "token": HUB_TOKEN,
        "projects": projects,
        "errors": errors,
        "scheduler": {
            "globalMaxConcurrentJobs": WORKERS.global_concurrency,
            "projectMaxConcurrentJobs": WORKERS.project_concurrency,
            "runningJobs": sum(project["counts"]["running"] for project in projects),
            "queuedJobs": sum(project["counts"]["queued"] for project in projects),
        },
    }


def aggregate_payload(endpoint: str, key: str) -> dict[str, Any]:
    projects, errors = REGISTRY.discover()
    values: list[dict[str, Any]] = []
    for project in projects:
        try:
            status, payload = worker_json(project["id"], "GET", endpoint)
            if status != 200 or payload.get("ok") is False:
                raise controller.WorkflowError(payload.get("error") or f"HTTP {status}")
            for value in payload.get(key) or []:
                if isinstance(value, dict):
                    values.append({**value, "projectId": project["id"], "projectName": project["name"]})
        except (controller.WorkflowError, OSError, http.client.HTTPException) as exc:
            errors.append({"profilePath": project["profilePath"], "error": safe_log(exc)})
    if key == "tasks":
        values.sort(key=lambda item: str(item.get("updatedAt") or ""), reverse=True)
    else:
        values.sort(key=lambda item: str(item.get("createdAt") or item.get("updatedAt") or ""), reverse=True)
    return {"ok": True, key: values, "projects": projects, "errors": errors, "scheduler": projects_payload()["scheduler"]}


class HubHandler(BaseHTTPRequestHandler):
    server_version = "DevConductorHub/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write(f"[{now_iso()}] {self.client_address[0]} {fmt % args}\n")

    def host_allowed(self) -> bool:
        host = self.headers.get("Host", "").split(":", 1)[0].strip("[]").lower()
        return host in {"127.0.0.1", "localhost", "::1"}

    def token_allowed(self) -> bool:
        return secrets.compare_digest(self.headers.get("X-Requirement-Flow-Token", ""), HUB_TOKEN)

    def read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise controller.WorkflowError("无效的 Content-Length。") from exc
        if length <= 0 or length > MAX_BODY_BYTES:
            raise controller.WorkflowError("请求体为空或超过大小限制。")
        return self.rfile.read(length)

    def read_json(self) -> tuple[dict[str, Any], bytes]:
        body = self.read_body()
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise controller.WorkflowError("请求 JSON 无效。") from exc
        if not isinstance(payload, dict):
            raise controller.WorkflowError("请求 JSON 必须是对象。")
        return payload, body

    def send_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def send_error_json(self, message: str, status: int = 400) -> None:
        self.send_json({"ok": False, "error": safe_log(message)}, status)

    def serve_file(self, path: Path, csp: str) -> None:
        if not path.is_file():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        body = path.read_bytes()
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if content_type.startswith("text/") or path.suffix in {".js", ".json"}:
            content_type += "; charset=utf-8"
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", csp)
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def forward_worker(self, project_id: str, method: str, worker_path: str, body: bytes = b"") -> None:
        status, headers, raw = WORKERS.request(
            project_id, method, worker_path, body, self.headers.get("Content-Type", "application/json")
        )
        content_type = headers.get("Content-Type", "application/octet-stream")
        if "application/json" in content_type:
            try:
                payload = json.loads(raw)
                if worker_path == "/api/health" and isinstance(payload, dict):
                    payload["token"] = HUB_TOKEN
                    payload.setdefault("features", {})["multiProjectHub"] = True
                    payload["hub"] = projects_payload()["scheduler"]
                raw = json.dumps(rewrite_project_urls(payload, project_id), ensure_ascii=False).encode("utf-8")
            except json.JSONDecodeError:
                pass
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if "Content-Security-Policy" in headers:
            self.send_header("Content-Security-Policy", headers["Content-Security-Policy"])
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_error(HTTPStatus.FORBIDDEN)

    def do_GET(self) -> None:  # noqa: N802
        if not self.host_allowed():
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        path = urlparse(self.path).path
        try:
            if path == "/api/hub/projects":
                self.send_json(projects_payload())
                return
            if path in {"/api/hub/tasks", "/api/hub/knowledge"}:
                if not self.token_allowed():
                    self.send_error_json("控制令牌无效，请从本地控制台页面操作。", HTTPStatus.FORBIDDEN)
                    return
                endpoint, key = ("/api/tasks", "tasks") if path.endswith("tasks") else ("/api/knowledge", "candidates")
                self.send_json(aggregate_payload(endpoint, key))
                return
            project_match = PROJECT_ROUTE.fullmatch(path)
            if project_match:
                project_id, suffix = project_match.groups()
                worker_path = "/api" + (suffix or "/health")
                if worker_path != "/api/health" and not self.token_allowed():
                    self.send_error_json("控制令牌无效，请从本地控制台页面操作。", HTTPStatus.FORBIDDEN)
                    return
                self.forward_worker(project_id, "GET", worker_path)
                return
            html_match = PROJECT_HTML_ROUTE.fullmatch(path)
            if html_match:
                project_id, name = html_match.groups()
                safe_name = Path(unquote(name)).name
                self.forward_worker(project_id, "GET", f"/task-html/{quote(safe_name)}")
                return
            static = {"/": TOOL_DIR / "index.html", "/index.html": TOOL_DIR / "index.html", "/app.js": TOOL_DIR / "app.js"}
            target = static.get(path)
            if target:
                self.serve_file(
                    target,
                    "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
                    "connect-src 'self'; img-src 'self' data: blob:; base-uri 'none'; frame-ancestors 'none'",
                )
                return
        except (controller.WorkflowError, OSError, http.client.HTTPException) as exc:
            self.send_error_json(str(exc), HTTPStatus.BAD_GATEWAY)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if not self.host_allowed() or not self.token_allowed():
            self.send_error_json("控制令牌无效，请从本地控制台页面操作。", HTTPStatus.FORBIDDEN)
            return
        path = urlparse(self.path).path
        try:
            payload, body = self.read_json()
            if path == "/api/hub/projects/preview":
                result = REGISTRY.setup_project(payload, dry_run=True)
                self.send_json({"ok": True, **result})
                return
            if path == "/api/hub/projects":
                result = REGISTRY.setup_project(payload, dry_run=False)
                self.send_json({"ok": True, **result, **projects_payload()}, HTTPStatus.CREATED)
                return
            hub_project_match = HUB_PROJECT_ACTION_ROUTE.fullmatch(path)
            if hub_project_match:
                project_id, action = hub_project_match.groups()
                if action == "config":
                    result = REGISTRY.update_project(project_id, payload)
                    self.send_json({"ok": True, "profile": result, **projects_payload()})
                else:
                    opened = REGISTRY.open_project_directory(project_id, str(payload.get("target") or "repo"))
                    self.send_json({"ok": True, "openedPath": str(opened)})
                return
            project_match = PROJECT_ROUTE.fullmatch(path)
            if project_match:
                project_id, suffix = project_match.groups()
                self.forward_worker(project_id, "POST", "/api" + (suffix or ""), body)
                return
        except (controller.WorkflowError, OSError, subprocess.SubprocessError, http.client.HTTPException) as exc:
            self.send_error_json(str(exc))
            return
        self.send_error_json("未知 API。", HTTPStatus.NOT_FOUND)


def main() -> int:
    global REGISTRY, WORKERS
    parser = argparse.ArgumentParser(description="Run the DevConductor multi-project hub.")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PROJECT_FLOW_HUB_PORT", "4318")))
    parser.add_argument("--profiles-dir", type=Path, default=PROFILE_DIR, help="Project Profile directory")
    parser.add_argument("--registry", type=Path, default=REGISTRY_PATH, help="External Profile registry path")
    parser.add_argument("--runtime-root", type=Path, default=RUNTIME_ROOT, help="Hub logs and global slot directory")
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        raise SystemExit("端口必须在 1024–65535 之间。")
    REGISTRY = ProjectRegistry(args.profiles_dir, args.registry, args.runtime_root.parent)
    WORKERS = WorkerManager(REGISTRY, args.runtime_root)
    projects, errors = REGISTRY.discover()
    args.runtime_root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), HubHandler)
    def stop_from_signal(_signum: int, _frame: Any) -> None:
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop_from_signal)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, stop_from_signal)
    print(f"DevConductor Project Hub: http://127.0.0.1:{args.port}/")
    print(f"Projects: {', '.join(project['name'] for project in projects) if projects else '暂无，请从页面添加'}")
    for error in errors:
        print(f"Profile warning: {error['profilePath']} · {error['error']}", file=sys.stderr)
    print("每个项目使用独立 Worker；仅监听 127.0.0.1；按 Ctrl-C 停止。")
    try:
        server.serve_forever(poll_interval=0.4)
    except KeyboardInterrupt:
        pass
    finally:
        WORKERS.stop_all()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
