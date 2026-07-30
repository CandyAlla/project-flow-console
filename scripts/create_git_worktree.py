#!/usr/bin/env python3
"""Create a linked Git worktree without fetching, pushing, or changing the primary checkout."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)


def require_ok(result: subprocess.CompletedProcess[str], label: str) -> str:
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown error"
        raise SystemExit(f"{label} failed: {message}")
    return result.stdout.strip()


def run_visible(command: list[str], label: str, preserve_note: str = "") -> str:
    result = run(command)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        note = f"\n{preserve_note}" if preserve_note else ""
        raise SystemExit(f"{label} failed: {result.stderr.strip() or result.stdout.strip()}{note}")
    return result.stdout.strip()


def sanitize_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-._")
    if not cleaned or len(cleaned) > 80:
        raise SystemExit("Worktree name must become 1–80 safe characters after sanitizing.")
    return cleaned


def verify_repo_root(repo: Path) -> None:
    top = require_ok(run(["git", "-C", str(repo), "rev-parse", "--show-toplevel"]), "git repo lookup")
    if Path(top).resolve() != repo:
        raise SystemExit(f"Expected Git root {repo}, got {top}")
    branch = require_ok(run(["git", "-C", str(repo), "branch", "--show-current"]), "branch lookup")
    if not branch:
        raise SystemExit("Primary repository is in detached HEAD state.")
    for ref in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if run(["git", "-C", str(repo), "rev-parse", "--verify", "-q", ref]).returncode == 0:
            raise SystemExit(f"Primary repository has an unfinished Git operation: {ref}")


def submodule_commands(worktree: Path) -> list[list[str]]:
    return [
        ["git", "-C", str(worktree), "submodule", "sync", "--recursive"],
        ["git", "-C", str(worktree), "submodule", "update", "--init", "--recursive"],
        ["git", "-C", str(worktree), "submodule", "status", "--recursive"],
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a conservative linked Git worktree.")
    parser.add_argument("name", help="Worktree directory name")
    parser.add_argument("--repo", required=True, help="Absolute primary Git repository root")
    parser.add_argument("--parent", required=True, help="Absolute parent directory for worktrees")
    parser.add_argument("--base", required=True, help="Existing local base ref")
    parser.add_argument("--branch", help="Branch name; defaults to worktree/<name>")
    parser.add_argument("--init-submodules", action="store_true", help="Initialize and verify submodules")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without changing anything")
    args = parser.parse_args()

    raw_repo = Path(args.repo).expanduser()
    raw_parent = Path(args.parent).expanduser()
    if not raw_repo.is_absolute() or not raw_parent.is_absolute():
        raise SystemExit("--repo and --parent must be absolute paths.")
    repo = raw_repo.resolve()
    parent = raw_parent.resolve()
    safe_name = sanitize_name(args.name)
    worktree = parent / safe_name
    branch = args.branch or f"worktree/{safe_name}"

    verify_repo_root(repo)
    if worktree.exists():
        raise SystemExit(f"Target worktree path already exists: {worktree}")
    if worktree == repo or repo in worktree.parents:
        raise SystemExit("Refusing to create a worktree inside the primary repository.")
    require_ok(
        run(["git", "-C", str(repo), "rev-parse", "--verify", f"{args.base}^{{commit}}"]),
        f"base ref {args.base}",
    )

    status = require_ok(run(["git", "-C", str(repo), "status", "--short", "--branch"]), "git status")
    existing = require_ok(run(["git", "-C", str(repo), "worktree", "list"]), "git worktree list")
    branch_check = run(["git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"])
    if branch_check.returncode == 0:
        command = ["git", "-C", str(repo), "worktree", "add", str(worktree), branch]
        branch_mode = "existing"
    elif branch_check.returncode == 1:
        command = ["git", "-C", str(repo), "worktree", "add", "-b", branch, str(worktree), args.base]
        branch_mode = "new"
    else:
        raise SystemExit("Failed to determine whether the target branch exists.")

    print(f"Repo: {repo}")
    print(f"Target: {worktree}")
    print(f"Branch: {branch} ({branch_mode})")
    print(f"Base: {args.base}")
    print("Status:")
    for line in status.splitlines():
        print(f"  {line}")
    print("Existing worktrees:")
    for line in existing.splitlines():
        print(f"  {line}")
    print("Command:")
    print("  " + shlex.join(command))
    if args.init_submodules:
        print("Post-create commands:")
        for post_create in submodule_commands(worktree):
            print("  " + shlex.join(post_create))
    else:
        print("Post-create: submodule initialization disabled by Project Profile.")
    print("Note: no fetch, push, merge, checkout of the primary repo, or Git config write will run.")

    if args.dry_run:
        print("Dry run: no changes made.")
        return 0

    parent.mkdir(parents=True, exist_ok=True)
    result = run(command)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        return result.returncode

    actual_root = require_ok(run(["git", "-C", str(worktree), "rev-parse", "--show-toplevel"]), "root verification")
    if Path(actual_root).resolve() != worktree.resolve():
        raise SystemExit(f"Created worktree root mismatch: {actual_root}")
    preserve_note = f"Worktree preserved at {worktree}."
    submodule_status = ""
    if args.init_submodules:
        commands = submodule_commands(worktree)
        run_visible(commands[0], "submodule sync", preserve_note)
        run_visible(commands[1], "submodule update", preserve_note)
        submodule_status = require_ok(run(commands[2]), "submodule status verification")
        invalid = [line for line in submodule_status.splitlines() if line[:1] in {"-", "+", "U"}]
        if invalid:
            raise SystemExit("Submodule verification failed:\n" + "\n".join(f"  {line}" for line in invalid) + f"\n{preserve_note}")

    actual_branch = require_ok(run(["git", "-C", str(worktree), "branch", "--show-current"]), "branch verification")
    actual_head = require_ok(run(["git", "-C", str(worktree), "rev-parse", "HEAD"]), "HEAD verification")
    if actual_branch != branch:
        raise SystemExit(f"Created worktree branch mismatch: expected {branch}, got {actual_branch}")
    created_status = require_ok(run(["git", "-C", str(worktree), "status", "--short", "--branch"]), "status verification")
    print("Verified:")
    print(f"  Root: {actual_root}")
    print(f"  Branch: {actual_branch}")
    print(f"  HEAD: {actual_head}")
    print(f"  Submodules: {'verified' if args.init_submodules else 'not requested'}")
    if submodule_status:
        for line in submodule_status.splitlines():
            print(f"  Submodule: {line}")
    for line in created_status.splitlines():
        print(f"  Status: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
