from __future__ import annotations

import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1]
HUB_PATH = TOOL_DIR / "hub.py"
SPEC = importlib.util.spec_from_file_location("dev_conductor_hub", HUB_PATH)
assert SPEC and SPEC.loader
hub = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hub)


def run(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)


class ProjectHubTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="dev-conductor-hub-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "sample-repo"
        self.repo.mkdir()
        self.assertEqual(run(["git", "init", "-b", "main"], self.repo).returncode, 0)
        (self.repo / "README.md").write_text("sample\n", encoding="utf-8")
        self.assertEqual(run(["git", "add", "README.md"], self.repo).returncode, 0)
        commit = run(
            ["git", "-c", "user.name=Hub Test", "-c", "user.email=hub@example.test", "commit", "-m", "initial"],
            self.repo,
        )
        self.assertEqual(commit.returncode, 0, commit.stderr)
        self.profiles = self.root / "profiles"
        self.profiles.mkdir()
        self.profile_path = self.profiles / "sample.json"
        self.profile_path.write_text(json.dumps(self.profile()), encoding="utf-8")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def profile(self) -> dict[str, object]:
        docs = self.root / "SampleDocs"
        return {
            "schemaVersion": 1,
            "id": "sample",
            "name": "Sample Project",
            "workspaceRoot": str(self.root),
            "repoRoot": str(self.repo),
            "docsRoot": str(docs),
            "worktreesRoot": str(self.root / "worktrees"),
            "htmlTaskRoot": str(docs / "tasks" / "active"),
            "defaultBaseBranch": "main",
            "worktreeNamePrefix": "Sample",
            "planRelativeDir": "Docs/plans/active",
            "projectFacts": ["README.md"],
            "planTemplate": "",
            "skills": {"discussion": [], "plan": [], "execution": [], "acceptanceFix": [], "review": []},
            "verification": {"sources": ["test output"], "policy": "Run tests."},
            "capabilities": {"initializeSubmodules": False},
            "port": 4320,
        }

    def registry(self) -> object:
        return hub.ProjectRegistry(
            self.profiles,
            self.root / "runtime" / "projects.json",
            self.root / ".runtime",
        )

    def test_discovery_loads_profiles_and_runtime_counts_without_starting_workers(self) -> None:
        task_root = self.root / ".runtime" / "sample" / "tasks" / "task-1"
        task_root.mkdir(parents=True)
        task_root.joinpath("task.json").write_text(json.dumps({
            "id": "task-1", "activeJob": "execution", "jobState": "running", "archivedAt": "",
            "git": {"committed": False}, "knowledge": {"candidates": [{"status": "pending"}]},
        }), encoding="utf-8")
        projects, errors = self.registry().discover()
        self.assertEqual(errors, [])
        self.assertEqual(projects[0]["id"], "sample")
        self.assertEqual(projects[0]["counts"]["running"], 1)
        self.assertEqual(projects[0]["counts"]["knowledgePending"], 1)

    def test_external_profile_registration_persists_only_its_absolute_reference(self) -> None:
        external = self.root / "external" / "sample.json"
        external.parent.mkdir()
        external.write_text(json.dumps(self.profile()), encoding="utf-8")
        registry = self.registry()
        result = registry.register_profile(external)
        saved = json.loads(registry.registry_path.read_text(encoding="utf-8"))
        self.assertEqual(result["id"], "sample")
        self.assertEqual(saved["profiles"], [str(external.resolve())])

    def test_existing_profile_preview_is_read_only_then_confirmation_registers(self) -> None:
        external = self.root / "external" / "sample.json"
        external.parent.mkdir()
        external.write_text(json.dumps(self.profile()), encoding="utf-8")
        registry = self.registry()
        preview = registry.setup_project({"profilePath": str(external)}, dry_run=True)
        self.assertEqual(preview["profile"]["name"], "Sample Project")
        self.assertFalse(registry.registry_path.exists())
        registry.setup_project({"profilePath": str(external)}, dry_run=False)
        self.assertTrue(registry.registry_path.is_file())

    def test_worker_response_urls_are_scoped_to_the_owning_project(self) -> None:
        value = {"htmlUrl": "/task-html/plan.html", "nested": ["/task-html/check.html", "/api/tasks"]}
        rewritten = hub.rewrite_project_urls(value, "sample")
        self.assertEqual(rewritten["htmlUrl"], "/projects/sample/task-html/plan.html")
        self.assertEqual(rewritten["nested"][0], "/projects/sample/task-html/check.html")
        self.assertEqual(rewritten["nested"][1], "/api/tasks")

    def test_frontend_and_startup_expose_multi_project_entrypoints(self) -> None:
        app = (TOOL_DIR / "app.js").read_text(encoding="utf-8")
        html = (TOOL_DIR / "index.html").read_text(encoding="utf-8")
        start = (TOOL_DIR / "start.command").read_text(encoding="utf-8")
        self.assertIn('fetch("/api/hub/projects"', app)
        self.assertIn('id="projectRail"', html)
        self.assertIn('id="hubDashboard"', html)
        self.assertIn('id="addProjectDialog"', html)
        self.assertIn('id="addProjectRepositoryUrl"', html)
        self.assertIn('data-knowledge-publish', app)
        self.assertIn('"$SCRIPT_DIR/hub.py"', start)


if __name__ == "__main__":
    unittest.main()
