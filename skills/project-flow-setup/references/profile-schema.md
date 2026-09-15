# Project Profile schema v1

Project Profiles are JSON data files loaded with:

```bash
python3 server.py --profile /absolute/path/to/profile.json
```

## Fields

| Field | Type | Rule |
|---|---|---|
| `schemaVersion` | integer | Must be `1` |
| `id` | string | Lowercase kebab-case; isolates runtime task state |
| `name` | string | Human-facing project name |
| `workspaceRoot` | absolute path | Allowed root for imported requirement documents |
| `repoRoot` | absolute path | Exact primary Git root |
| `repositoryUrl` | Git remote URL | Shared project identity; defaults to `origin`, may be overridden, never a local path |
| `docsRoot` | absolute path | External or project document root |
| `worktreesRoot` | absolute path | Must not equal or sit inside `repoRoot` |
| `htmlTaskRoot` | absolute path | Must sit inside `docsRoot` |
| `defaultBaseBranch` | string | Existing local Git ref; no fetch is performed |
| `worktreeNamePrefix` | string | Safe letters/numbers plus `.`, `_`, or `-` |
| `planRelativeDir` | relative path | Destination inside each Worktree; no `..` |
| `projectFacts` | string array | Repository-relative read entrypoints; no `..` |
| `planTemplate` | string | Optional repository-relative planning template |
| `sourceReading.defaultReader` | string | Optional: `auto` (default), `manual_import`, `lark_cli`, or `codex_read_only`; resolved for each new link task |
| `sourceReading.attachmentPolicy` | string | Optional: `optional` (default) or `required`; copied into each new link task |
| `skills` | object | Arrays for `discussion`, `plan`, `execution`, `acceptanceFix`, `review` |
| `verification.sources` | string array | Logs, dashboards, test runners, or other evidence sources |
| `verification.policy` | string | Project-specific automatic/manual verification boundary |
| `capabilities.initializeSubmodules` | boolean | Initialize and verify Submodules after creating a Worktree |
| `memory.enabled` | boolean | Enable bounded shared recall and explicit publication |
| `memory.endpoint` | HTTP(S) origin | Memory Hub server origin without a path |
| `memory.teamId` | string | Stable team namespace |
| `memory.apiKeyEnv` | env name | Environment variable containing the API key; the key itself never belongs in Profile |
| `memory.maxItems` | integer | Recall limit, 1–20 |
| `memory.maxChars` | integer | Total recalled character budget, 500–20000 |
| `memory.timeoutMs` | integer | Best-effort request timeout, 200–10000 ms |
| `port` | integer | Localhost port from `1024` to `65535` |

Skill names must be lowercase kebab-case. Profiles cannot declare shell commands, hooks, environment mutation, fetch/push behavior, or arbitrary providers.

`repositoryUrl` is normalized into a runtime-only `repositoryKey` such as `github.com/team/project`. HTTPS, SSH, and scp-style forms for the same remote resolve to one key. Absolute filesystem paths and `file://` remotes are rejected as shared identity.

## Source Reading Defaults

The entire `sourceReading` object is optional. Omitting it is equivalent to:

```json
{
  "sourceReading": {
    "defaultReader": "auto",
    "attachmentPolicy": "optional"
  }
}
```

| Default reader | Lark links | Other links |
|---|---|---|
| `auto` | `manual_import` | `codex_read_only` with `optional`; `manual_import` with `required` |
| `manual_import` | `manual_import` | `manual_import` |
| `lark_cli` | `lark_cli` | Falls back to `manual_import` |
| `codex_read_only` | Falls back to `manual_import` | `codex_read_only` with `optional`; falls back to `manual_import` with `required` |

`manual_import` accepts document content obtained through any authorized source; it does not require Chrome or a Codex desktop session. `lark_cli` supports Feishu/Lark `/docx/` and `/wiki/` links and requires an available CLI and authenticated `user` identity. Missing Lark Skills are diagnostic notices, not a readiness gate. `codex_read_only` reads a link during discussion and is intended for ordinary public links without the separate material gate.

The input form can override the reader and attachment policy for a new task. Defaults are resolved before the concrete values are saved in that task's `source`. An explicitly selected incompatible reader is rejected instead of silently replaced. Profile defaults do not retroactively change existing tasks; tasks without a stored attachment policy retain `optional`.

`optional` records unread attachments and references without blocking otherwise complete body coverage. `required` blocks discussion and planning while any entry remains in `missingAttachments`; all unread attachments and references must be supplied. Both policies require a complete, nonempty body and no missing body sections when the material gate applies.

While a task is idle in discussion, the user can explicitly switch between `manual_import` and `lark_cli`, subject to link compatibility, and adjust the attachment policy. Switching readers retains earlier material revisions and discussion history but requires a fresh read or save before continuing. Changing policy re-evaluates the saved snapshot. A task that already has `sourceRead` cannot switch back to `codex_read_only` to bypass the material gate. Legacy `chrome_mcp` tasks retain the manual-import path.

`sourceReading` accepts only these bounded choices; it cannot specify custom shell commands, provider commands, executable paths, or credential locations.

## Runtime Isolation

The console stores mutable task state under `.runtime/<id>/tasks`. Profiles share the application but do not share queues or task memory.

## Directory Selection

The setup script keeps the primary repository in place. Explicit roots win; otherwise it reuses an existing sibling/project docs root and an existing external Worktree root. When no project convention exists, it falls back to `~/ProjectFlowData/<project-id>/docs` and `~/ProjectFlowData/<project-id>/worktrees`. These values are expanded to absolute paths in the generated Profile, and dry-run does not create them.

## Git Boundary

The built-in provider only performs local validation and `git worktree add`. It does not fetch, pull, push, merge, alter Git config, switch the primary checkout, or delete an existing Worktree.
