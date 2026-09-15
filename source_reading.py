"""Validate document snapshots and classify reader failures without side effects."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit


READERS = frozenset({"chrome_mcp", "lark_cli"})
METHODS = frozenset({"desktop_import", "automated"})
MAX_BODY_LENGTH = 240_000
MAX_TITLE_LENGTH = 500
MAX_SECTION_COUNT = 200
MAX_SECTION_LENGTH = 500
PAYLOAD_FIELDS = frozenset({
    "title", "url", "body", "sections", "missingSections",
    "missingAttachments", "coverage",
})

_ERROR_MESSAGES = {
    "lark_credentials_unavailable": "Lark CLI 后台读取进程无法访问本机钥匙串中的飞书凭据。请检查启动服务的用户及钥匙串访问环境，恢复访问后单独重试读取。",
    "codex_auth_missing": "读取环境缺少 Codex 账号认证。请在用于读取的 Codex 环境检查账号登录与插件授权，然后单独重试读取。",
    "plugin_load_failed": "Codex 浏览器插件加载失败。请在桌面设置的 Computer Use 中检查插件安装与受信任路径，然后单独重试读取。",
    "chrome_not_connected": "读取环境尚未连接 Chrome。请打开 Chrome 并检查控制扩展连接，然后单独重试读取。",
    "reader_unavailable": "所选文档读取通道当前不可用。请检查读取环境，或在桌面完成读取后导入文档正文。",
    "document_login_required": "文档站点要求登录。请在读取所用环境登录该文档站点，然后单独重试读取。",
    "document_permission_denied": "当前文档账号没有访问权限。请确认原始链接及该账号的文档权限，然后单独重试读取。",
    "read_incomplete": "文档正文读取不完整。请补齐正文和缺失章节后重新读取或导入；未读附件不影响进入需求讨论。",
    "read_failed": "文档读取失败。请检查读取环境后单独重试，或在桌面完成读取后导入文档正文。",
}


class SourceReadError(ValueError):
    """The submitted document does not satisfy the snapshot contract."""


def default_state() -> dict[str, Any]:
    """Return a fresh state for each task; mutable values must never be shared."""
    return {"status": "idle", "errorCode": "", "error": "", "logs": [], "snapshot": None}


def requires_read(source: dict[str, Any]) -> bool:
    return (
        isinstance(source, dict)
        and source.get("type") == "link"
        and isinstance(source.get("reader"), str)
        and source["reader"] in READERS
    )


def _valid_url(value: Any) -> bool:
    if not isinstance(value, str) or not value or any(char.isspace() or ord(char) < 32 for char in value):
        return False
    try:
        parsed = urlsplit(value)
        # Accessing port also validates malformed and out-of-range port values.
        parsed.port
        return (
            parsed.scheme in {"https", "http"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except ValueError:
        return False


def _section_list(value: Any) -> list[str]:
    if not isinstance(value, list) or len(value) > MAX_SECTION_COUNT:
        raise SourceReadError("文档章节或附件列表格式无效，请检查导入结果后重试。")
    result = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or len(item) > MAX_SECTION_LENGTH:
            raise SourceReadError("文档章节或附件名称为空、过长或格式无效，请检查导入结果后重试。")
        result.append(item.strip())
    return result


def validate_snapshot(
    source: dict[str, Any],
    payload: dict[str, Any],
    *,
    read_at: str,
    method: str,
) -> dict[str, Any]:
    """Validate a complete or partial document without trusting reader metadata.

    Coverage describes the main document. Unread attachments are retained as
    context, but only incomplete body/sections block the planning gate.
    URL, reader, timestamp and digest are bound by this function.
    """
    if not requires_read(source) or not _valid_url(source.get("url")):
        raise SourceReadError("文档来源或读取通道无效，请检查任务中的原始链接。")
    if not isinstance(payload, dict):
        raise SourceReadError("文档读取结果必须是包含正文的对象。")
    if "body" not in payload or not isinstance(payload["body"], str) or not payload["body"].strip():
        raise SourceReadError("文档正文为空或缺失，只有摘要不能完成读取。请提供实际正文后重试。")
    if set(payload) != PAYLOAD_FIELDS:
        raise SourceReadError("文档读取结果字段不完整或包含未知字段，请按导入格式提供正文与覆盖信息。")
    if not _valid_url(payload["url"]) or payload["url"] != source["url"]:
        raise SourceReadError("文档链接与任务中的原始链接不完全一致，请读取原始链接后重试。")
    title = payload["title"]
    if not isinstance(title, str) or not title.strip() or len(title) > MAX_TITLE_LENGTH:
        raise SourceReadError("文档标题为空、过长或格式无效，请检查读取结果后重试。")
    body = payload["body"]
    if len(body) > MAX_BODY_LENGTH:
        raise SourceReadError("文档正文超过支持的长度，请拆分需求文档后重新读取；不要用摘要替代正文。")
    coverage = payload["coverage"]
    if not isinstance(coverage, str) or coverage not in {"complete", "partial"}:
        raise SourceReadError("文档覆盖状态无效，请提供完整或部分读取的覆盖信息。")
    sections = _section_list(payload["sections"])
    missing_sections = _section_list(payload["missingSections"])
    missing_attachments = _section_list(payload["missingAttachments"])
    if not isinstance(method, str) or method not in METHODS:
        raise SourceReadError("文档读取方式无效。")
    if not isinstance(read_at, str) or not read_at.strip():
        raise SourceReadError("文档读取时间缺失或格式无效。")
    body = body.strip()
    return {
        "title": title.strip(),
        "url": source["url"],
        "body": body,
        "sections": sections,
        "missingSections": missing_sections,
        "missingAttachments": missing_attachments,
        "coverage": "partial" if missing_sections else coverage,
        "readAt": read_at,
        "reader": source["reader"],
        "method": method,
        "digest": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    }


def snapshot_ready(snapshot: Any) -> bool:
    """Require complete body/sections; attachments are optional context."""
    if not isinstance(snapshot, dict) or snapshot.get("coverage") != "complete":
        return False
    body = snapshot.get("body")
    return (
        isinstance(body, str)
        and bool(body.strip())
        and len(body) <= MAX_BODY_LENGTH
        and isinstance(snapshot.get("missingSections"), list)
        and snapshot["missingSections"] == []
        and isinstance(snapshot.get("missingAttachments"), list)
    )


def classify_error(message: str, *, reader: str | None = None) -> tuple[str, str]:
    """Return a safe category and guidance; never return raw tool error text."""
    value = message.casefold() if isinstance(message, str) else ""
    lark_reader = reader == "lark_cli" or (
        reader is None and any(marker in value for marker in ("lark-cli", "lark cli", "lark_cli"))
    )
    # Concrete reader failures outrank a possibly incorrect model-supplied code.
    # A generic keychain error alone does not identify which reader failed.
    if lark_reader and any(marker in value for marker in ("keychain get failed", "keychain not initialized")):
        return "lark_credentials_unavailable", _ERROR_MESSAGES["lark_credentials_unavailable"]
    # Codex/plugin failures take precedence over generic login/permission text.
    patterns = (
        ("lark_credentials_unavailable", ("lark_credentials_unavailable",)),
        ("codex_auth_missing", ("codex auth token is unavailable", "codex_auth_missing")),
        ("plugin_load_failed", ("trusted rpc dependency", "plugin_load_failed", "插件加载失败")),
        ("chrome_not_connected", (
            "chrome_not_connected", "chrome is not connected", "chrome not connected",
            "chrome extension not connected", "browser is not connected", "browser not connected",
            "no browser connection", "chrome is not running", "chrome not running",
            "chrome 未连接", "chrome未连接", "未连接 chrome", "未连接chrome",
            "浏览器未连接", "chrome 未运行", "chrome未运行",
        )),
        ("reader_unavailable", ("reader_unavailable", "读取通道不可用", "读取通道当前不可用")),
        ("document_login_required", (
            "document_login_required", "sign in", "sign-in", "signin", "log in",
            "login required", "login_required", "not logged in", "未登录", "请登录",
            "需要登录", "要求登录",
        )),
        ("document_permission_denied", (
            "document_permission_denied", "permission denied", "access denied", "forbidden",
            "没有访问权限", "无权限", "没有权限", "权限不足", "无权访问",
        )),
        ("read_incomplete", (
            "read_incomplete", "partial", "incomplete", "summary only", "summary-only",
            "读取不完整", "缺失章节", "正文为空", "正文缺失", "只有摘要", "仅摘要",
        )),
    )
    for code, markers in patterns:
        if any(marker in value for marker in markers):
            return code, _ERROR_MESSAGES[code]
    return "read_failed", _ERROR_MESSAGES["read_failed"]
