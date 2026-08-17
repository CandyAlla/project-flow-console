#!/usr/bin/env python3
"""Minimal stdio MCP server for explicit DevConductor memory operations."""

from __future__ import annotations

import json
import sys
from typing import Any

from memory_lib import PluginMemoryError, create, read, search


TOOLS = [
    {
        "name": "memory_search",
        "description": "Search approved shared memories for the current Git project and team.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string"}, "cwd": {"type": "string"}, "repositoryUrl": {"type": "string"},
            "taskId": {"type": "string"}, "scopes": {"type": "array", "items": {"type": "string"}},
        }, "required": ["query"], "additionalProperties": False},
    },
    {
        "name": "knowledge_search",
        "description": "Search reusable project/team knowledge; alias of memory_search for knowledge-oriented prompts.",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string"}, "cwd": {"type": "string"}, "repositoryUrl": {"type": "string"},
        }, "required": ["query"], "additionalProperties": False},
    },
    {
        "name": "memory_read",
        "description": "Read one shared memory by its Memory Hub id.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"], "additionalProperties": False},
    },
    {
        "name": "memory_capture",
        "description": "Explicitly save a reviewed memory as active; never call without user authorization.",
        "inputSchema": {"type": "object", "properties": {
            "title": {"type": "string"}, "content": {"type": "string"}, "scope": {"type": "string", "enum": ["private", "task", "project", "team"]},
            "kind": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}, "taskId": {"type": "string"},
            "cwd": {"type": "string"}, "repositoryUrl": {"type": "string"}, "sourceKey": {"type": "string"},
        }, "required": ["title", "content"], "additionalProperties": False},
    },
    {
        "name": "memory_publish_candidate",
        "description": "Save a memory candidate for later review; candidates are not returned by normal recall.",
        "inputSchema": {"type": "object", "properties": {
            "title": {"type": "string"}, "content": {"type": "string"}, "scope": {"type": "string", "enum": ["private", "task", "project", "team", "global-candidate"]},
            "kind": {"type": "string"}, "tags": {"type": "array", "items": {"type": "string"}}, "taskId": {"type": "string"},
            "cwd": {"type": "string"}, "repositoryUrl": {"type": "string"}, "sourceKey": {"type": "string"},
        }, "required": ["title", "content"], "additionalProperties": False},
    },
]


def tool_result(value: Any, *, error: bool = False) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}], "isError": error}


def call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    if name in {"memory_search", "knowledge_search"}:
        return tool_result({"memories": search(
            str(arguments.get("query") or ""), cwd=arguments.get("cwd"), repository_url=arguments.get("repositoryUrl"),
            task_id=str(arguments.get("taskId") or ""), scopes=arguments.get("scopes"),
        )})
    if name == "memory_read":
        return tool_result({"memory": read(str(arguments.get("id") or ""))})
    if name in {"memory_capture", "memory_publish_candidate"}:
        return tool_result({"memory": create(
            arguments, cwd=arguments.get("cwd"), repository_url=arguments.get("repositoryUrl"),
            status="active" if name == "memory_capture" else "candidate",
        )})
    return tool_result({"error": f"Unknown tool: {name}"}, error=True)


def respond(request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    if request_id is None:
        return None
    if method == "initialize":
        version = str((request.get("params") or {}).get("protocolVersion") or "2025-03-26")
        result = {"protocolVersion": version, "capabilities": {"tools": {}}, "serverInfo": {"name": "devconductor-memory", "version": "0.1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") if isinstance(request.get("params"), dict) else {}
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        try:
            result = call_tool(str(params.get("name") or ""), arguments)
        except PluginMemoryError as exc:
            result = tool_result({"error": str(exc)}, error=True)
    elif method == "ping":
        result = {}
    else:
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    for line in sys.stdin:
        try:
            request = json.loads(line)
            response = respond(request) if isinstance(request, dict) else None
        except (json.JSONDecodeError, OSError) as exc:
            response = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(exc)}}
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
