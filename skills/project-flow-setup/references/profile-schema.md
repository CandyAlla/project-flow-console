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

## Runtime Isolation

The console stores mutable task state under `.runtime/<id>/tasks`. Profiles share the application but do not share queues or task memory.

## Directory Selection

The setup script keeps the primary repository in place. Explicit roots win; otherwise it reuses an existing sibling/project docs root and an existing external Worktree root. When no project convention exists, it falls back to `~/ProjectFlowData/<project-id>/docs` and `~/ProjectFlowData/<project-id>/worktrees`. These values are expanded to absolute paths in the generated Profile, and dry-run does not create them.

## Git Boundary

The built-in provider only performs local validation and `git worktree add`. It does not fetch, pull, push, merge, alter Git config, switch the primary checkout, or delete an existing Worktree.
