---
name: devconductor-memory
description: Search, read, or explicitly capture shared DevConductor Memory Hub knowledge across computers, team members, and Git projects. Use when the user asks what was previously decided, wants reusable project knowledge, requests cross-project memory, or explicitly asks to save a stable fact, decision, runbook, pitfall, or acceptance rule.
---

# DevConductor Memory

Use the plugin's Memory Hub tools as an auxiliary knowledge source. Current repository code, configuration, tests, Plan, and Git state always override recalled memory when they conflict.

## Identity and recall

- Derive project identity from Git `origin` by default.
- Use `DEVCONDUCTOR_REPOSITORY_URL` only as an explicit override.
- Never use or upload a local absolute path as shared identity.
- Prefer `memory_search` for a concrete question and `knowledge_search` for reusable engineering guidance.
- Read an individual item with `memory_read` when the full evidence is needed.

## Writes

- Do not write memory merely because a conversation ended.
- Use `memory_capture` only after the user explicitly authorizes saving the reviewed content.
- Use `memory_publish_candidate` when content still needs a separate human review. Candidate memories are not included in normal recall.
- Store concise stable facts, decisions, runbooks, pitfalls, acceptance rules, Skill candidates, or automation candidates. Do not upload complete chats, secrets, API keys, tokens, raw logs, personal paths, or unrelated source code.
- Choose `project` scope for one Git repository and `team` only when the knowledge genuinely applies across projects.

## Failure behavior

If the Memory Hub is unavailable, continue with repository facts and say that shared memory was not consulted. Never block normal coding or review work solely because recall failed.
