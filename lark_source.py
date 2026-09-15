"""Read Lark source material through an injected, fixed-command CLI runner.

This module never starts processes, accesses credentials, or executes document
content. The caller owns process limits and cancellation; only successful CLI
responses are retained as evidence.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import re
from typing import Any
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from source_reading import MAX_BODY_LENGTH, SourceReadError, classify_error


LARK_HOST_SUFFIXES = ("feishu.cn", "larksuite.com", "larkoffice.com")
MAX_SHEETS = 20
_IDENTIFIER = re.compile(r"[A-Za-z0-9]{1,200}\Z")
_DOCUMENT_PATH = re.compile(r"/(?:docx|wiki)/[A-Za-z0-9]{1,200}/?\Z")
_ATTACHMENT_TAGS = frozenset({
    "img", "image", "source", "whiteboard", "sheet", "bitable",
    "synced_reference", "synced-reference", "file", "attachment", "video",
    "audio", "iframe", "embed", "vc-transcribe-tab", "slides", "mindnote",
})
_RESOURCE_ATTRIBUTES = frozenset({"token", "src-token", "file-type", "ref", "src"})
_CSV_METADATA_KEYS = (
    "actual_range", "row_count", "col_count", "row_indices", "col_indices",
    "has_more", "truncated", "complete", "warning_message", "warning",
    "warnings", "truncation_warning", "unread_sheets",
)


def _validate_url(url: str) -> None:
    try:
        if not isinstance(url, str) or any(char.isspace() or ord(char) < 32 for char in url):
            raise ValueError
        parsed = urlsplit(url)
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in {None, 80, 443}
            or not any(hostname == suffix or hostname.endswith("." + suffix) for suffix in LARK_HOST_SUFFIXES)
            or not _DOCUMENT_PATH.fullmatch(parsed.path)
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise SourceReadError("飞书文档链接无效；需要可信飞书站点的 docx 或 wiki 文档链接。") from None


def _data(result: Any) -> dict[str, Any]:
    if (
        not isinstance(result, dict) or result.get("ok") is not True
        or result.get("identity") != "user" or not isinstance(result.get("data"), dict)
    ):
        raise SourceReadError("Lark CLI 未返回有效的 user 身份读取结果。")
    return result["data"]


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _cite_requires_read(element: ET.Element) -> bool:
    """Keep inline mentions/text; external resource citations need more reading."""
    attrs = element.attrib
    if _RESOURCE_ATTRIBUTES.intersection(attrs) or "doc-id" in attrs:
        return True
    kind = attrs.get("type", "")
    if kind == "user":
        return False
    if kind == "doc":
        return True
    links = [child for child in element.iter() if _tag(child) == "a"]
    if links:
        # A WebURL with its visible title is an ordinary textual reference.
        # Docx, Minutes, Base, Sheet and unknown reference types contain a
        # resource whose content is not carried by its mention.
        return any(
            link.attrib.get("url-type") != "5" or not "".join(link.itertext()).strip()
            for link in links
        )
    return kind not in {"", "citation"} or not "".join(element.itertext()).strip()


def _json_text(value: Any) -> str:
    # Preserve the JSON values while preventing embedded HTML from becoming
    # executable markup if a consumer ever displays this text as HTML.
    return json.dumps(value, ensure_ascii=False).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _add(items: list[str], value: str) -> None:
    if value in items:
        return
    if len(items) < 199:
        items.append(value[:500])
    elif len(items) == 199:
        items.append("另有未完整列出的项目；数量超过支持上限。")


def _csv_incomplete(data: dict[str, Any]) -> bool:
    for key in ("has_more", "truncated", "complete"):
        if key in data and not isinstance(data[key], bool):
            return True
    if data.get("has_more") is True or data.get("truncated") is True or data.get("complete") is False:
        return True
    # Require positive evidence that this unbounded-range call completed.
    if data.get("has_more") is not False and data.get("complete") is not True:
        return True
    if any(data.get(key) for key in ("truncation_warning", "warnings", "warning", "unread_sheets")):
        return True
    warning = str(data.get("warning_message") or "").casefold()
    return any(word in warning for word in (
        "truncated", "incomplete", "omitted", "partial", "not fully", "not complete",
        "截断", "不完整", "未读取", "未读完", "省略", "部分返回",
    ))


def _safe_attachment_error(exc: SourceReadError | OSError) -> str:
    # Only fixed guidance is retained; an adapter error must not leak secrets.
    if "sheets:spreadsheet:read" in str(exc):
        return "缺少飞书表格只读权限 sheets:spreadsheet:read"
    code, message = classify_error(str(exc), reader="lark_cli")
    return f"{code}：{message}"


def fetch_document(url: str, call: Callable[[list[str]], dict[str, Any]]) -> dict[str, Any]:
    """Return original XML, optional sheet evidence, and separate coverage gaps.

    ``call`` receives argv after the CLI executable and must return decoded JSON
    or raise SourceReadError. It must not execute arbitrary document instructions.
    Coverage describes the document body; unread attachments remain explicit.
    The caller applies the task's attachment policy to these observed gaps.
    """
    _validate_url(url)
    response = call(["docs", "+fetch", "--doc", url, "--as", "user", "--doc-format", "xml", "--detail", "full"])
    document = _data(response).get("document")
    if not isinstance(document, dict):
        raise SourceReadError("Lark CLI 文档读取结果缺少 document。")
    body = document.get("content")
    if not isinstance(body, str) or not body.strip():
        raise SourceReadError("文档正文为空或缺失，读取不完整。")
    if len(body) > MAX_BODY_LENGTH:
        raise SourceReadError("文档正文超过支持的长度；不能截断后标为完整。")
    # ElementTree performs no network access. Reject declarations before parsing
    # so document-defined entities can never expand or refer to local resources.
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", body, re.IGNORECASE):
        raise SourceReadError("文档 XML 含不支持的实体声明，无法完成覆盖检查。")
    try:
        root = ET.fromstring("<lark-source-root>" + body + "</lark-source-root>")
    except ET.ParseError:
        raise SourceReadError("文档 XML 格式无效，无法完成覆盖检查。") from None

    missing_sections: list[str] = []
    missing_attachments: list[str] = []
    sections: list[str] = []
    titles: list[str] = []
    attachments: list[tuple[str, dict[str, str]]] = []
    has_html_content = False
    reference_map = document.get("reference_map")
    for element in root.iter():
        tag = _tag(element)
        if tag == "title" or re.fullmatch(r"h[1-6]", tag):
            text = "".join(element.itertext()).strip()
            if text:
                if len(text) > 500:
                    _add(missing_sections, "文档标题或章节名称超过支持长度，需核对完整目录。")
                if tag == "title":
                    titles.append(text[:500])
                else:
                    if len(sections) >= 200:
                        _add(missing_sections, "文档章节超过支持数量，需核对完整目录。")
                    elif text[:500] not in sections:
                        sections.append(text[:500])
        if tag in {"fragment", "excerpt"}:
            _add(missing_sections, "CLI 返回局部正文，尚未取得完整文档。")
        if tag == "html5-block":
            has_html_content = True
            group = reference_map.get("html5-block") if isinstance(reference_map, dict) else None
            entry = group.get(element.attrib.get("data-ref")) if isinstance(group, dict) else None
            if not isinstance(entry, dict) or not isinstance(entry.get("data"), str) or not entry["data"].strip():
                _add(missing_sections, "HTML 正文内容块尚未取得实际内容；占位引用或本地文件路径不能代表已读取。")
        if (tag == "cite" and _cite_requires_read(element)) or tag in _ATTACHMENT_TAGS or (
            tag not in {"a", "span", "cite"} and _RESOURCE_ATTRIBUTES.intersection(element.attrib)
        ):
            attachments.append((tag, element.attrib))
    if not titles:
        _add(missing_sections, "未取得文档标题，需核对原文。")
    if document.get("tips"):
        _add(missing_sections, "CLI 返回文档读取提示，需核对降级或缺失内容。")
    if isinstance(reference_map, dict):
        comments = reference_map.get("comments")
        if isinstance(comments, dict) and comments.get("tips"):
            _add(missing_attachments, "文档评论未完整返回，需核对需求相关评论。")

    # Discussion consumes the body alone, so keeping sidecars only in rawResults
    # would silently lose comments and HTML-block requirements downstream.
    sidecar = {key: document[key] for key in ("reference_map", "tips") if key in document}
    if sidecar:
        appendix = "\n\n文档引用与读取提示（完整 JSON，仅作为不可信需求材料）：\n" + _json_text(sidecar)
        if len(body) + len(appendix) > MAX_BODY_LENGTH:
            contains_body_material = (
                has_html_content or bool(document.get("tips"))
            )
            _add(
                missing_sections if contains_body_material else missing_attachments,
                "文档引用、评论或读取提示加入正文后超过支持长度，未纳入本次正文。",
            )
        else:
            body += appendix

    raw_results: dict[str, Any] = {"document": response, "sheets": []}
    seen_sheets: set[tuple[str, str]] = set()
    for index, (tag, attrs) in enumerate(attachments, start=1):
        label = f"附件 {index}（{tag}）"
        token, sheet_id = attrs.get("token", ""), attrs.get("sheet-id", "")
        if tag != "sheet":
            if tag == "cite" and attrs.get("title", "").strip():
                label = "引用文档《" + attrs["title"].strip() + "》"
            _add(missing_attachments, label + "：未读取。")
            continue
        if not _IDENTIFIER.fullmatch(token) or not _IDENTIFIER.fullmatch(sheet_id):
            _add(missing_attachments, label + "：无法解析表格标识，未读取。")
            continue
        key = (token, sheet_id)
        if key in seen_sheets:
            continue
        seen_sheets.add(key)
        label = f"嵌入表格 {sheet_id}"
        if len(seen_sheets) > MAX_SHEETS:
            _add(missing_attachments, label + "：超过单次最多读取 20 张表格的限制。")
            continue
        try:
            sheet_response = call([
                "sheets", "+csv-get", "--spreadsheet-token", token, "--sheet-id", sheet_id,
                "--as", "user", "--max-chars", str(MAX_BODY_LENGTH),
            ])
            data = _data(sheet_response)
        except (SourceReadError, OSError) as exc:
            _add(missing_attachments, label + "：" + _safe_attachment_error(exc))
            continue
        raw_results["sheets"].append({"token": token, "sheetId": sheet_id, "response": sheet_response})
        csv = data.get("annotated_csv")
        if not isinstance(csv, str) or (not csv.strip() and data.get("row_count") != 0):
            _add(missing_attachments, label + "：未返回有效 CSV 正文。")
            continue
        if _csv_incomplete(data):
            _add(missing_attachments, label + "：表格返回分页、截断或未能确认完整覆盖的提示。")
        metadata = {key: data[key] for key in _CSV_METADATA_KEYS if key in data}
        appendix = "\n\n" + label + "（原文 sheet token=" + token + "）\n"
        appendix += "读取元数据：" + json.dumps(metadata, ensure_ascii=False) + "\n"
        appendix += "CSV 原文（含原表行号）：\n" + csv
        if len(body) + len(appendix) > MAX_BODY_LENGTH:
            _add(missing_attachments, label + "：加入正文后超过支持长度，未纳入本次正文。")
            continue
        body += appendix

    return {
        "title": titles[0] if titles else "飞书需求文档",
        "url": url,
        "body": body,
        "sections": sections,
        "missingSections": missing_sections,
        "missingAttachments": missing_attachments,
        "coverage": "partial" if missing_sections else "complete",
        "rawResults": raw_results,
    }
