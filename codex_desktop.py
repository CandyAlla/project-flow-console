"""Desktop opening and compatibility with the former private dual launcher."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

_DEEPLINK = re.compile(r"codex://threads/[A-Za-z0-9_-]{1,160}")
_LEGACY_ACTIVE = {"api": "newapi", "account": "chatgpt"}


class ConnectionError(RuntimeError):
    """A user-facing error that never includes credentials or subprocess output."""


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ConnectionError(f"无法读取有效的{label}，请检查对应配置文件。") from None
    if not isinstance(value, dict):
        raise ConnectionError(f"{label}必须是 JSON 对象。")
    return value


def absolute_path(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise ConnectionError(f"Codex 连接配置缺少有效的 {label} 路径。")
    try:
        path = Path(value).expanduser()
    except (OSError, RuntimeError):
        raise ConnectionError(f"无法解析 Codex 连接配置的 {label} 路径。") from None
    if not path.is_absolute():
        raise ConnectionError(f"Codex 连接配置的 {label} 必须是绝对路径。")
    return path


def validate_deep_link(deep_link: str) -> None:
    if not isinstance(deep_link, str) or not _DEEPLINK.fullmatch(deep_link):
        raise ConnectionError("Codex 聊天链接无效。")


def validate_config(desktop: Any, *, legacy: bool = False) -> None:
    if not isinstance(desktop, dict):
        raise ConnectionError("Codex desktop 必须是对象。")
    kind = desktop.get("type")
    if kind == "current" or kind == "legacy" and legacy:
        return
    if kind != "command":
        raise ConnectionError("Codex desktop.type 必须为 current 或 command。")
    command = desktop.get("command")
    if not isinstance(command, list) or len(command) < 2 or any(not isinstance(arg, str) or "\x00" in arg for arg in command):
        raise ConnectionError("Codex 桌面 command 必须是有效的参数数组。")
    absolute_path(command[0], "desktop.command 可执行文件")
    if command.count("{url}") != 1 or any(("{" in arg or "}" in arg) and arg != "{url}" for arg in command):
        raise ConnectionError("Codex 桌面 command 必须且只能包含一个完整参数 {url}。")
    if Path(command[0]).name.lower() in {"sh", "bash", "zsh", "dash", "fish", "ksh", "csh", "tcsh", "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        raise ConnectionError("Codex 桌面 command 必须直接运行打开程序，不能通过 Shell 执行。")


def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _platform_command() -> list[str] | None:
    if sys.platform == "darwin":
        return ["/usr/bin/open"] if _executable(Path("/usr/bin/open")) else None
    if sys.platform.startswith("linux"):
        executable = shutil.which("xdg-open")
        return [executable] if executable else None
    return None


def _platform_reason() -> str:
    if sys.platform == "win32" and callable(getattr(os, "startfile", None)):
        return ""
    if _platform_command():
        return ""
    return "当前系统没有可用的默认桌面打开程序，请配置 desktop.command。"


def _state(desktop: dict[str, Any]) -> dict[str, Any]:
    state = read_json(absolute_path(desktop["statePath"], "switcherStatePath"), "Codex 桌面入口状态")
    if type(state.get("homes_ready")) is not bool:
        raise ConnectionError("Codex 桌面入口状态缺少有效的 homes_ready。")
    return state


def unavailable_reason(connection: dict[str, Any] | None) -> str:
    if connection is None:
        return _platform_reason()
    desktop = connection.get("desktop")
    if desktop is None:
        return "此连接仅用于后台，尚未配置 desktop 打开方式。"
    home = absolute_path(connection["home"], "home")
    kind = desktop["type"]
    if kind == "legacy":
        if sys.platform != "darwin":
            return "旧双入口连接只支持 macOS，请改用通用 desktop 打开方式。"
        if not _state(desktop)["homes_ready"] or not home.is_dir():
            return "Codex 桌面连接尚未初始化，请先手动打开对应桌面入口完成初始化，再重试；控制台不会自动迁移聊天。"
        if not absolute_path(desktop["launcher"], "launcher").exists() or not absolute_path(desktop["app"], "desktopApp").exists():
            return "Codex 桌面入口或应用不存在，请检查本机连接配置。"
        return _platform_reason()
    if not home.is_dir():
        return "Codex 连接目录不存在，请先完成连接初始化。"
    if kind == "current":
        if os.environ.get("CODEX_SQLITE_HOME", "").strip():
            return "当前进程设置了独立的 Codex 数据库目录，请使用默认 Codex 环境或配置 desktop.command。"
        try:
            inherited_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex").expanduser()
            same_home = home.resolve() == inherited_home.resolve()
        except (OSError, RuntimeError):
            return "无法解析当前 Codex 连接目录，请检查本机目录配置。"
        if not same_home:
            return "此连接目录与当前进程的 Codex 目录不同，请配置能打开该连接的 desktop.command。"
        return _platform_reason()
    if not _executable(absolute_path(desktop["command"][0], "desktop.command 可执行文件")):
        return "Codex 桌面 command 的打开程序不存在或不可执行。"
    return ""


def _run(command: list[str]) -> None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=60, shell=False)
    except subprocess.TimeoutExpired:
        raise ConnectionError("等待 Codex 桌面入口超时，请手动完成或取消入口提示后重试。") from None
    except OSError:
        raise ConnectionError("无法打开 Codex 桌面入口，请检查打开程序。") from None
    if result.returncode != 0:
        raise ConnectionError("Codex 桌面入口未成功打开，请手动检查入口提示后重试。")


def open_connection(connection: dict[str, Any] | None, deep_link: str) -> None:
    validate_deep_link(deep_link)
    reason = unavailable_reason(connection)
    if reason:
        raise ConnectionError(reason)
    desktop = connection.get("desktop") if connection else None
    if desktop and desktop["type"] == "legacy":
        _run(["/usr/bin/open", "-W", "-a", str(absolute_path(desktop["launcher"], "launcher"))])
        state = _state(desktop)
        if not state["homes_ready"] or state.get("active") != desktop["activeValue"]:
            raise ConnectionError("Codex 桌面连接尚未切换到所选模式，请完成入口提示后重试。")
        _run(["/usr/bin/open", "-a", str(absolute_path(desktop["app"], "desktopApp")), deep_link])
    elif desktop and desktop["type"] == "command":
        command = [deep_link if argument == "{url}" else argument for argument in desktop["command"]]
        command[0] = str(absolute_path(command[0], "desktop.command 可执行文件"))
        _run(command)
    elif sys.platform == "win32":
        try:
            os.startfile(deep_link)
        except OSError:
            raise ConnectionError("系统未能打开 Codex 链接，请检查 Codex App 的安装。") from None
    else:
        _run([*_platform_command(), deep_link])


def convert_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the private switcher format in memory; never migrate user files."""
    for name in ("baseHome", "switcherStatePath", "desktopApp"):
        absolute_path(raw.get(name), name)
    original = raw.get("connections")
    if not isinstance(original, dict):
        raise ConnectionError("旧 Codex 连接配置缺少 connections。")
    connections = {}
    for mode, active in _LEGACY_ACTIVE.items():
        source = original.get(mode)
        if not isinstance(source, dict):
            raise ConnectionError("旧 Codex 连接配置必须同时包含 api 和 account。")
        absolute_path(source.get("launcher"), "launcher")
        config = source.get("config")
        if not isinstance(config, dict) or not isinstance(config.get("model"), str) or not config["model"].strip():
            raise ConnectionError("旧 Codex 连接必须明确配置 model。")
        if mode == "api":
            absolute_path(source.get("credentialFile"), "credentialFile")
            provider = config.get("model_provider")
            if not isinstance(provider, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", provider):
                raise ConnectionError("旧 Codex API 连接必须明确配置 model_provider。")
            if not source.get("envKey") or config.get("forced_login_method") != "api" or config.get(f"model_providers.{provider}.env_key") != source["envKey"]:
                raise ConnectionError("旧 Codex API 连接必须固定 api 登录方式并使用匹配的 env_key。")
            if config.get(f"model_providers.{provider}.requires_openai_auth") is not False:
                raise ConnectionError("旧 Codex API provider 必须设置 requires_openai_auth=false。")
        elif config.get("model_provider") != "openai" or config.get("forced_login_method") != "chatgpt":
            raise ConnectionError("旧 Codex 账户连接必须使用 openai provider 和 chatgpt 登录方式。")
        connection = copy.deepcopy(source)
        connection.setdefault("label", "API 登录版" if mode == "api" else "账号版")
        connection["desktop"] = {
            "type": "legacy", "statePath": raw["switcherStatePath"],
            "launcher": source["launcher"], "app": raw["desktopApp"], "activeValue": active,
        }
        connections[mode] = connection
    return {
        "version": 2, "connections": connections, "backgroundConnection": "api",
        "defaultDesktopConnection": "api", "_legacy": {"baseHome": raw["baseHome"]},
    }


def legacy_active(settings: dict[str, Any]) -> str | None:
    connection = next(iter(settings["connections"].values()))
    state = _state(connection["desktop"])
    if state["homes_ready"]:
        return next((key for key, value in settings["connections"].items() if value["desktop"]["activeValue"] == state.get("active")), None)
    return None


def legacy_background_home(settings: dict[str, Any], connection: dict[str, Any], home: Path) -> Path:
    if not _state(connection["desktop"])["homes_ready"] or not home.is_dir():
        return absolute_path(settings["_legacy"]["baseHome"], "baseHome")
    return home
