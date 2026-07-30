from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1]
SERVER_PATH = TOOL_DIR / "server.py"
SETUP_SCRIPT = TOOL_DIR / "skills" / "project-flow-setup" / "scripts" / "configure_project.py"
WORKTREE_SCRIPT = TOOL_DIR / "scripts" / "create_git_worktree.py"
SPEC = importlib.util.spec_from_file_location("project_flow_profile_server", SERVER_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


class ProjectProfileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="project-flow-profile-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "sample-repo"
        self.repo.mkdir()
        self.assertEqual(run(["git", "init", "-b", "main"], self.repo).returncode, 0)
        (self.repo / "README.md").write_text("sample\n", encoding="utf-8")
        self.assertEqual(run(["git", "add", "README.md"], self.repo).returncode, 0)
        commit = run(
            ["git", "-c", "user.name=Flow Test", "-c", "user.email=flow@example.test", "commit", "-m", "initial"],
            self.repo,
        )
        self.assertEqual(commit.returncode, 0, commit.stderr)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def profile(self) -> dict[str, object]:
        docs = self.root / "SampleDocs"
        return {
            "schemaVersion": 1,
            "id": "sample",
            "name": "Sample",
            "workspaceRoot": str(self.root),
            "repoRoot": str(self.repo),
            "docsRoot": str(docs),
            "worktreesRoot": str(self.root / "worktrees"),
            "htmlTaskRoot": str(docs / "Tasks" / "进行中"),
            "defaultBaseBranch": "main",
            "worktreeNamePrefix": "Sample",
            "planRelativeDir": "Docs/plans/active",
            "projectFacts": ["README.md"],
            "planTemplate": "",
            "skills": {"discussion": [], "plan": [], "execution": [], "acceptanceFix": [], "review": []},
            "verification": {"sources": ["test output"], "policy": "Run local tests."},
            "capabilities": {"initializeSubmodules": False},
            "port": 4320,
        }

    def test_profile_rejects_missing_fields_and_relative_paths(self) -> None:
        with self.assertRaisesRegex(server.WorkflowError, "schemaVersion"):
            server.validate_project_profile({})
        profile = self.profile()
        profile["repoRoot"] = "relative/repo"
        with self.assertRaisesRegex(server.WorkflowError, "绝对路径"):
            server.validate_project_profile(profile, require_repo=False)

    def test_profile_rejects_worktree_root_inside_repo(self) -> None:
        profile = self.profile()
        profile["worktreesRoot"] = str(self.repo / "worktrees")
        with self.assertRaisesRegex(server.WorkflowError, "worktreesRoot"):
            server.validate_project_profile(profile, require_repo=False)

    def test_profile_loads_and_normalizes_a_real_git_root(self) -> None:
        path = self.root / "sample.json"
        path.write_text(json.dumps(self.profile()), encoding="utf-8")
        loaded = server.load_project_profile(path)
        self.assertEqual(loaded["repoRoot"], str(self.repo.resolve()))
        self.assertEqual(loaded["defaultBaseBranch"], "main")

    def test_setup_dry_run_does_not_write_then_formal_run_generates_profile(self) -> None:
        profiles = self.root / "profiles"
        command = [
            "python3", str(SETUP_SCRIPT), str(self.repo), "--profiles-dir", str(profiles),
            "--id", "sample-project", "--port", "4321",
        ]
        preview = run([*command, "--dry-run"])
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("Dry run: no directories or files were created.", preview.stdout)
        self.assertFalse(profiles.exists())

        generated = run(command)
        self.assertEqual(generated.returncode, 0, generated.stderr)
        profile_path = profiles / "sample-project.json"
        self.assertTrue(profile_path.is_file())
        profile = server.load_project_profile(profile_path)
        self.assertEqual(profile["repoRoot"], str(self.repo.resolve()))
        self.assertEqual(profile["port"], 4321)

    def test_setup_rejects_non_git_and_detached_head(self) -> None:
        plain = self.root / "plain"
        plain.mkdir()
        non_git = run(["python3", str(SETUP_SCRIPT), str(plain), "--dry-run"])
        self.assertEqual(non_git.returncode, 2)

        self.assertEqual(run(["git", "checkout", "--detach"], self.repo).returncode, 0)
        detached = run(["python3", str(SETUP_SCRIPT), str(self.repo), "--dry-run"])
        self.assertEqual(detached.returncode, 2)
        self.assertIn("detached HEAD", detached.stderr)

    def test_generic_worktree_provider_dry_run_and_create(self) -> None:
        parent = self.root / "worktrees"
        command = [
            "python3", str(WORKTREE_SCRIPT), "Sample_readable-task-flow_12345678",
            "--repo", str(self.repo), "--parent", str(parent), "--base", "main",
        ]
        preview = run([*command, "--dry-run"])
        self.assertEqual(preview.returncode, 0, preview.stderr)
        target = parent / "Sample_readable-task-flow_12345678"
        self.assertFalse(target.exists())

        created = run(command)
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(
            run(["git", "branch", "--show-current"], target).stdout.strip(),
            "worktree/Sample_readable-task-flow_12345678",
        )


if __name__ == "__main__":
    unittest.main()
