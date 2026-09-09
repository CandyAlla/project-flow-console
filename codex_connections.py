"""Resolve named, process-local Codex connections independently of desktop launchers."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
from typing import Any

import codex_desktop
from codex_desktop import ConnectionError, absolute_path as _path, read_json as _read_json

SETTINGS_PATH = Path(__file__).resolve().parent / ".runtime" / "codex-connections.json"
_CONNECTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_API_ENV = {"OPENAI_API_KEY", "OPENAI_ACCESS_TOKEN", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL"}
_CONFIG_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*(?:\.[A-Za-z_][A-Za-z0-9_-]*)*")
_ENV_KEY = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_CONNECTION_ID.fullmatch(value))


def _settings() -> dict[str, Any]:
    if not SETTINGS_PATH.exists():
        return {"version": 2, "connections": {}, "backgroundConnection": "default", "defaultDesktopConnection": "default"}
    settings = _read_json(SETTINGS_PATH, "Codex 连接配置")
    legacy = "version" not in settings and "switcherStatePath" in settings
    if legacy:
        settings = codex_desktop.convert_legacy(settings)
    elif type(settings.get("version")) is not int or settings["version"] != 2:
        raise ConnectionError("Codex 连接配置必须使用 version: 2。")
    elif "_legacy" in settings:
        raise ConnectionError("Codex 连接配置不能使用内部兼容字段。")
    connections = settings.get("connections", {})
    if not isinstance(connections, dict):
        raise ConnectionError("Codex 连接配置的 connections 必须是对象。")
    for connection_id, connection in connections.items():
        if not _valid_id(connection_id) or connection_id == "default":
            raise ConnectionError("Codex 连接 ID 必须为 1–64 位字母、数字、下划线或连字符，且不能使用保留的 default。")
        if not isinstance(connection, dict):
            raise ConnectionError("Codex 连接必须是对象。")
        _path(connection.get("home"), "home")
        if "label" in connection and (not isinstance(connection["label"], str) or not connection["label"].strip()):
            raise ConnectionError("Codex 连接 label 必须为非空字符串。")
        config = connection.get("config", {})
        if not isinstance(config, dict):
            raise ConnectionError("Codex 连接 config 必须是对象。")
        for key, value in config.items():
            if not isinstance(key, str) or not _CONFIG_KEY.fullmatch(key):
                raise ConnectionError("Codex 连接 config 只能使用有效的扁平配置键。")
            if not legacy and (key in {"sqlite_home", "profile", "profiles"} or key.startswith("profiles.") or key.endswith(".sqlite_home")):
                raise ConnectionError("Codex 命名连接不能通过 sqlite_home 或 Profile 覆盖连接目录；请使用 home 配置。")
            if type(value) not in (str, bool, int, float) or isinstance(value, float) and not math.isfinite(value):
                raise ConnectionError("Codex 连接 config 的值只能是字符串、布尔值或有限数字。")
        for key in ("model", "model_provider", "model_reasoning_effort"):
            if key in config and (not isinstance(config[key], str) or not config[key].strip()):
                raise ConnectionError("Codex 连接的模型、provider 和推理强度必须为非空字符串。")
        connection["config"] = config
        if "credentialFile" in connection:
            _path(connection["credentialFile"], "credentialFile")
            if "envKey" not in connection:
                raise ConnectionError("Codex 凭据配置缺少有效的 envKey。")
        if "envKey" in connection:
            env_key = connection["envKey"]
            if not isinstance(env_key, str) or not _ENV_KEY.fullmatch(env_key):
                raise ConnectionError("Codex 凭据配置缺少有效的 envKey。")
            if env_key in {"HOME", "PATH", "CODEX_HOME", "CODEX_SQLITE_HOME"}:
                raise ConnectionError("Codex envKey 不能使用系统目录或路径变量。")
        if "credentialKey" in connection and (not isinstance(connection["credentialKey"], str) or not connection["credentialKey"].strip()):
            raise ConnectionError("Codex credentialKey 必须为非空字符串。")
        if "desktop" in connection:
            codex_desktop.validate_config(connection["desktop"], legacy=legacy)
    settings["connections"] = connections
    for name in ("backgroundConnection", "defaultDesktopConnection"):
        selected = settings.get(name, "default")
        if not _valid_id(selected):
            raise ConnectionError("Codex 默认连接必须是有效的连接 ID。")
        settings[name] = selected
    return settings


def _desktop_mode(settings: dict[str, Any]) -> str:
    if settings.get("_legacy"):
        active = codex_desktop.legacy_active(settings)
        if active is not None:
            return active
        for connection_id, connection in settings["connections"].items():
            if not codex_desktop.unavailable_reason(connection):
                return connection_id
    return settings["defaultDesktopConnection"]


def _selected(settings: dict[str, Any], mode: str | None, desktop: bool) -> str:
    if mode is None:
        mode = _desktop_mode(settings) if desktop else settings["backgroundConnection"]
    if not _valid_id(mode) or mode != "default" and mode not in settings["connections"]:
        raise ConnectionError("Codex 连接未配置，请选择 default 或已配置的连接。")
    return mode


def _validate_desktop(settings: dict[str, Any], mode: str) -> None:
    connection = None if mode == "default" else settings["connections"][mode]
    reason = codex_desktop.unavailable_reason(connection)
    if reason:
        raise ConnectionError(reason)


def validate_desktop(mode: str | None = None) -> None:
    settings = _settings()
    _validate_desktop(settings, _selected(settings, mode, True))


def desktop_mode() -> str:
    """Return the configured desktop default without launching or changing it."""
    return _desktop_mode(_settings())


def desktop_options() -> list[dict[str, Any]]:
    """Describe desktop availability without exposing local paths or credentials."""
    settings = _settings()
    candidates: list[tuple[str, dict[str, Any] | None]] = []
    if not settings.get("_legacy"):
        candidates.append(("default", None))
    candidates.extend((key, value) for key, value in settings["connections"].items() if "desktop" in value)
    options = []
    for connection_id, connection in candidates:
        try:
            reason = codex_desktop.unavailable_reason(connection)
        except ConnectionError as exc:
            reason = str(exc)
        options.append({
            "id": connection_id,
            "label": connection.get("label", connection_id) if connection else "默认 Codex 环境",
            "available": not bool(reason), "reason": reason,
        })
    return options


def _credential(connection: dict[str, Any]) -> str:
    auth = _read_json(_path(connection["credentialFile"], "credentialFile"), "Codex 连接凭据")
    key = auth.get(connection.get("credentialKey", "OPENAI_API_KEY"))
    if not isinstance(key, str) or not key.strip():
        raise ConnectionError("Codex 连接凭据缺少有效密钥，请检查凭据文件和 credentialKey 配置。")
    return key


def _reject_connection_overrides(command: list[str], config: dict[str, Any]) -> None:
    for index, argument in enumerate(command[1:], 1):
        assignment = ""
        if argument in ("-c", "--config") and index + 1 < len(command):
            assignment = command[index + 1]
        elif argument.startswith("--config="):
            assignment = argument.removeprefix("--config=")
        elif argument.startswith("-c") and len(argument) > 2:
            assignment = argument[2:]
        key = assignment.split("=", 1)[0].strip()
        if key in config or key in {"model_provider", "model_providers", "forced_login_method", "model", "sqlite_home", "profile", "profiles"} or key.startswith(("model_providers.", "profiles.")):
            raise ConnectionError("Codex 命令不能覆盖已固定的连接配置。")
        if argument in ("-m", "--model", "-p", "--profile") or argument.startswith(("--model=", "--profile=")) or re.fullmatch(r"-[mp].+", argument):
            raise ConnectionError("Codex 命令不能覆盖已固定的模型或连接 Profile。")


def _resolve(command: list[str], settings: dict[str, Any], mode: str, desktop: bool) -> tuple[list[str], dict[str, str]]:
    if not isinstance(command, list) or not command or any(not isinstance(arg, str) or "\x00" in arg for arg in command) or not command[0]:
        raise ConnectionError("Codex 启动命令无效。")
    if desktop:
        _validate_desktop(settings, mode)
    env = os.environ.copy()
    if mode == "default":
        return list(command), env
    connection = settings["connections"][mode]
    home = _path(connection["home"], "home")
    if not desktop and settings.get("_legacy"):
        home = codex_desktop.legacy_background_home(settings, connection, home)
    if not home.is_dir():
        raise ConnectionError("Codex 连接目录不存在，请检查连接配置或先完成初始化。")
    selected_env_value = env.get(connection.get("envKey", ""))
    credential_env_keys = {item["envKey"] for item in settings["connections"].values() if "envKey" in item}
    for name in _API_ENV | credential_env_keys | {"CODEX_SQLITE_HOME"}:
        env.pop(name, None)
    env["CODEX_HOME"] = str(home)
    if "credentialFile" in connection:
        env[connection["envKey"]] = _credential(connection)
    elif "envKey" in connection:
        if not selected_env_value or not selected_env_value.strip():
            raise ConnectionError("Codex 连接所需的凭据环境变量未设置，请在启动服务前配置对应 envKey。")
        env[connection["envKey"]] = selected_env_value
    config = connection["config"]
    _reject_connection_overrides(command, config)
    overrides = [argument for key, value in config.items() for argument in ("-c", f"{key}={json.dumps(value, ensure_ascii=False, allow_nan=False)}")]
    return [command[0], *overrides, *command[1:]], env


def resolve(command: list[str], *, mode: str | None = None, desktop: bool = False) -> tuple[list[str], dict[str, str]]:
    settings = _settings()
    return _resolve(command, settings, _selected(settings, mode, desktop), desktop)


def _rpc_overrides(method: str, settings: dict[str, Any], mode: str) -> dict[str, Any]:
    if mode == "default" or method not in {"thread/start", "thread/resume", "turn/start"}:
        return {}
    config = settings["connections"][mode]["config"]
    overrides = {"model": config["model"]} if "model" in config else {}
    if method in {"thread/start", "thread/resume"}:
        if "model_provider" in config:
            overrides["modelProvider"] = config["model_provider"]
    elif "model_reasoning_effort" in config:
        overrides["effort"] = config["model_reasoning_effort"]
    return overrides


def rpc_overrides(method: str, *, mode: str | None = None, desktop: bool = False) -> dict[str, Any]:
    """Apply only explicit model settings to new or resumed App Server turns."""
    settings = _settings()
    return _rpc_overrides(method, settings, _selected(settings, mode, desktop))


def app_server_spec(command: list[str], *, mode: str | None = None, desktop: bool = False) -> tuple[list[str], dict[str, str], dict[str, dict[str, Any]]]:
    """Snapshot process configuration and RPC settings together for one server lifetime."""
    settings = _settings()
    selected = _selected(settings, mode, desktop)
    resolved, env = _resolve(command, settings, selected, desktop)
    overrides = {method: _rpc_overrides(method, settings, selected) for method in ("thread/start", "thread/resume", "turn/start")}
    return resolved, env, overrides


def open_desktop(mode: str | None, deep_link: str) -> None:
    codex_desktop.validate_deep_link(deep_link)
    settings = _settings()
    mode = _selected(settings, mode, True)
    _validate_desktop(settings, mode)
    codex_desktop.open_connection(None if mode == "default" else settings["connections"][mode], deep_link)
