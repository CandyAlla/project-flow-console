---
name: project-flow-setup
description: Configure any local Git project for the shared Project Flow requirement console by scanning repository facts and skills, validating safe repository/docs/worktree boundaries, and generating a versioned Project Profile JSON. Use when the user asks to configure, initialize, migrate, or reuse the requirement workflow console in another project; mentions Project Flow/Profile; or wants project paths, Git worktrees, stage skills, and verification sources configured through one skill.
---

# Project Flow Setup

Configure a project without modifying its code, creating a Worktree, starting implementation, committing, fetching, pushing, or merging. Keep the generated Profile beside the shared console so it remains the single configuration entrypoint.

## Workflow

1. Resolve the user-supplied absolute path with `git rev-parse --show-toplevel`.
2. Read the repository `AGENTS.md` and the smallest relevant docs/Skill indexes. Search common roots such as `Doc/Skills`, `Docs/Skills`, and `.codex/skills`.
3. Identify:
   - workspace, repository, docs, HTML task, and Worktree roots;
   - current/default base branch and Worktree name prefix;
   - Plan directory and project fact entrypoints;
   - discussion, plan, execution, acceptance-fix, and review Skills;
   - verification/log sources and whether Submodules are required.
4. Ask only for missing choices that materially change behavior. Do not ask for facts the scan can establish.
5. Read [references/profile-schema.md](references/profile-schema.md) when changing fields or validating a nonstandard layout.
6. Run `scripts/configure_project.py` with `--dry-run` first. Report its resolved paths, branch, Skill chains, warnings, and target Profile path.
7. After user confirmation, rerun without `--dry-run`. Use `--force` only after explicit approval to replace an existing Profile.
8. Run the console's profile tests or at minimum load the generated JSON through `server.py --profile <path> --help` and report the launch command.

## Command Pattern

```bash
python3 scripts/configure_project.py /absolute/project/path --dry-run
python3 scripts/configure_project.py /absolute/project/path
```

Add explicit options only when discovery is wrong or the user selected a different behavior. Prefer repeated stage options such as `--execution-skill workmission` over editing JSON manually.

## Safety Contract

- Require an absolute input path and a real, non-detached Git root.
- Stop on unfinished Merge, Rebase, Cherry-pick, or Revert state.
- Require the Worktree root to remain outside the primary repository.
- Treat Profile values as data. Never place shell snippets or arbitrary commands in a Profile.
- Keep `projectFacts`, `planTemplate`, and `planRelativeDir` repository-relative and free of `..`.
- A dry-run must not create directories or files.
- Writing a Profile must not edit the target repository.
- Do not create a Worktree, run Codex execution, start the service, Commit, Push, or Merge unless the user separately requests that action.

## Handoff

Report the absolute Profile path, detected base branch, configured stage Skills, warnings, and exact launch command. If a configured Skill is not discoverable, state that before calling the setup complete.
