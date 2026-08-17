#!/usr/bin/env python3
"""Best-effort Codex hook that injects bounded shared memory context."""

from __future__ import annotations

import json
import sys

from memory_lib import PluginMemoryError, format_context, search


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, OSError):
        print("{}")
        return 0
    event = str(payload.get("hook_event_name") or payload.get("hookEventName") or "")
    cwd = payload.get("cwd") or payload.get("workspace") or ""
    prompt = str(payload.get("prompt") or payload.get("user_prompt") or payload.get("userPrompt") or "")
    if event == "SessionStart":
        query = "project architecture decisions conventions workflow runbook pitfalls acceptance"
    elif event == "PostCompact":
        query = "current project decisions constraints runbook pitfalls acceptance"
    elif event == "UserPromptSubmit":
        query = prompt
    else:
        print("{}")
        return 0
    try:
        context = format_context(search(query, cwd=cwd))
    except PluginMemoryError:
        context = ""
    if not context:
        print("{}")
        return 0
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": context,
        }
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
