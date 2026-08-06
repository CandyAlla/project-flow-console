#!/usr/bin/env python3
"""Discover and write a safe Project Flow Profile for a local Git repository."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any


TOOL_DIR = Path(__file__).resolve().parents[3]
DEFAULT_PROFILES_DIR = TOOL_DIR / "profiles"
PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PREFIX_PATTERN = re.compile(r"^[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*$")
SKILL_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
DEFAULT_SKILLS = {
    "discussion": ["discussion-only", "ask-first", "project-collaboration-flow"],
    "plan": ["prd-to-plan", "clear-html"],
    "execution": ["workmission", "change-guard"],
    "acceptanceFix": ["change-guard"],
    "review": ["code-review"],
}


class SetupError(RuntimeError):
    pass


def run_git(repo: Path, arguments: list[str], *, allow_failure: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 and not allow_failure:
        raise SetupError((result.stderr or result.stdout or "Git command failed").strip())
    return result


def require_absolute(value: str, label: str) -> Path:
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        raise SetupError(f"{label} must be an absolute path: {value}")
    return candidate.resolve(strict=False)


def safe_relative(value: str, label: str, *, allow_empty: bool = False) -> str:
    raw = value.strip().replace("\\", "/")
    if allow_empty and not raw:
        return ""
    candidate = Path(raw)
    if not raw or candidate.is_absolute() or ".." in candidate.parts or "." in candidate.parts:
        raise SetupError(f"{label} must be a repository-relative path without '..': {value}")
    return candidate.as_posix().strip("/")


def inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def slug(value: str, fallback_seed: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii").lower()
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized[:48] or f"project-{hashlib.sha256(fallback_seed.encode()).hexdigest()[:8]}"


def prefix(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", normalized).strip("-._")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized[:40] or "Project"


def resolve_repo(input_path: Path) -> Path:
    if not input_path.exists():
        raise SetupError(f"Project path does not exist: {input_path}")
    result = run_git(input_path, ["rev-parse", "--show-toplevel"])
    repo = Path(result.stdout.strip()).resolve()
    if not repo.is_dir():
        raise SetupError(f"Git root is not a directory: {repo}")
    branch = run_git(repo, ["branch", "--show-current"]).stdout.strip()
    if not branch:
        raise SetupError("Repository is in detached HEAD state.")
    for ref in ("MERGE_HEAD", "REBASE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        if run_git(repo, ["rev-parse", "--verify", "-q", ref], allow_failure=True).returncode == 0:
            raise SetupError(f"Repository has an unfinished Git operation: {ref}")
    return repo


def validate_base(repo: Path, value: str) -> str:
    base = value.strip()
    if not base:
        raise SetupError("Default base branch cannot be empty.")
    if run_git(repo, ["check-ref-format", "--branch", base], allow_failure=True).returncode != 0:
        raise SetupError(f"Invalid default base branch: {base}")
    if run_git(repo, ["rev-parse", "--verify", f"{base}^{{commit}}"], allow_failure=True).returncode != 0:
        raise SetupError(f"Default base branch/ref does not exist locally: {base}")
    return base


def detect_docs(repo: Path) -> Path | None:
    sibling = repo.parent / f"{repo.name}Docs"
    for candidate in (sibling, repo / "Docs", repo / "Doc"):
        if candidate.is_dir():
            return candidate.resolve()
    return None


def detect_worktrees(repo: Path) -> Path | None:
    candidates = (
        repo.parent / "worktrees",
        repo.parent / "Worktrees",
        repo.parent / f"{repo.name}Worktrees",
    )
    for candidate in candidates:
        if candidate.is_dir() and not inside(candidate.resolve(), repo):
            return candidate.resolve()
    return None


def detect_html_task_root(docs: Path) -> Path:
    candidates = (
        docs / "Tasks" / "进行中",
        docs / "tasks" / "active",
        docs / "Tasks" / "active",
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()
    return (docs / "tasks" / "active").resolve(strict=False)


def detect_plan_dir(repo: Path) -> str:
    for candidate in ("Docs/plans/active", "Doc/plans/active"):
        if (repo / candidate).is_dir():
            return candidate
    if (repo / "Docs").is_dir():
        return "Docs/plans/active"
    if (repo / "Doc").is_dir():
        return "Doc/plans/active"
    return "Docs/plans/active"


def detect_facts(repo: Path) -> list[str]:
    candidates = [
        "AGENTS.md",
        "Doc/index.md",
        "Docs/index.md",
        "Doc/rules/ai-workflow.md",
        "Docs/rules/ai-workflow.md",
        "Doc/Skills/README.md",
        "Docs/Skills/README.md",
    ]
    return [candidate for candidate in candidates if (repo / candidate).is_file()]


def detect_plan_template(repo: Path) -> str:
    for candidate in ("Doc/rules/prd-analysis-template.md", "Docs/rules/prd-analysis-template.md"):
        if (repo / candidate).is_file():
            return candidate
    return ""


def skill_roots(repo: Path) -> list[Path]:
    roots = [repo / "Doc" / "Skills", repo / "Docs" / "Skills", repo / ".codex" / "skills"]
    personal = Path.home() / ".codex" / "skills"
    if personal not in roots:
        roots.append(personal)
    return roots


def skill_exists(repo: Path, name: str) -> bool:
    return any((root / name / "SKILL.md").is_file() for root in skill_roots(repo))


def stage_skills(repo: Path, explicit: list[str] | None, stage: str, no_defaults: bool) -> list[str]:
    values = explicit if explicit is not None else ([] if no_defaults else DEFAULT_SKILLS[stage])
    cleaned = list(dict.fromkeys(item.strip() for item in values if item.strip()))
    if any(not SKILL_PATTERN.fullmatch(item) for item in cleaned):
        raise SetupError(f"Invalid {stage} Skill name; use lowercase kebab-case.")
    if explicit is None and not no_defaults:
        return [item for item in cleaned if skill_exists(repo, item)]
    return cleaned


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Configure a Git repository for Project Flow.")
    parser.add_argument("project", help="Absolute project path inside the target Git repository")
    parser.add_argument("--name", help="Human-facing project name; defaults to repository directory name")
    parser.add_argument("--id", dest="project_id", help="Lowercase kebab-case project id")
    parser.add_argument("--workspace-root", help="Absolute workspace root")
    parser.add_argument("--docs-root", help="Absolute docs root")
    parser.add_argument("--worktrees-root", help="Absolute Worktree parent outside the primary repo")
    parser.add_argument(
        "--managed-root",
        help="Absolute fallback data root; defaults to ~/ProjectFlowData and is only used when no existing or explicit docs/Worktree root is found",
    )
    parser.add_argument("--html-task-root", help="Absolute HTML task root inside docsRoot")
    parser.add_argument("--base", help="Existing local base branch/ref; defaults to current branch")
    parser.add_argument("--worktree-prefix", help="Safe Worktree directory prefix")
    parser.add_argument("--plan-dir", help="Plan destination relative to Worktree; defaults from existing Docs/Doc layout")
    parser.add_argument("--fact", action="append", help="Repository-relative fact entrypoint; repeatable")
    parser.add_argument("--plan-template", help="Optional repository-relative planning template")
    parser.add_argument("--discussion-skill", action="append")
    parser.add_argument("--plan-skill", action="append")
    parser.add_argument("--execution-skill", action="append")
    parser.add_argument("--acceptance-fix-skill", action="append")
    parser.add_argument("--review-skill", action="append")
    parser.add_argument("--no-default-skills", action="store_true", help="Do not auto-add discoverable standard Skills")
    parser.add_argument("--verification-source", action="append", help="Manual evidence/log source; repeatable")
    parser.add_argument(
        "--verification-policy",
        default="按项目规则完成可自动执行的定向验证；无法运行的编译、编辑器或真机检查明确留给人工验收。",
    )
    parser.add_argument("--init-submodules", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--port", type=int, default=4318)
    parser.add_argument("--profiles-dir", default=str(DEFAULT_PROFILES_DIR), help="Absolute Profile output directory")
    parser.add_argument("--force", action="store_true", help="Replace an existing Profile")
    parser.add_argument("--dry-run", action="store_true", help="Print resolved Profile without writing")
    return parser


def configure(args: argparse.Namespace) -> tuple[dict[str, Any], Path, list[str]]:
    input_path = require_absolute(args.project, "project")
    repo = resolve_repo(input_path)
    current_branch = run_git(repo, ["branch", "--show-current"]).stdout.strip()
    project_name = (args.name or repo.name).strip()
    if not project_name or len(project_name) > 80:
        raise SetupError("Project name must be 1–80 characters.")
    project_id = (args.project_id or slug(project_name, str(repo))).strip()
    if not PROFILE_ID_PATTERN.fullmatch(project_id):
        raise SetupError("Project id must be lowercase kebab-case.")
    worktree_prefix = (args.worktree_prefix or prefix(project_name)).strip()
    if not PREFIX_PATTERN.fullmatch(worktree_prefix) or len(worktree_prefix) > 40:
        raise SetupError("Worktree prefix contains unsafe characters.")

    workspace = require_absolute(args.workspace_root, "workspaceRoot") if args.workspace_root else repo.parent.resolve()
    managed_parent = require_absolute(args.managed_root, "managedRoot") if args.managed_root else (Path.home() / "ProjectFlowData").resolve()
    managed_project = managed_parent / project_id
    detected_docs = detect_docs(repo) if not args.docs_root else None
    detected_worktrees = detect_worktrees(repo) if not args.worktrees_root else None
    docs = require_absolute(args.docs_root, "docsRoot") if args.docs_root else detected_docs or managed_project / "docs"
    worktrees = require_absolute(args.worktrees_root, "worktreesRoot") if args.worktrees_root else detected_worktrees or managed_project / "worktrees"
    html_root = require_absolute(args.html_task_root, "htmlTaskRoot") if args.html_task_root else detect_html_task_root(docs)
    if worktrees == repo or inside(worktrees, repo):
        raise SetupError("worktreesRoot must remain outside the primary repository.")
    if not inside(html_root, docs):
        raise SetupError("htmlTaskRoot must be inside docsRoot.")
    base = validate_base(repo, args.base or current_branch)
    plan_dir = safe_relative(args.plan_dir or detect_plan_dir(repo), "planRelativeDir")
    facts = [safe_relative(item, "projectFacts[]") for item in (args.fact if args.fact is not None else detect_facts(repo))]
    plan_template = safe_relative(
        args.plan_template if args.plan_template is not None else detect_plan_template(repo),
        "planTemplate",
        allow_empty=True,
    )
    skills = {
        "discussion": stage_skills(repo, args.discussion_skill, "discussion", args.no_default_skills),
        "plan": stage_skills(repo, args.plan_skill, "plan", args.no_default_skills),
        "execution": stage_skills(repo, args.execution_skill, "execution", args.no_default_skills),
        "acceptanceFix": stage_skills(repo, args.acceptance_fix_skill, "acceptanceFix", args.no_default_skills),
        "review": stage_skills(repo, args.review_skill, "review", args.no_default_skills),
    }
    sources = list(dict.fromkeys(item.strip() for item in (args.verification_source or ["应用日志", "项目测试工具"]) if item.strip()))
    if not sources:
        raise SetupError("At least one verification source is required.")
    if not 1024 <= args.port <= 65535:
        raise SetupError("Port must be between 1024 and 65535.")
    init_submodules = (repo / ".gitmodules").is_file() if args.init_submodules is None else args.init_submodules
    profiles_dir = require_absolute(args.profiles_dir, "profilesDir")
    profile_path = profiles_dir / f"{project_id}.json"
    warnings: list[str] = []
    missing_facts = [item for item in facts if not (repo / item).exists()]
    if missing_facts:
        warnings.append("Configured fact paths do not exist yet: " + ", ".join(missing_facts))
    missing_skills = [name for names in skills.values() for name in names if not skill_exists(repo, name)]
    if missing_skills:
        warnings.append("Configured Skills are not currently discoverable: " + ", ".join(dict.fromkeys(missing_skills)))
    if not args.docs_root and detected_docs is None:
        warnings.append(f"No existing docs root detected; using managed fallback: {docs}")
    elif not docs.exists():
        warnings.append(f"docsRoot does not exist yet; the console will create it on startup: {docs}")
    if not args.worktrees_root and detected_worktrees is None:
        warnings.append(f"No existing Worktree root detected; using managed fallback: {worktrees}")
    profile = {
        "schemaVersion": 1,
        "id": project_id,
        "name": project_name,
        "workspaceRoot": str(workspace),
        "repoRoot": str(repo),
        "docsRoot": str(docs),
        "worktreesRoot": str(worktrees),
        "htmlTaskRoot": str(html_root),
        "defaultBaseBranch": base,
        "worktreeNamePrefix": worktree_prefix,
        "planRelativeDir": plan_dir,
        "projectFacts": facts,
        "planTemplate": plan_template,
        "skills": skills,
        "verification": {"sources": sources, "policy": args.verification_policy.strip()},
        "capabilities": {"initializeSubmodules": bool(init_submodules)},
        "port": args.port,
    }
    return profile, profile_path, warnings


def main() -> int:
    args = build_parser().parse_args()
    try:
        profile, profile_path, warnings = configure(args)
        print(json.dumps(profile, ensure_ascii=False, indent=2))
        print(f"\nProfile target: {profile_path}")
        for warning in warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        if args.dry_run:
            print("Dry run: no directories or files were created.")
            return 0
        if profile_path.exists() and not args.force:
            raise SetupError(f"Profile already exists; rerun with --force only after approval: {profile_path}")
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Profile written: {profile_path}")
        print(f"Launch: python3 {TOOL_DIR / 'server.py'} --profile {profile_path}")
        return 0
    except SetupError as exc:
        print(f"project-flow-setup: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
