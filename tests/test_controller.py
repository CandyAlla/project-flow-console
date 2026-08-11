from __future__ import annotations

import importlib.util
import base64
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
SPEC = importlib.util.spec_from_file_location("requirement_flow_server", SERVER_PATH)
assert SPEC and SPEC.loader
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


def run(command: list[str], cwd: Path) -> None:
    result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)


class ControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="project-flow-test-")
        self.root = Path(self.temp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        run(["git", "init", "-b", "main"], self.repo)
        (self.repo / "README.md").write_text("baseline\n", encoding="utf-8")
        run(["git", "add", "README.md"], self.repo)
        run(["git", "-c", "user.name=Flow Test", "-c", "user.email=flow@example.test", "commit", "-m", "baseline"], self.repo)
        self.old_task_root = server.TASK_ROOT
        self.old_job_slots = server.JOB_SLOTS
        self.old_env = {key: os.environ.get(key) for key in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL")}
        server.TASK_ROOT = self.root / "state"
        os.environ.update({
            "GIT_AUTHOR_NAME": "Flow Test",
            "GIT_AUTHOR_EMAIL": "flow@example.test",
            "GIT_COMMITTER_NAME": "Flow Test",
            "GIT_COMMITTER_EMAIL": "flow@example.test",
        })
        server.TASKS.clear()
        server.ACTIVE_THREADS.clear()
        server.ACTIVE_PROCESSES.clear()
        server.ACTIVE_APP_TURNS.clear()
        server.CANCEL_REQUESTED.clear()
        server.JOB_SLOTS = threading.BoundedSemaphore(2)

    def tearDown(self) -> None:
        server.TASKS.clear()
        server.ACTIVE_THREADS.clear()
        server.ACTIVE_PROCESSES.clear()
        server.ACTIVE_APP_TURNS.clear()
        server.CANCEL_REQUESTED.clear()
        server.TASK_ROOT = self.old_task_root
        server.JOB_SLOTS = self.old_job_slots
        for key, value in self.old_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        self.temp.cleanup()

    def seed_task(self) -> str:
        task_id = "00000000-0000-0000-0000-000000000001"
        task = {
            "id": task_id,
            "updatedAt": "",
            "stage": "commit",
            "maxStageIndex": 6,
            "events": [],
            "worktree": {"path": str(self.repo)},
            "verification": {"approved": True},
            "git": {"committed": False, "commitId": ""},
        }
        server.TASKS[task_id] = task
        return task_id

    def seed_execution_task(self, task_id: str = "00000000-0000-0000-0000-000000000051") -> str:
        status = server.git_status(self.repo)
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "Codex App 快速模式",
            "createdAt": "2026-07-31T10:00:00+08:00",
            "updatedAt": "2026-07-31T10:00:00+08:00",
            "stage": "execute",
            "maxStageIndex": server.STAGE_INDEX["execute"],
            "activeJob": None,
            "jobState": "idle",
            "sessions": {"discussion": None, "execution": None, "review": None, "ask": None, "app": None, "codexApp": None},
            "discussion": {"status": "ready", "result": {"summary": "需求已确认"}, "messages": []},
            "plan": {"status": "ready", "approved": True, "finalPath": str(self.repo / "plan.md"), "markdown": "# Plan"},
            "paths": {"planRelative": "plan.md", "htmlRelative": ""},
            "worktree": {"status": "ready", "path": str(self.repo), "branch": "main", "name": "quick-mode"},
            "execution": {"status": "idle", "phase": "idle", "threadId": None, "result": None, "review": None, "logs": [], "error": ""},
            "ask": {"status": "idle", "threadId": None, "messages": [], "logs": [], "error": ""},
            "app": {"status": "idle", "threadId": None, "turnId": None, "deepLink": "", "cwd": str(self.repo), "logs": [], "error": ""},
            "codexApp": server.default_codex_app_chat(self.repo),
            "verification": {"approved": False, "checks": [], "note": ""},
            "git": {**status, "committed": False, "commitId": ""},
            "bugfix": {"status": "idle", "description": "", "history": []},
            "events": [],
        }
        return task_id

    def quick_result(self) -> dict[str, object]:
        return {
            "summary": "快速修改与自检完成",
            "changed_files": ["feature.cs"],
            "verification": [{"check": "静态检查", "result": "通过", "status": "passed"}],
            "minimum_manual_verification": {
                "estimated_minutes": 3,
                "steps": [{"title": "主流程", "action": "运行", "expected": "功能正常", "log_filter": "FLOW", "expected_log": "ok", "failure_signal": "error"}],
            },
            "manual_cases": [{"title": "主流程", "required": True, "priority": "P0", "steps": ["运行"], "expected": "功能正常"}],
            "acceptance_logs": [],
            "risks": [],
            "docs_backfill": [],
        }

    def create_linked_worktree(self) -> Path:
        path = self.root / "worktrees" / "existing-task"
        path.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "worktree", "add", "-b", "worktree/existing-task", str(path)], self.repo)
        return path

    def seed_committed_knowledge_task(self, task_id: str = "00000000-0000-0000-0000-000000000071") -> str:
        task_id = self.seed_execution_task(task_id)
        plan_path = self.repo / "plan.md"
        plan_path.write_text("# Stable delivery plan\n", encoding="utf-8")
        with server.mutate_task(task_id) as task:
            task["stage"] = "bugfix"
            task["maxStageIndex"] = server.STAGE_INDEX["bugfix"]
            task["plan"].update({"finalPath": str(plan_path), "draftPath": str(plan_path)})
            task["execution"].update({"status": "complete", "result": self.quick_result(), "review": {"verdict": "pass", "summary": "review passed", "findings": []}})
            task["verification"] = {"approved": True, "checks": [True], "note": "manual passed"}
            task["git"].update({"committed": True, "commitId": task["git"]["head"], "message": "feat: deliver"})
            task["bugfix"] = {"status": "idle", "description": "", "history": []}
            task["knowledge"] = server.default_knowledge()
        return task_id

    def imported_paths(self):
        docs = self.root / "ProjectDocs"
        docs.mkdir(exist_ok=True)
        return (
            mock.patch.object(server, "WORKSPACE_ROOT", self.root),
            mock.patch.object(server, "REPO_ROOT", self.repo),
            mock.patch.object(server, "DOCS_ROOT", docs),
            mock.patch.object(server, "HTML_TASK_ROOT", docs / "Tasks" / "进行中"),
        )

    def feedback_image_payload(self, mime_type: str = "image/png", content: bytes | None = None) -> dict[str, str]:
        samples = {
            "image/png": b"\x89PNG\r\n\x1a\nminimal",
            "image/jpeg": b"\xff\xd8\xffminimal",
            "image/webp": b"RIFF\x04\x00\x00\x00WEBPminimal",
        }
        raw = content if content is not None else samples[mime_type]
        return {
            "name": "feedback.png",
            "mimeType": mime_type,
            "base64": base64.b64encode(raw).decode("ascii"),
        }

    def test_feedback_image_validation_rejects_invalid_inputs_and_limits(self) -> None:
        valid = self.feedback_image_payload()
        decoded = server.decode_feedback_images([valid])
        self.assertEqual(decoded[0]["mimeType"], "image/png")
        self.assertEqual(decoded[0]["size"], len(b"\x89PNG\r\n\x1a\nminimal"))

        with self.assertRaisesRegex(server.WorkflowError, "仅支持 PNG"):
            server.decode_feedback_images([{**valid, "mimeType": "text/plain"}])
        with self.assertRaisesRegex(server.WorkflowError, "编码无效"):
            server.decode_feedback_images([{**valid, "base64": "not-base64"}])
        with self.assertRaisesRegex(server.WorkflowError, "内容与声明"):
            server.decode_feedback_images([self.feedback_image_payload(content=b"plain text")])
        with self.assertRaisesRegex(server.WorkflowError, "最多添加"):
            server.decode_feedback_images([valid] * (server.MAX_FEEDBACK_IMAGE_COUNT + 1))
        with mock.patch.object(server, "MAX_FEEDBACK_IMAGE_BYTES", 8):
            with self.assertRaisesRegex(server.WorkflowError, "单张图片"):
                server.decode_feedback_images([valid])
        with mock.patch.object(server, "MAX_FEEDBACK_IMAGE_BYTES", 64), \
                mock.patch.object(server, "MAX_FEEDBACK_IMAGE_TOTAL_BYTES", 20):
            with self.assertRaisesRegex(server.WorkflowError, "总大小"):
                server.decode_feedback_images([valid, valid])

    def test_feedback_images_stay_inside_task_runtime_and_reject_path_escape(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000041"
        attachments = server.persist_feedback_images(
            task_id, server.decode_feedback_images([self.feedback_image_payload()]), "acceptance-fix"
        )
        saved = Path(attachments[0]["path"])
        self.assertTrue(saved.is_file())
        self.assertTrue(saved.is_relative_to((server.TASK_ROOT / task_id).resolve()))
        self.assertEqual(server.feedback_attachment_paths(task_id, attachments), [saved])

        outside = self.root / "outside.png"
        outside.write_bytes(b"\x89PNG\r\n\x1a\nminimal")
        with self.assertRaisesRegex(server.WorkflowError, "路径越界"):
            server.feedback_attachment_paths(task_id, [{"path": str(outside)}])

    def test_commit_rejects_stale_digest_then_commits_exact_current_state(self) -> None:
        task_id = self.seed_task()
        (self.repo / "feature.txt").write_text("first\n", encoding="utf-8")
        first = server.git_status(self.repo)
        (self.repo / "feature.txt").write_text("changed after preview\n", encoding="utf-8")
        with self.assertRaisesRegex(server.WorkflowError, "Git 状态已变化"):
            server.commit_task(task_id, "feat: temp test", first["digest"])

        current = server.git_status(self.repo)
        commit_id = server.commit_task(task_id, "feat: temp test", current["digest"])
        self.assertEqual(commit_id, subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip())
        self.assertEqual(server.git_status(self.repo)["entries"], [])
        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "bugfix")
        self.assertEqual(task["maxStageIndex"], server.STAGE_INDEX["bugfix"])

    def test_confirm_manual_commit_records_head_without_git_write(self) -> None:
        task_id = self.seed_task()
        (self.repo / "feature.txt").write_text("manual commit\n", encoding="utf-8")
        run(["git", "add", "feature.txt"], self.repo)
        run(["git", "-c", "user.name=Flow Test", "-c", "user.email=flow@example.test", "commit", "-m", "feat: manual work"], self.repo)
        (self.repo / "leftover.txt").write_text("keep pending\n", encoding="utf-8")
        status = server.git_status(self.repo)
        head_before = status["head"]

        commit_id = server.confirm_manual_commit(task_id, status["digest"])

        task = server.get_task_copy(task_id)
        self.assertEqual(commit_id, head_before)
        self.assertEqual(server.git_status(self.repo)["head"], head_before)
        self.assertTrue(task["git"]["committed"])
        self.assertEqual(task["git"]["commitSource"], "manual")
        self.assertEqual(task["git"]["message"], "feat: manual work")
        self.assertEqual(len(task["git"]["entries"]), 1)
        self.assertEqual(task["stage"], "bugfix")
        self.assertIn("仍有 1 项未提交改动", task["events"][-1]["message"])

    def test_confirm_manual_commit_rejects_stale_git_state(self) -> None:
        task_id = self.seed_task()
        first = server.git_status(self.repo)
        (self.repo / "changed-after-preview.txt").write_text("changed\n", encoding="utf-8")

        with self.assertRaisesRegex(server.WorkflowError, "Git 状态已变化"):
            server.confirm_manual_commit(task_id, first["digest"])

        task = server.get_task_copy(task_id)
        self.assertFalse(task["git"]["committed"])
        self.assertEqual(task["git"]["commitId"], "")

    def test_prepare_bugfix_reuses_committed_worktree_without_git_write(self) -> None:
        task_id = self.seed_task()
        (self.repo / "leftover.txt").write_text("pre-existing\n", encoding="utf-8")
        status = server.git_status(self.repo)
        head_before = status["head"]
        server.TASKS[task_id]["git"] = {
            **status,
            "committed": True,
            "commitId": head_before,
            "message": "feat: delivered",
            "commitSource": "manual",
            "confirmedAt": "2026-07-29T15:00:00+08:00",
        }

        feedback = server.prepare_bugfix_request(task_id, "设置页返回后计时没有恢复", status["digest"])

        task = server.get_task_copy(task_id)
        self.assertEqual(server.git_status(self.repo)["head"], head_before)
        self.assertEqual(task["stage"], "bugfix")
        self.assertEqual(task["maxStageIndex"], server.STAGE_INDEX["bugfix"])
        self.assertEqual(task["execution"]["mode"], "bugfix")
        self.assertFalse(task["git"]["committed"])
        self.assertEqual(len(task["git"]["entries"]), 1)
        self.assertEqual(task["bugfix"]["status"], "running")
        self.assertEqual(task["bugfix"]["fromCommit"]["commitId"], head_before)
        self.assertIn("Commit 后的 Bug 修复轮次", feedback)
        self.assertIn("已有 1 项未提交改动", feedback)

    def test_prepare_bugfix_accepts_image_without_text_and_records_attachment(self) -> None:
        task_id = self.seed_task()
        status = server.git_status(self.repo)
        server.TASKS[task_id]["git"] = {
            **status,
            "committed": True,
            "commitId": status["head"],
            "message": "feat: delivered",
        }

        feedback = server.prepare_bugfix_request(
            task_id, "", status["digest"], [self.feedback_image_payload()]
        )

        task = server.get_task_copy(task_id)
        attachments = task["bugfix"]["attachments"]
        self.assertEqual(task["bugfix"]["description"], "")
        self.assertEqual(len(attachments), 1)
        self.assertTrue(Path(attachments[0]["path"]).is_file())
        self.assertIn("未填写文字说明", feedback)
        self.assertIn("图片附件", feedback)

    def test_bugfix_execution_stays_in_bugfix_module_and_does_not_reexecute_plan(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000043"
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "设置页计时 Bug",
            "updatedAt": "",
            "stage": "bugfix",
            "maxStageIndex": server.STAGE_INDEX["bugfix"],
            "activeJob": "execution",
            "jobState": "running",
            "sessions": {"discussion": None, "execution": "saved-execution-thread", "review": None, "ask": None},
            "discussion": {},
            "plan": {"finalPath": "/tmp/plan.md", "markdown": "# Plan"},
            "paths": {},
            "worktree": {"status": "ready", "path": str(self.repo), "branch": "main"},
            "execution": {
                "status": "idle", "phase": "idle", "mode": "bugfix", "threadId": "saved-execution-thread",
                "result": {"summary": "原需求已完成", "changed_files": [], "verification": [], "manual_cases": []},
                "review": {"verdict": "pass", "summary": "原需求通过", "findings": []}, "logs": [], "error": "",
            },
            "verification": {"approved": False},
            "git": {"committed": False, "entries": [], "digest": "old"},
            "bugfix": {"status": "running", "description": "设置页返回后计时没有恢复", "attachments": [], "history": []},
            "events": [],
        }
        fix_result = {
            "summary": "已修复计时恢复", "changed_files": ["reported.cs"], "verification": [],
            "manual_cases": [], "acceptance_logs": [], "risks": [], "docs_backfill": [],
        }
        clean_status = {"entries": [], "digest": "clean", "branch": "main", "head": "abc", "diffStat": "", "refreshedAt": "now"}

        with mock.patch.object(server, "worktree_change_snapshot", side_effect=[{"timer.cs": "before"}, {"timer.cs": "after"}]), \
                mock.patch.object(server, "run_implementation", return_value=(fix_result, None)) as run_implementation, \
                mock.patch.object(server, "run_review", return_value={"verdict": "pass", "summary": "通过", "findings": []}), \
                mock.patch.object(server, "git_status", return_value=clean_status):
            server.execution_job(task_id, "")

        prompt = run_implementation.call_args.args[1]
        self.assertIn("不得重新执行整份 Plan", prompt)
        self.assertNotIn("用户已在控制台明确点击“执行 Plan”", prompt)
        self.assertEqual(run_implementation.call_args.args[2], "saved-execution-thread")
        self.assertEqual(run_implementation.call_args.kwargs["output_schema"], server.SCHEMA_ROOT / "acceptance-fix.schema.json")
        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "bugfix")
        self.assertEqual(task["bugfix"]["status"], "verify")
        self.assertEqual(task["execution"]["mode"], "bugfix")
        self.assertEqual(task["execution"]["roundChangedFiles"], ["timer.cs"])

    def test_ask_is_read_only_persists_answer_and_keeps_stage(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000044"
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "询问当前实现",
            "updatedAt": "",
            "stage": "verify",
            "maxStageIndex": server.STAGE_INDEX["verify"],
            "activeJob": None,
            "jobState": "idle",
            "sessions": {"discussion": None, "execution": None, "review": None, "ask": None},
            "discussion": {},
            "plan": {"finalPath": "/tmp/plan.md", "markdown": "# Plan"},
            "paths": {},
            "worktree": {"status": "ready", "path": str(self.repo), "branch": "main"},
            "execution": {"status": "complete", "result": {}, "review": {}, "logs": []},
            "verification": {"approved": False},
            "git": {"committed": False},
            "bugfix": {"status": "idle"},
            "ask": {"status": "idle", "threadId": None, "messages": [], "logs": [], "error": ""},
            "events": [],
        }
        message_id = server.prepare_ask_request(task_id, "当前状态是怎么保存的？")
        answer = {
            "answer": "状态保存在任务 JSON 中。",
            "evidence": [{"path": "server.py", "detail": "save_task_locked 持久化任务。"}],
            "uncertainties": [],
        }

        with mock.patch.object(server, "run_codex_structured", return_value=(answer, "ask-thread")) as run_codex:
            server.ask_job(task_id, message_id)

        command = run_codex.call_args.args[2]
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "verify")
        self.assertEqual(task["ask"]["status"], "ready")
        self.assertEqual(task["ask"]["messages"][0]["answer"], "状态保存在任务 JSON 中。")
        self.assertEqual(task["sessions"]["ask"], "ask-thread")

    def test_prepare_bugfix_rejects_stale_git_state_without_losing_commit(self) -> None:
        task_id = self.seed_task()
        first = server.git_status(self.repo)
        server.TASKS[task_id]["git"] = {
            **first,
            "committed": True,
            "commitId": first["head"],
            "message": "feat: delivered",
        }
        (self.repo / "changed-after-preview.txt").write_text("changed\n", encoding="utf-8")

        with self.assertRaisesRegex(server.WorkflowError, "Git 状态已变化"):
            server.prepare_bugfix_request(task_id, "新的 Bug", first["digest"])

        task = server.get_task_copy(task_id)
        self.assertTrue(task["git"]["committed"])
        self.assertEqual(task["git"]["commitId"], first["head"])
        self.assertNotEqual(task["git"]["digest"], first["digest"])

    def test_commit_closes_active_bugfix_cycle(self) -> None:
        task_id = self.seed_task()
        server.TASKS[task_id]["bugfix"] = {
            "status": "commit",
            "description": "修复重试问题",
            "fromCommit": {"commitId": "old"},
            "startedAt": "2026-07-29T15:00:00+08:00",
            "history": [],
        }
        (self.repo / "bugfix.txt").write_text("fixed\n", encoding="utf-8")
        status = server.git_status(self.repo)

        commit_id = server.commit_task(task_id, "fix: retry", status["digest"])

        task = server.get_task_copy(task_id)
        self.assertEqual(task["bugfix"]["status"], "complete")
        self.assertEqual(task["bugfix"]["resultCommit"], commit_id)
        self.assertTrue(task["bugfix"]["completedAt"])
        self.assertEqual(task["stage"], "bugfix")

    def test_bind_plan_only_writes_expected_worktree_path(self) -> None:
        draft = self.root / "draft.md"
        draft.write_text("# Plan\n", encoding="utf-8")
        task = {
            "plan": {"draftPath": str(draft)},
            "paths": {"planRelative": "Doc/plans/active/2026-07-27-test.md"},
            "worktree": {"branch": "worktree/test"},
        }
        destination = server.bind_plan_to_worktree(task, self.repo)
        self.assertEqual(destination, self.repo / "Doc/plans/active/2026-07-27-test.md")
        self.assertIn("控制台执行绑定", destination.read_text(encoding="utf-8"))

    def test_safe_names_cannot_escape_controlled_roots(self) -> None:
        self.assertEqual(server.safe_name("../../ bad/name", "fallback"), "bad-name")
        self.assertNotIn("/", server.safe_display_name("需求/../../危险", "fallback"))

    def test_project_branches_lists_local_and_remote_refs_without_fetching(self) -> None:
        run(["git", "branch", "develop"], self.repo)
        run(["git", "branch", "feature/dropdown"], self.repo)
        run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"], self.repo)
        run(["git", "update-ref", "refs/remotes/origin/release", "HEAD"], self.repo)
        run(["git", "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"], self.repo)

        with mock.patch.object(server, "REPO_ROOT", self.repo), mock.patch.object(server, "DEFAULT_BASE_BRANCH", "develop"):
            payload = server.project_branches_payload()

        by_name = {item["name"]: item for item in payload["branches"]}
        self.assertEqual(payload["repo"], str(self.repo))
        self.assertFalse(payload["fetched"])
        self.assertEqual(by_name["main"]["kind"], "local")
        self.assertTrue(by_name["main"]["current"])
        self.assertTrue(by_name["develop"]["default"])
        self.assertEqual(by_name["feature/dropdown"]["kind"], "local")
        self.assertEqual(by_name["origin/release"]["kind"], "remote")
        self.assertNotIn("origin/HEAD", by_name)
        self.assertNotIn("origin", by_name)

    def test_worktree_base_branch_uses_read_only_dropdown_data(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        self.assertIn('api("/api/branches")', app_js)
        self.assertIn('<select id="baseBranch"', app_js)
        self.assertIn('optgroup label="本地分支"', app_js)
        self.assertIn('optgroup label="远端跟踪分支（未 Fetch）"', app_js)
        self.assertNotIn('<input id="baseBranch"', app_js)

    def test_poll_refreshes_when_runtime_state_changes_within_same_second(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        self.assertIn("selectedSummary.stage !== task.stage", app_js)
        self.assertIn("selectedSummary.maxStageIndex !== task.maxStageIndex", app_js)
        self.assertIn("selectedSummary.activeJob !== task.activeJob", app_js)
        self.assertIn('selectedSummary.jobState !== (task.jobState || "idle")', app_js)
        self.assertIn('selectedId === task?.id ? task?.execution?.phase || "" : ""', app_js)
        self.assertIn('selectedExecutionPhase !== (task.execution?.phase || "")', app_js)
        self.assertIn('const wasViewingCurrentStage = ui.module === "flow" && ui.viewStage === previousStage', app_js)
        self.assertIn("if (wasViewingCurrentStage && task.stage !== previousStage) ui.viewStage = task.stage", app_js)
        self.assertIn('task.activeJob === "plan"', app_js)
        self.assertIn('renderProgress(task.plan, "正在生成 Plan 与逻辑验收 HTML")', app_js)
        self.assertIn('generatePlan && result.task?.activeJob === "plan"', app_js)

    def test_running_state_has_motion_cues_and_reduced_motion_fallback(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        index_html = (SERVER_PATH.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn("function estimateProgress(section)", app_js)
        self.assertIn("const estimate = estimateProgress(section)", app_js)
        self.assertIn('class="activity-state ${queued ? "queued" : ""}"', app_js)
        self.assertIn('class="progress-track ${queued ? "queued" : ""}"', app_js)
        self.assertIn('role="progressbar"', app_js)
        self.assertIn("按实时日志里程碑估算", app_js)
        self.assertIn('statusTextEl?.classList.toggle("is-running"', app_js)
        self.assertIn('.task-card[data-state="running"]', index_html)
        self.assertIn('.progress-estimate', index_html)
        self.assertIn('width: var(--progress-value, 0%)', index_html)
        self.assertIn('@keyframes progress-travel', index_html)
        self.assertIn('@keyframes activity-spin', index_html)
        self.assertIn('@media (prefers-reduced-motion: reduce)', index_html)

    def test_quick_execution_ui_explains_progress_timeout_and_checkpoint_resume(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        readme = (SERVER_PATH.parent / "README.md").read_text(encoding="utf-8")
        self.assertIn("quickExecutionHardSeconds", app_js)
        self.assertIn("持续有进度会自动续期", app_js)
        self.assertIn("继续现有修改并完成自检", app_js)
        self.assertIn('section.status === "partial"', app_js)
        self.assertIn("PROJECT_FLOW_QUICK_HARD_TIMEOUT=1800", readme)

    def test_manual_verification_has_sticky_case_navigation(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        index_html = (SERVER_PATH.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn('function renderManualCaseNavigation(cases, requiredIndexes)', app_js)
        self.assertIn('id="manual-case-${index}"', app_js)
        self.assertIn('data-manual-case-jump="${index}"', app_js)
        self.assertIn('class="verification-case-layout"', app_js)
        self.assertIn('classList.toggle("verification-layout-active"', app_js)
        self.assertIn('target.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" })', app_js)
        self.assertIn('navItem.classList.toggle("is-complete", input.checked)', app_js)
        self.assertIn('.manual-case-nav {', index_html)
        self.assertIn('position: sticky;', index_html)
        self.assertIn('.verification-layout-active .workspace { overflow: visible; }', index_html)
        self.assertIn('.manual-case-nav-item.is-complete', index_html)
        self.assertIn('@media (max-width: 1320px)', index_html)
        self.assertIn('@media (max-width: 1120px)', index_html)

    def test_manual_verification_rework_persists_and_rehydrates_checks(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        execute_plan = app_js.split("async function executePlan", 1)[1].split("async function cancelExecution", 1)[0]
        self.assertIn('"verificationRevision"', app_js)
        self.assertIn("serverRevision !== Number(ui.verificationRevision || 0)", app_js)
        self.assertIn("ui.checks = task.verification.checks.map(Boolean)", app_js)
        self.assertIn("mode: ui.executionMode, checks: ui.checks", execute_plan)
        self.assertNotIn("ui.checks = []", execute_plan)

    def test_stage_pages_have_hover_section_navigation_with_snapshots(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        index_html = (SERVER_PATH.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn("function setupSectionNavigator(stageId)", app_js)
        self.assertIn("function destroySectionNavigator()", app_js)
        self.assertIn("function sectionSnapshot(section, title)", app_js)
        self.assertIn('data-section-jump="${index}"', app_js)
        self.assertIn('aria-controls="sectionNavigatorPanel"', app_js)
        self.assertIn('aria-current", "location"', app_js)
        self.assertIn('sections[index].element.scrollIntoView({ behavior: reducedMotion ? "auto" : "smooth", block: "start" })', app_js)
        self.assertIn('window.addEventListener("scroll", onScroll, { passive: true })', app_js)
        self.assertIn('navigator.addEventListener("pointerenter", () => setOpen(true))', app_js)
        self.assertIn('navigator.addEventListener("pointerleave", () => setOpen(false))', app_js)
        self.assertIn('class="section-navigator-snapshot"', app_js)
        self.assertIn('const gapLeft = workflowRect?.right ?? workspaceRect.left - 18', app_js)
        self.assertIn('navigator.style.setProperty("--section-nav-width", `${gapWidth}px`)', app_js)
        self.assertIn('navigator.classList.toggle("is-outside-stage", !stageVisible)', app_js)
        self.assertIn('data-section-title="验收备注与问题"', app_js)
        self.assertIn(".section-navigator {", index_html)
        self.assertIn("position: fixed;", index_html)
        self.assertIn(".section-navigator:is(:hover, .is-open) .section-navigator-panel", index_html)
        self.assertIn(".section-navigator-snapshot", index_html)
        self.assertIn(".section-navigator.is-outside-stage", index_html)
        self.assertIn(".app-shell, .app-shell.verification-layout-active { grid-template-columns: 1fr;", index_html)

    def test_discussion_note_can_be_sent_after_ask_first_questions_are_complete(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        self.assertIn('const discussionActionLabel = questions.length ? "提交回答，继续讨论" : "发送补充，继续讨论"', app_js)
        self.assertIn('<button id="sendDiscussionNote" type="button">${discussionActionLabel}</button>', app_js)
        self.assertIn('if (!generatePlan && !questions.length && !ui.discussionNote.trim())', app_js)
        self.assertIn('showToast("请先填写要继续讨论的补充说明。", true)', app_js)
        self.assertIn('setTask(result.task, generatePlan)', app_js)
        self.assertNotIn("${questions.length ? '<button id=\"sendDiscussionNote\"", app_js)

    def test_worktree_snapshot_detects_changes_to_already_dirty_files(self) -> None:
        readme = self.repo / "README.md"
        readme.write_text("dirty before repair\n", encoding="utf-8")
        before = server.worktree_change_snapshot(self.repo)

        readme.write_text("changed during repair\n", encoding="utf-8")
        (self.repo / "new-fix.cs").write_text("fix\n", encoding="utf-8")
        after = server.worktree_change_snapshot(self.repo)

        self.assertEqual(server.changed_paths_between(before, after), ["README.md", "new-fix.cs"])

    def test_semantic_worktree_slug_replaces_temporary_name_before_creation(self) -> None:
        worktrees_root = self.root / "worktrees"
        html_root = self.root / "html"
        with mock.patch.object(server, "WORKTREES_ROOT", worktrees_root), \
                mock.patch.object(server, "REPO_ROOT", self.repo), \
                mock.patch.object(server, "HTML_TASK_ROOT", html_root), \
                mock.patch.object(server, "launch_job"):
            task = server.create_task({
                "title": "线性关卡 V2",
                "sourceType": "paste",
                "sourceText": "实现线性关卡的第二版流程。",
                "baseBranch": "develop",
            })

            self.assertEqual(task["worktree"]["name"], f"{server.WORKTREE_NAME_PREFIX}_pending_{task['id'][:8]}")
            changed = server.apply_semantic_worktree_slug(task["id"], "linear-level-v2")
            documents_changed = server.apply_semantic_document_paths(task["id"], "linear-level-v2")

        updated = server.get_task_copy(task["id"])
        expected_name = f"{server.WORKTREE_NAME_PREFIX}_linear-level-v2_{task['id'][:8]}"
        created_date = task["createdAt"][:10]
        self.assertTrue(changed)
        self.assertTrue(documents_changed)
        self.assertEqual(updated["worktree"]["slug"], "linear-level-v2")
        self.assertEqual(updated["worktree"]["name"], expected_name)
        self.assertEqual(updated["worktree"]["branch"], f"worktree/{expected_name}")
        self.assertEqual(Path(updated["worktree"]["path"]), worktrees_root / expected_name)
        self.assertEqual(updated["paths"]["planRelative"], f"{server.PLAN_RELATIVE_DIR}/{created_date}-linear-level-v2.md")
        self.assertEqual(Path(updated["paths"]["htmlAbsolute"]), html_root / f"{created_date}-线性关卡-V2-逻辑流程图.html")
        self.assertNotIn(task["id"][:8], updated["paths"]["planRelative"])
        self.assertNotIn(task["id"][:8], updated["paths"]["htmlAbsolute"])

    def test_semantic_document_paths_use_readable_sequence_for_name_collisions(self) -> None:
        html_root = self.root / "html"
        with mock.patch.object(server, "REPO_ROOT", self.repo), \
                mock.patch.object(server, "HTML_TASK_ROOT", html_root), \
                mock.patch.object(server, "launch_job"):
            first = server.create_task({
                "title": "复活提示动画",
                "sourceType": "paste",
                "sourceText": "增加复活提示动画。",
            })
            second = server.create_task({
                "title": "复活提示动画",
                "sourceType": "paste",
                "sourceText": "增加复活提示动画。",
            })
            server.apply_semantic_document_paths(first["id"], "revive-hint-animation")
            server.apply_semantic_document_paths(second["id"], "revive-hint-animation")

        date = first["createdAt"][:10]
        second_paths = server.get_task_copy(second["id"])["paths"]
        self.assertEqual(second_paths["planRelative"], f"{server.PLAN_RELATIVE_DIR}/{date}-revive-hint-animation-2.md")
        self.assertEqual(Path(second_paths["htmlAbsolute"]), html_root / f"{date}-复活提示动画-2-逻辑流程图.html")
        self.assertNotIn("task-", second_paths["planRelative"])

    def test_quick_change_skips_discussion_and_full_plan_agent(self) -> None:
        worktrees_root = self.root / "worktrees"
        with mock.patch.object(server, "REPO_ROOT", self.repo), \
                mock.patch.object(server, "WORKTREES_ROOT", worktrees_root), \
                mock.patch.object(server, "launch_job") as launch_job, \
                mock.patch.object(server, "worktree_preview", return_value="dry-run ok") as preview:
            task = server.create_task({
                "title": "弹幕时间调整",
                "workflowMode": "quick",
                "sourceType": "paste",
                "sourceText": "把弹幕中间停留时间从 2 秒改为 1 秒，不调整移动路径。",
                "baseBranch": "main",
            })

        launch_job.assert_not_called()
        preview.assert_called_once()
        self.assertEqual(task["intake"]["mode"], "quick_change")
        self.assertEqual(task["stage"], "worktree")
        self.assertEqual(task["maxStageIndex"], server.STAGE_INDEX["worktree"])
        self.assertEqual(task["discussion"]["status"], "skipped")
        self.assertEqual(task["plan"]["status"], "ready")
        self.assertTrue(task["plan"]["approved"])
        self.assertEqual(task["worktree"]["status"], "validated")
        self.assertEqual(task["worktree"]["preview"], "dry-run ok")
        self.assertEqual(task["paths"]["htmlUrl"], "")
        self.assertIn("弹幕中间停留时间", task["plan"]["markdown"])
        self.assertTrue(Path(task["plan"]["draftPath"]).is_file())
        self.assertIn("轻量执行单（跳过独立 Plan Agent）", task["agentMemory"]["completedSteps"])
        self.assertIn("轻量执行单已由用户输入确认", task["agentMemory"]["completedSteps"])

    def test_quick_change_rejects_indirect_or_oversized_sources(self) -> None:
        with self.assertRaisesRegex(server.WorkflowError, "只支持明确的粘贴需求"):
            server.create_task({
                "title": "链接需求",
                "workflowMode": "quick",
                "sourceType": "link",
                "sourceUrl": "https://example.com/requirement",
            })

        with self.assertRaisesRegex(server.WorkflowError, "不能超过 12000"):
            server.create_task({
                "title": "过长需求",
                "workflowMode": "quick",
                "sourceType": "paste",
                "sourceText": "x" * (server.MAX_QUICK_SOURCE_TEXT + 1),
            })

    def test_quick_change_binds_local_execution_sheet_to_new_worktree(self) -> None:
        worktrees_root = self.root / "quick-worktrees"
        with mock.patch.object(server, "REPO_ROOT", self.repo), \
                mock.patch.object(server, "WORKTREES_ROOT", worktrees_root), \
                mock.patch.object(server, "launch_job"):
            task = server.create_task({
                "title": "Local Timer Tweak",
                "workflowMode": "quick",
                "sourceType": "paste",
                "sourceText": "Change the local timer from two seconds to one second.",
                "baseBranch": "main",
            })
            server._worktree_job(task["id"])

        updated = server.get_task_copy(task["id"])
        plan_path = Path(updated["plan"]["finalPath"])
        self.assertEqual(updated["stage"], "execute")
        self.assertEqual(updated["worktree"]["status"], "ready")
        self.assertTrue(plan_path.is_file())
        self.assertTrue(plan_path.is_relative_to(Path(updated["worktree"]["path"])))
        self.assertIn("Change the local timer", plan_path.read_text(encoding="utf-8"))

    def test_standard_requirement_is_default_and_quick_change_remains_available(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        self.assertIn('workflowMode: "standard"', app_js)
        self.assertLess(app_js.index('data-workflow-mode="standard"'), app_js.index('data-workflow-mode="quick"'))
        self.assertIn('data-workflow-mode="quick"', app_js)
        self.assertIn('data-workflow-mode="standard"', app_js)
        self.assertIn("跳过 discussion、完整 Plan Agent 和 HTML", app_js)
        self.assertIn("workflowMode: ui.workflowMode", app_js)

    def test_semantic_worktree_slug_rejects_generic_names(self) -> None:
        for slug in ("v2", "feature-v2", "task-feature-v2"):
            with self.subTest(slug=slug), self.assertRaisesRegex(server.WorkflowError, "Worktree 英文名"):
                server.validate_worktree_slug(slug)

    def test_semantic_worktree_slug_does_not_change_existing_or_imported_worktree(self) -> None:
        task_id = "11111111-1111-1111-1111-111111111111"
        original = {
            "status": "ready",
            "name": "Project_v2_11111111",
            "branch": "worktree/Project_v2_11111111",
            "path": str(self.root / "worktrees" / "Project_v2_11111111"),
        }
        server.TASKS[task_id] = {"id": task_id, "updatedAt": "", "events": [], "worktree": dict(original)}

        self.assertFalse(server.apply_semantic_worktree_slug(task_id, "linear-level-v2"))
        self.assertEqual(server.get_task_copy(task_id)["worktree"], original)

        server.TASKS[task_id]["worktree"].update({"status": "validated", "imported": True})
        imported = dict(server.TASKS[task_id]["worktree"])
        self.assertFalse(server.apply_semantic_worktree_slug(task_id, "another-readable-task"))
        self.assertEqual(server.get_task_copy(task_id)["worktree"], imported)

    def test_manual_verification_gate_requires_only_required_cases(self) -> None:
        task = {
            "execution": {
                "result": {
                    "manual_cases": [
                        {"title": "编译", "required": True},
                        {"title": "双端真机", "required": False},
                        {"title": "主流程", "required": True},
                    ]
                }
            }
        }

        self.assertEqual(server.required_manual_case_indexes(task), [0, 2])
        self.assertTrue(server.manual_verification_checks_pass(task, [True, False, True]))
        self.assertFalse(server.manual_verification_checks_pass(task, [True, True, False]))
        self.assertFalse(server.manual_verification_checks_pass(task, [True, True]))

        legacy_task = {"execution": {"result": {"manual_cases": [{"title": "旧用例"}]}}}
        self.assertEqual(server.required_manual_case_indexes(legacy_task), [0])
        self.assertTrue(server.manual_verification_checks_pass(legacy_task, [True]))

    def test_execution_prompt_requires_minimum_steps_detailed_cases_and_logs(self) -> None:
        task = {
            "id": "prompt-contract",
            "title": "验收输出契约",
            "updatedAt": "2026-07-28T20:00:00+08:00",
            "plan": {"finalPath": "/tmp/plan.md", "markdown": "# Plan"},
            "execution": {"review": None},
            "discussion": {},
            "paths": {},
            "worktree": {},
            "git": {},
        }

        prompt = server.execution_prompt(task, "")

        contract = server.TASK_RUNTIME_CONTRACT.read_text(encoding="utf-8")
        self.assertIn("<task-memory-ref>", prompt)
        self.assertIn("<static-contract-ref>", prompt)
        self.assertNotIn('"confirmedFacts"', prompt)
        self.assertIn("3–5 minute", contract)
        self.assertIn("P0/P1/P2", contract)
        self.assertIn("acceptance_logs", contract)
        self.assertIn("low-frequency", contract)
        self.assertIn("never `passed`", contract)

    def test_prompt_references_large_memory_by_path_and_hash(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000062"
        task = {
            "id": task_id,
            "title": "大任务记忆",
            "updatedAt": "2026-08-10T12:00:00+08:00",
            "plan": {"finalPath": "/tmp/plan.md", "markdown": "# Plan"},
            "execution": {"review": None},
            "discussion": {},
            "paths": {},
            "worktree": {},
            "git": {},
            "agentMemory": {
                "version": 1,
                "confirmedFacts": [f"fact-{index}-" + ("x" * 900) for index in range(16)],
                "decisions": [f"decision-{index}-" + ("y" * 900) for index in range(16)],
                "sessions": {"execution": "secret-thread"},
            },
        }
        reference = server.persist_agent_memory(task)
        prompt = server.execution_prompt(task, "只处理新增要求")

        memory_size = server.task_memory_file(task_id).stat().st_size
        self.assertGreater(memory_size, 20_000)
        self.assertLess(len(prompt), 3_000)
        self.assertIn(reference["path"], prompt)
        self.assertIn(reference["sha256"], prompt)
        self.assertNotIn("fact-0-", prompt)
        self.assertNotIn("secret-thread", server.task_memory_file(task_id).read_text(encoding="utf-8"))

    def test_acceptance_fix_prompt_is_targeted_and_reports_only_round_files(self) -> None:
        task = {
            "plan": {"finalPath": "/tmp/plan.md"},
            "execution": {
                "result": {"summary": "上一轮完整实施已通过"},
                "review": {"verdict": "pass", "summary": "通过", "findings": []},
            },
        }

        prompt = server.acceptance_fix_prompt(task, "点击复活后计时没有继续")

        self.assertIn("人工验收后的定向返修", prompt)
        self.assertIn("点击复活后计时没有继续", prompt)
        self.assertIn("禁止重新扫描、重新实施或重新验证整份 Plan", prompt)
        self.assertIn("本轮实际写入的文件", prompt)
        self.assertNotIn("使用 $workmission", prompt)

    def test_acceptance_fix_result_keeps_unaffected_cases_and_prior_files(self) -> None:
        previous = {
            "summary": "上一轮",
            "changed_files": ["old.cs", "shared.cs"],
            "verification": [{"check": "旧检查", "result": "ok", "status": "passed"}],
            "manual_cases": [
                {"title": "复活计时", "expected": "旧结果"},
                {"title": "主流程", "expected": "保持"},
            ],
            "acceptance_logs": [{"name": "计时日志", "expected": "旧日志"}],
            "risks": ["旧风险"],
            "docs_backfill": ["old.md"],
        }
        update = {
            "summary": "已定向修复",
            "changed_files": ["shared.cs", "fix.cs"],
            "verification": [{"check": "新检查", "result": "ok", "status": "passed"}],
            "minimum_manual_verification": {"estimated_minutes": 3, "steps": []},
            "manual_cases": [{"title": "复活计时", "expected": "新结果"}],
            "acceptance_logs": [{"name": "计时日志", "expected": "新日志"}],
            "risks": [],
            "docs_backfill": ["fix.md"],
        }

        result = server.merge_acceptance_fix_result(previous, update)

        self.assertEqual(result["summary"], "已定向修复")
        self.assertEqual(result["changed_files"], ["shared.cs", "fix.cs", "old.cs"])
        self.assertEqual([case["title"] for case in result["manual_cases"]], ["复活计时", "主流程"])
        self.assertEqual(result["manual_cases"][0]["expected"], "新结果")
        self.assertEqual(result["acceptance_logs"][0]["expected"], "新日志")
        self.assertEqual(result["docs_backfill"], ["fix.md", "old.md"])

    def test_acceptance_fix_rechecks_only_affected_manual_cases(self) -> None:
        previous_cases = [
            {"title": "复活计时", "expected": "旧结果"},
            {"title": "主流程", "expected": "保持"},
            {"title": "补充回归", "expected": "保持"},
        ]
        merged_cases = [
            {"title": "新增长按回归", "expected": "新用例"},
            {"title": "复活计时", "expected": "新结果"},
            {"title": "主流程", "expected": "保持"},
            {"title": "补充回归", "expected": "保持"},
        ]
        affected_cases = merged_cases[:2]

        checks = server.remap_manual_verification_checks(
            previous_cases,
            [True, True, False],
            merged_cases,
            affected_cases,
        )

        self.assertEqual(checks, [False, False, True, False])

    def test_acceptance_fix_check_mapping_uses_case_title_not_array_index(self) -> None:
        previous_cases = [{"title": "主流程"}, {"title": "设置页"}]
        merged_cases = [{"title": "设置页"}, {"title": "主流程"}]

        checks = server.remap_manual_verification_checks(
            previous_cases,
            [True, False],
            merged_cases,
            [],
        )

        self.assertEqual(checks, [False, True])

    def test_prepare_acceptance_fix_persists_current_manual_checks(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000080")
        with server.mutate_task(task_id) as task:
            task["stage"] = "verify"
            task["execution"]["result"] = {
                "manual_cases": [{"title": "主流程"}, {"title": "设置页"}],
            }
            task["verification"] = {"approved": False, "checks": [], "note": "", "revision": 4}

        server.prepare_execution_request(
            task_id,
            False,
            acceptance_fix=True,
            feedback="设置页仍有问题",
            verification_checks=[True, False],
        )

        verification = server.get_task_copy(task_id)["verification"]
        self.assertEqual(verification["checks"], [True, False])
        self.assertEqual(verification["revision"], 5)

    def test_prepare_acceptance_review_retry_keeps_mapped_checks(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000081")
        with server.mutate_task(task_id) as task:
            task["stage"] = "execute"
            task["execution"].update({
                "status": "needs_attention",
                "phase": "review",
                "mode": "acceptance_fix",
                "result": {"manual_cases": [{"title": "返修项"}, {"title": "主流程"}]},
                "review": {"verdict": "needs_fix", "findings": [{"title": "仍需修复"}]},
            })
            task["verification"] = {
                "approved": False,
                "checks": [False, True],
                "note": "",
                "revision": 6,
            }

        server.prepare_execution_request(task_id, False, verification_checks=[False, False])

        verification = server.get_task_copy(task_id)["verification"]
        self.assertEqual(verification["checks"], [False, True])
        self.assertEqual(verification["revision"], 7)

    def test_lark_links_default_to_chrome_mcp_without_accepting_spoofed_hosts(self) -> None:
        self.assertTrue(server.is_lark_url("https://example.feishu.cn/docx/abc"))
        self.assertTrue(server.is_lark_url("https://example.larksuite.com/wiki/abc"))
        self.assertFalse(server.is_lark_url("https://feishu.cn.example.com/docx/abc"))

        with mock.patch.object(server, "REPO_ROOT", self.repo), mock.patch.object(server, "launch_job") as launch_job:
            task = server.create_task({
                "title": "飞书策划文档",
                "sourceType": "link",
                "sourceUrl": "https://example.feishu.cn/docx/abc",
                "baseBranch": "main",
            })
            payload = {"summary": "ready", "worktree_slug": "lark-document-review", "confirmed_facts": [], "assumptions": [], "questions": [], "ready_for_plan": True}
            with mock.patch.object(server, "run_codex_structured", return_value=(payload, "discussion-thread")) as run_codex:
                server.initial_discussion_job(task["id"])

        launch_job.assert_called_once()
        self.assertEqual(task["source"]["reader"], "chrome_mcp")
        prompt = run_codex.call_args.args[2][-1]
        self.assertIn("$chrome:control-chrome", prompt)
        self.assertIn("不要改用 curl、Web Search、其他浏览器", prompt)
        self.assertIn("名称必须能单独看出任务含义", prompt)

    def test_lark_links_can_use_ready_official_cli_in_read_only_mode(self) -> None:
        ready = {
            "installed": True,
            "authenticated": True,
            "ready": True,
            "version": "lark-cli 1.0.82",
            "message": "已安装且授权状态有效。",
        }
        with mock.patch.object(server, "lark_cli_status", return_value=ready), \
                mock.patch.object(server, "launch_job"):
            task = server.create_task({
                "title": "飞书官方接口读取",
                "sourceType": "link",
                "sourceUrl": "https://example.feishu.cn/wiki/abc",
                "larkReader": "lark_cli",
                "baseBranch": "main",
            })

        prompt = server.source_prompt(task)
        self.assertEqual(task["source"]["reader"], "lark_cli")
        self.assertIn("$lark-shared、$lark-wiki 与 $lark-doc", prompt)
        self.assertIn("禁止创建、更新、覆盖、移动、分享、评论、发送消息", prompt)
        self.assertIn("不要改用 Chrome MCP", prompt)

    def test_lark_cli_reader_rejects_unready_or_unknown_selection(self) -> None:
        unavailable = {
            "installed": False,
            "authenticated": False,
            "ready": False,
            "version": "未安装",
            "message": "未找到官方 lark-cli；需要先完成一次安装、应用配置和用户授权。",
        }
        payload = {
            "title": "飞书读取",
            "sourceType": "link",
            "sourceUrl": "https://example.feishu.cn/wiki/abc",
            "baseBranch": "main",
        }
        with mock.patch.object(server, "lark_cli_status", return_value=unavailable), \
                self.assertRaisesRegex(server.WorkflowError, "Lark CLI 暂不可用"):
            server.create_task({**payload, "larkReader": "lark_cli"})
        with self.assertRaisesRegex(server.WorkflowError, "飞书读取方式"):
            server.create_task({**payload, "larkReader": "unknown_reader"})

    def test_lark_cli_status_requires_reader_skills_as_well_as_auth(self) -> None:
        command_result = subprocess.CompletedProcess(["lark-cli"], 0, "lark-cli 1.0.82", "")
        with mock.patch.object(server, "resolve_lark_cli_bin", return_value="/opt/homebrew/bin/lark-cli"), \
                mock.patch.object(server, "LARK_READER_SKILLS", ("definitely-missing-lark-skill",)), \
                mock.patch.object(server, "run_command", return_value=command_result):
            status = server.lark_cli_status()

        self.assertTrue(status["installed"])
        self.assertTrue(status["authenticated"])
        self.assertFalse(status["skillsInstalled"])
        self.assertFalse(status["ready"])
        self.assertIn("definitely-missing-lark-skill", status["missingSkills"])

    def test_lark_reader_selector_is_optional_and_preserves_typing(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        self.assertIn('larkReader: "chrome_mcp"', app_js)
        self.assertIn('data-lark-reader="chrome_mcp"', app_js)
        self.assertIn('data-lark-reader="lark_cli"', app_js)
        self.assertIn('options.hidden = !isLarkLink(event.target.value)', app_js)
        self.assertIn('larkReader: ui.larkReader', app_js)
        self.assertIn("官方 Lark CLI 正在只读获取飞书需求", app_js)

    def test_import_existing_plan_enters_execute_without_codex_job(self) -> None:
        worktree = self.create_linked_worktree()
        plan = worktree / "Doc" / "plans" / "active" / "existing.md"
        plan.parent.mkdir(parents=True)
        plan.write_text("# Existing Plan\n\nExecute this.\n", encoding="utf-8")

        patches = self.imported_paths()
        with patches[0], patches[1], patches[2], patches[3], mock.patch.object(server, "launch_job") as launch_job:
            task = server.create_imported_task({
                "title": "已有 Plan 接入",
                "intakeMode": "existing_plan",
                "documentPath": str(plan),
                "worktreePath": str(worktree),
            })

        launch_job.assert_not_called()
        self.assertEqual(task["stage"], "execute")
        self.assertEqual(task["maxStageIndex"], server.STAGE_INDEX["execute"])
        self.assertEqual(Path(task["plan"]["finalPath"]), plan.resolve())
        self.assertTrue(task["plan"]["approved"])
        self.assertEqual(task["worktree"]["status"], "ready")
        self.assertTrue(task["worktree"]["imported"])
        self.assertEqual(task["intake"]["mode"], "existing_plan")
        self.assertEqual(task["paths"]["planRelative"], str(plan.relative_to(worktree)))
        self.assertFalse(server.apply_semantic_document_paths(task["id"], "existing-plan-intake"))
        self.assertEqual(server.get_task_copy(task["id"])["paths"]["planRelative"], str(plan.relative_to(worktree)))
        self.assertIn("已有执行 Plan 接入", task["agentMemory"]["completedSteps"])

    def test_import_existing_requirement_starts_discussion_and_reuses_worktree(self) -> None:
        worktree = self.create_linked_worktree()
        requirement = self.root / "ProjectDocs" / "requirement.md"
        requirement.parent.mkdir(exist_ok=True)
        requirement.write_text("# Requirement\n", encoding="utf-8")

        patches = self.imported_paths()
        with patches[0], patches[1], patches[2], patches[3], mock.patch.object(server, "launch_job") as launch_job:
            task = server.create_imported_task({
                "title": "已有需求文档接入",
                "intakeMode": "existing_requirement",
                "documentPath": str(requirement),
                "worktreePath": str(worktree),
            })
            discussion_payload = {"summary": "ready", "worktree_slug": "existing-requirement-intake", "confirmed_facts": [], "assumptions": [], "questions": [], "ready_for_plan": True}
            with mock.patch.object(server, "run_codex_structured", return_value=(discussion_payload, "discussion-thread")) as run_codex:
                server.initial_discussion_job(task["id"])

        launch_job.assert_called_once()
        self.assertEqual(task["stage"], "discuss")
        self.assertEqual(task["discussion"]["status"], "queued")
        self.assertEqual(task["source"]["type"], "existing_file")
        self.assertEqual(task["worktree"]["status"], "validated")
        self.assertEqual(task["worktree"]["branch"], "worktree/existing-task")
        self.assertEqual(task["intake"]["mode"], "existing_requirement")
        updated = server.get_task_copy(task["id"])
        expected_plan = f"{server.PLAN_RELATIVE_DIR}/{task['createdAt'][:10]}-existing-requirement-intake.md"
        self.assertEqual(updated["paths"]["planRelative"], expected_plan)
        self.assertEqual(updated["worktree"]["name"], worktree.name)
        self.assertNotIn(task["id"][:8], updated["paths"]["htmlAbsolute"])
        command = run_codex.call_args.args[2]
        self.assertIn("--add-dir", command)
        self.assertIn(str(requirement.resolve().parent), command)

    def test_existing_worktree_validation_rejects_main_repo(self) -> None:
        patches = self.imported_paths()
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaisesRegex(server.WorkflowError, "主仓库"):
                server.validate_existing_worktree(str(self.repo))

    def test_imported_requirement_binds_plan_without_creating_worktree(self) -> None:
        worktree = self.create_linked_worktree()
        requirement = self.root / "ProjectDocs" / "requirement.md"
        requirement.parent.mkdir(exist_ok=True)
        requirement.write_text("# Requirement\n", encoding="utf-8")
        draft = self.root / "plan-draft.md"
        draft.write_text("# Generated Plan\n", encoding="utf-8")

        patches = self.imported_paths()
        with patches[0], patches[1], patches[2], patches[3], mock.patch.object(server, "launch_job"):
            task = server.create_imported_task({
                "title": "绑定已有 Worktree",
                "intakeMode": "existing_requirement",
                "documentPath": str(requirement),
                "worktreePath": str(worktree),
            })
            with server.mutate_task(task["id"]) as live:
                live["plan"].update({"status": "ready", "approved": True, "draftPath": str(draft), "markdown": "# Generated Plan"})
            preview = server.worktree_preview(server.get_task_copy(task["id"]))
            with mock.patch.object(server, "finish_existing_worktree") as finish_existing:
                server._worktree_job(task["id"])
            with self.assertRaisesRegex(server.WorkflowError, "拒绝覆盖"):
                server.bind_plan_to_worktree(server.get_task_copy(task["id"]), worktree)

        finish_existing.assert_not_called()
        bound = worktree / task["paths"]["planRelative"]
        self.assertTrue(bound.is_file())
        self.assertIn("Generated Plan", bound.read_text(encoding="utf-8"))
        self.assertIn("不会创建新目录", preview)
        final_task = server.get_task_copy(task["id"])
        self.assertEqual(final_task["stage"], "execute")
        self.assertEqual(final_task["worktree"]["status"], "ready")

    def test_task_summaries_sort_and_expose_dashboard_state(self) -> None:
        older = {
            "id": "00000000-0000-0000-0000-000000000010", "title": "旧需求", "createdAt": "2026-07-28T08:00:00+08:00",
            "updatedAt": "2026-07-28T09:00:00+08:00", "stage": "discuss", "maxStageIndex": 1,
            "activeJob": None, "jobState": "idle", "discussion": {"status": "ready"}, "plan": {}, "worktree": {}, "execution": {},
            "git": {"committed": False}, "source": {"text": "不应出现在摘要"},
        }
        newer = {
            "id": "00000000-0000-0000-0000-000000000011", "title": "运行需求", "createdAt": "2026-07-28T09:00:00+08:00",
            "updatedAt": "2026-07-28T10:00:00+08:00", "stage": "plan", "maxStageIndex": 2,
            "activeJob": "plan", "jobState": "queued", "discussion": {"status": "ready"}, "plan": {"status": "queued"},
            "worktree": {"name": "Project_running", "status": "idle"}, "execution": {"phase": "review"}, "git": {"committed": False},
        }
        server.TASKS.update({older["id"]: older, newer["id"]: newer})
        summaries = server.list_task_summaries()
        self.assertEqual([item["id"] for item in summaries], [newer["id"], older["id"]])
        self.assertEqual(summaries[0]["state"], "queued")
        self.assertEqual(summaries[0]["executionPhase"], "review")
        self.assertNotIn("source", summaries[0])

    def test_bugfix_running_labels_distinguish_implementation_from_review(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        self.assertIn('executionPhase: value.execution?.phase || ""', app_js)
        self.assertIn('"Bug 修改已完成 · Code Review 中"', app_js)
        self.assertIn('executionPhase === "review" ? "Bug Review 中" : "Bug 修改中"', app_js)
        self.assertIn('const progressTitle = reviewing ? "Bug 修改已完成 · 正在 Code Review"', app_js)
        self.assertIn('${reviewing ? "停止 Code Review" : "停止当前修改"}', app_js)

    def test_completed_flow_stage_ui_is_read_only(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        index_html = (SERVER_PATH.parent / "index.html").read_text(encoding="utf-8")

        self.assertIn("function isCompletedStageView", app_js)
        self.assertIn("function activeFlowStageId", app_js)
        self.assertIn("function lockCompletedStageView", app_js)
        self.assertIn('ui.module === "flow" && isCompletedStage(stageId)', app_js)
        self.assertIn('class="flow-stage-view ${completedStageView ? "completed-stage-view" : ""}"', app_js)
        self.assertIn('if (completedStageView) lockCompletedStageView(stageContentEl)', app_js)
        self.assertIn("已完成阶段，只读回看", app_js)
        self.assertIn(".completed-stage-view .actions { display: none; }", index_html)
        self.assertIn("已完成阶段仅可只读回看", index_html)

    def test_flow_writes_are_rejected_outside_the_current_stage(self) -> None:
        completed_task = {
            "stage": "commit",
            "plan": {"status": "ready", "approved": True},
            "worktree": {"status": "ready"},
            "execution": {"status": "complete"},
            "verification": {"approved": True},
            "git": {"committed": False},
            "bugfix": {"status": "idle"},
        }
        for action in ("discussion", "plan", "plan/approve", "worktree", "execute", "bugfix"):
            with self.subTest(action=action), self.assertRaisesRegex(server.WorkflowError, "仅可回看"):
                server.ensure_flow_action_allowed(completed_task, action)

        server.ensure_flow_action_allowed(completed_task, "commit")

        delivered_task = {
            **completed_task,
            "stage": "bugfix",
            "git": {"committed": True},
            "bugfix": {"status": "complete"},
        }
        server.ensure_flow_action_allowed(delivered_task, "bugfix")
        with self.assertRaisesRegex(server.WorkflowError, "拒绝重复操作"):
            server.ensure_flow_action_allowed(delivered_task, "execute")
        with self.assertRaisesRegex(server.WorkflowError, "拒绝重复操作"):
            server.ensure_flow_action_allowed(delivered_task, "commit")

    def test_flow_stage_guard_preserves_retries_and_acceptance_fixes(self) -> None:
        plan_retry = {
            "stage": "plan", "plan": {"status": "error", "approved": False},
            "git": {"committed": False}, "bugfix": {"status": "idle"},
        }
        server.ensure_flow_action_allowed(plan_retry, "plan")

        verification = {
            "stage": "verify", "plan": {"status": "ready", "approved": True},
            "git": {"committed": False}, "bugfix": {"status": "idle"},
        }
        with self.assertRaisesRegex(server.WorkflowError, "仅可回看"):
            server.ensure_flow_action_allowed(verification, "execute")
        server.ensure_flow_action_allowed(verification, "execute", acceptance_fix=True)

        bugfix_review = {
            "stage": "bugfix", "plan": {"status": "ready", "approved": True},
            "git": {"committed": False}, "bugfix": {"status": "review"},
        }
        server.ensure_flow_action_allowed(bugfix_review, "execute")

    def test_archive_and_restore_task_without_touching_execution_assets(self) -> None:
        task_id = self.seed_task()
        external_plan = self.root / "plan.md"
        external_plan.write_text("# keep\n", encoding="utf-8")
        server.TASKS[task_id]["plan"] = {"finalPath": str(external_plan)}

        archived = server.archive_task(task_id)
        self.assertTrue(archived["archivedAt"])
        summary = next(item for item in server.list_task_summaries() if item["id"] == task_id)
        self.assertEqual(summary["state"], "archived")
        self.assertTrue(summary["archivedAt"])
        self.assertTrue(external_plan.is_file())

        restored = server.restore_task(task_id)
        self.assertEqual(restored["archivedAt"], "")
        self.assertEqual(server.task_state(restored), "attention")
        self.assertTrue(external_plan.is_file())

    def test_delete_moves_only_inactive_task_record_to_runtime_trash(self) -> None:
        task_id = self.seed_task()
        external_worktree = self.root / "external-worktree"
        external_worktree.mkdir()
        server.TASKS[task_id]["worktree"] = {"path": str(external_worktree)}
        server.save_task_locked(server.TASKS[task_id])

        destination = server.delete_task(task_id)

        self.assertIsNotNone(destination)
        self.assertTrue((destination / "task.json").is_file())
        self.assertTrue(external_worktree.is_dir())
        self.assertNotIn(task_id, server.TASKS)
        self.assertFalse(server.task_dir(task_id).exists())

    def test_running_task_cannot_be_archived_or_deleted(self) -> None:
        task_id = self.seed_task()
        server.TASKS[task_id].update({"activeJob": "execution", "jobState": "running"})

        with self.assertRaisesRegex(server.WorkflowError, "正在执行"):
            server.archive_task(task_id)
        with self.assertRaisesRegex(server.WorkflowError, "正在执行"):
            server.delete_task(task_id)

        self.assertIn(task_id, server.TASKS)

    def test_global_job_slot_queues_another_task(self) -> None:
        server.JOB_SLOTS = threading.BoundedSemaphore(1)
        first_id = "00000000-0000-0000-0000-000000000020"
        second_id = "00000000-0000-0000-0000-000000000021"
        for task_id in (first_id, second_id):
            server.TASKS[task_id] = {
                "id": task_id, "title": task_id, "updatedAt": "", "activeJob": None, "jobState": "idle",
                "discussion": {"status": "idle", "logs": []}, "events": [],
            }
        first_started = threading.Event()
        release_first = threading.Event()
        second_started = threading.Event()

        server.launch_job(first_id, "discussion", lambda: (first_started.set(), release_first.wait(2)))
        self.assertTrue(first_started.wait(1))
        first_thread = server.ACTIVE_THREADS[first_id]
        server.launch_job(second_id, "discussion", second_started.set)
        second_thread = server.ACTIVE_THREADS[second_id]
        self.assertFalse(second_started.wait(0.1))
        self.assertEqual(server.get_task_copy(second_id)["jobState"], "queued")

        release_first.set()
        self.assertTrue(second_started.wait(1))
        first_thread.join(1)
        second_thread.join(1)
        self.assertIsNone(server.get_task_copy(second_id)["activeJob"])

    def test_agent_memory_is_derived_and_persisted_with_task(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000030"
        task = {
            "id": task_id,
            "title": "持久记忆测试",
            "updatedAt": "2026-07-28T10:00:00+08:00",
            "stage": "verify",
            "activeJob": None,
            "jobState": "idle",
            "sessions": {"discussion": "discussion-thread", "execution": "execution-thread", "review": "review-thread"},
            "discussion": {
                "status": "ready",
                "result": {"summary": "已确认需求口径", "confirmed_facts": ["已有本地控制服务"], "assumptions": ["默认两个 Worker"]},
                "messages": [{"answers": {"worker_count": "2"}, "note": "每需求保留逻辑 Agent"}],
            },
            "plan": {
                "status": "ready",
                "approved": True,
                "markdown": "# Persistent Agent Plan\n",
                "finalPath": "Doc/plans/active/persistent-agent.md",
                "result": {"summary": "升级多任务控制台", "scope": ["逻辑 Agent 记忆"], "non_scope": ["不创建常驻进程"], "risks": ["会话可能失效"]},
            },
            "paths": {"planRelative": "Doc/plans/active/persistent-agent.md", "htmlRelative": "../ProjectDocs/Tasks/agent.html"},
            "worktree": {"status": "ready", "path": "/tmp/worktree", "branch": "worktree/agent"},
            "execution": {
                "status": "complete",
                "result": {
                    "summary": "实现完成",
                    "changed_files": ["server.py"],
                    "verification": [{"status": "passed", "check": "unit tests", "result": "9 tests"}],
                },
            },
            "verification": {"approved": True},
            "git": {"committed": False, "head": "abc123", "digest": "digest-1"},
            "events": [],
        }
        server.TASKS[task_id] = task

        with server.mutate_task(task_id):
            pass

        stored = server.get_task_copy(task_id)
        memory = stored["agentMemory"]
        disk = server.json.loads(server.task_file(task_id).read_text(encoding="utf-8"))["agentMemory"]
        memory_path = server.task_memory_file(task_id)
        memory_bytes = memory_path.read_bytes()
        self.assertEqual(memory, disk)
        self.assertEqual(memory["summary"], "实现完成")
        self.assertEqual(memory["sessions"], {"discussion": "discussion-thread", "execution": "execution-thread", "review": "review-thread", "ask": None, "app": None})
        self.assertIn("worker_count: 2", memory["decisions"])
        self.assertIn("server.py", memory["relevantFiles"])
        self.assertIn("人工验收", memory["completedSteps"])
        self.assertTrue(memory["fingerprints"]["planSha256"])
        self.assertTrue(memory_path.is_file())
        self.assertEqual(stored["agentMemoryRef"]["path"], str(memory_path.resolve()))
        self.assertEqual(stored["agentMemoryRef"]["sha256"], server.hashlib.sha256(memory_bytes).hexdigest())
        self.assertNotIn("sessions", server.json.loads(memory_bytes))

        prompt = server.execution_prompt(stored, "只处理本轮反馈")
        self.assertIn(str(memory_path.resolve()), prompt)
        self.assertIn(stored["agentMemoryRef"]["sha256"], prompt)
        self.assertNotIn('"confirmedFacts"', prompt)
        self.assertNotIn('"decisions"', prompt)

    def test_execution_and_review_threads_are_kept_in_separate_slots(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000031"
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "会话隔离",
            "updatedAt": "",
            "stage": "execute",
            "activeJob": "execution",
            "jobState": "running",
            "sessions": {"discussion": "discussion-thread", "execution": None, "review": None},
            "discussion": {"status": "ready", "threadId": "discussion-thread"},
            "plan": {},
            "worktree": {},
            "execution": {"status": "running", "threadId": None, "reviewThreadId": None, "logs": []},
            "verification": {"approved": False},
            "git": {},
            "events": [],
        }

        server.record_codex_event(task_id, "execution", {"type": "thread.started", "thread_id": "execution-thread"}, "execution")
        server.record_codex_event(task_id, "execution", {"type": "thread.started", "thread_id": "review-thread"}, "review")

        task = server.get_task_copy(task_id)
        self.assertEqual(task["sessions"]["discussion"], "discussion-thread")
        self.assertEqual(task["sessions"]["execution"], "execution-thread")
        self.assertEqual(task["sessions"]["review"], "review-thread")
        self.assertEqual(task["execution"]["threadId"], "execution-thread")
        self.assertEqual(task["execution"]["reviewThreadId"], "review-thread")

    def test_review_uses_read_only_structured_exec_with_code_review_skill(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000034"
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "Review 参数互斥保护",
            "updatedAt": "",
            "plan": {"finalPath": str(self.repo / "Doc" / "plans" / "active" / "test.md")},
            "worktree": {"path": str(self.repo)},
            "execution": {"result": {"changed_files": ["feature.cs", "Doc/plan.md"]}},
        }
        review = {"verdict": "pass", "summary": "通过", "findings": []}

        with mock.patch.object(server, "run_codex_structured", return_value=(review, "review-thread")) as run_codex:
            self.assertEqual(server.run_review(task_id), review)

        command = run_codex.call_args.args[2]
        self.assertEqual(command[:2], [server.CODEX_BIN, "exec"])
        self.assertNotEqual(command[2], "review")
        self.assertNotIn("--uncommitted", command)
        self.assertIn("read-only", command)
        self.assertIn("--output-schema", command)
        self.assertIn("$code-review", command[-1])
        self.assertIn("feature.cs", command[-1])
        self.assertIn("严格审查白名单", command[-1])
        self.assertIn("禁止运行无路径限定的 git diff", command[-1])
        self.assertEqual(run_codex.call_args.kwargs["timeout_seconds"], server.REVIEW_TIMEOUT_SECONDS)

    def test_codex_resolution_falls_back_to_chatgpt_bundle_without_shell_path(self) -> None:
        bundled = self.root / "ChatGPT.app" / "Contents" / "Resources" / "codex"
        bundled.parent.mkdir(parents=True)
        bundled.write_text("#!/bin/sh\n", encoding="utf-8")
        bundled.chmod(0o755)

        with mock.patch.dict(os.environ, {server.CODEX_BIN_ENV: ""}), \
                mock.patch.object(server.shutil, "which", return_value=None), \
                mock.patch.object(server, "CODEX_FALLBACK_PATHS", (bundled,)):
            self.assertEqual(server.resolve_codex_bin(), str(bundled))

    def test_codex_resolution_prefers_environment_override(self) -> None:
        override = self.root / "custom-codex"
        fallback = self.root / "fallback-codex"
        for candidate in (override, fallback):
            candidate.write_text("#!/bin/sh\n", encoding="utf-8")
            candidate.chmod(0o755)

        with mock.patch.dict(os.environ, {server.CODEX_BIN_ENV: str(override)}), \
                mock.patch.object(server.shutil, "which", return_value=str(fallback)), \
                mock.patch.object(server, "CODEX_FALLBACK_PATHS", (fallback,)):
            self.assertEqual(server.resolve_codex_bin(), str(override))

    def test_codex_resolution_returns_empty_when_no_candidate_exists(self) -> None:
        missing = self.root / "missing-codex"
        with mock.patch.dict(os.environ, {server.CODEX_BIN_ENV: ""}), \
                mock.patch.object(server.shutil, "which", return_value=None), \
                mock.patch.object(server, "CODEX_FALLBACK_PATHS", (missing,)):
            self.assertEqual(server.resolve_codex_bin(), "")

    def test_missing_codex_is_reported_as_workflow_error(self) -> None:
        task_id = self.seed_task()
        output = self.root / "missing-codex-output.json"

        with mock.patch.object(server, "CODEX_BIN", ""), \
                mock.patch.object(server.subprocess, "Popen") as popen:
            with self.assertRaisesRegex(server.WorkflowError, "找不到 Codex CLI"):
                server.run_codex_structured(task_id, "execution", [""], self.repo, output)
        popen.assert_not_called()

    def test_disappearing_codex_does_not_leak_file_not_found(self) -> None:
        task_id = self.seed_task()
        output = self.root / "disappearing-codex-output.json"

        with mock.patch.object(server, "CODEX_BIN", "/missing/codex"), \
                mock.patch.object(server.subprocess, "Popen", side_effect=FileNotFoundError("gone")):
            with self.assertRaisesRegex(server.WorkflowError, "找不到 Codex CLI") as context:
                server.run_codex_structured(task_id, "execution", ["/missing/codex"], self.repo, output)
        self.assertNotIn("No such file or directory", str(context.exception))

    def test_health_does_not_spawn_empty_codex_command(self) -> None:
        with mock.patch.object(server, "CODEX_BIN", ""), \
                mock.patch.object(server, "lark_cli_status", return_value={"ready": False}), \
                mock.patch.object(server, "run_command") as run_command:
            health = server.health_payload()

        run_command.assert_not_called()
        self.assertFalse(health["codex"]["ready"])
        self.assertEqual(health["codex"]["version"], "未找到 Codex CLI")
        self.assertTrue(any("找不到 Codex CLI" in warning for warning in health["warnings"]))

    def test_structured_codex_uses_agent_message_when_output_file_is_empty(self) -> None:
        task_id = self.seed_task()
        payload = {"verdict": "pass", "summary": "通过", "findings": [], "verification_gaps": []}
        output = self.root / "empty-review-output.json"
        output.write_text("", encoding="utf-8")
        process = mock.Mock()
        process.stdout = iter([
            '{"type":"thread.started","thread_id":"review-thread"}\n',
            json.dumps({
                "type": "item.completed",
                "item": {"type": "agent_message", "text": json.dumps(payload, ensure_ascii=False)},
            }, ensure_ascii=False) + "\n",
        ])
        process.stderr = iter(())
        process.wait.return_value = 0

        with mock.patch.object(server.subprocess, "Popen", return_value=process):
            result, thread_id = server.run_codex_structured(
                task_id, "execution", ["codex"], self.repo, output, "review"
            )

        self.assertEqual(result, payload)
        self.assertEqual(thread_id, "review-thread")

    def test_structured_codex_reports_empty_result_clearly(self) -> None:
        task_id = self.seed_task()
        output = self.root / "empty-review-output.json"
        output.write_text(" \n", encoding="utf-8")
        process = mock.Mock()
        process.stdout = iter(())
        process.stderr = iter(())
        process.wait.return_value = 0

        with mock.patch.object(server.subprocess, "Popen", return_value=process):
            with self.assertRaisesRegex(server.WorkflowError, "结构化结果为空"):
                server.run_codex_structured(task_id, "execution", ["codex"], self.repo, output)

    def test_structured_codex_error_keeps_the_actionable_stderr_lines(self) -> None:
        task_id = self.seed_task()
        process = mock.Mock()
        process.stdout = iter(())
        process.stderr = iter([
            "error: the argument '--uncommitted' cannot be used with '[PROMPT]'\n",
            "Usage: codex exec review [OPTIONS] [PROMPT]\n",
            "For more information, try '--help'.\n",
        ])
        process.wait.return_value = 2
        output = self.root / "missing-review-output.json"

        with mock.patch.object(server.subprocess, "Popen", return_value=process):
            with self.assertRaises(server.WorkflowError) as context:
                server.run_codex_structured(task_id, "execution", ["codex"], self.repo, output)

        message = str(context.exception)
        self.assertIn("--uncommitted", message)
        self.assertIn("[PROMPT]", message)
        self.assertIn("try '--help'", message)

    def test_run_implementation_passes_images_to_new_and_resumed_codex_sessions(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000042"
        server.TASKS[task_id] = {"id": task_id, "worktree": {"path": str(self.repo)}}
        attachments = server.persist_feedback_images(
            task_id, server.decode_feedback_images([self.feedback_image_payload()]), "bugfix"
        )
        image_path = attachments[0]["path"]

        with mock.patch.object(server, "run_codex_structured", return_value=({}, None)) as run_structured:
            server.run_implementation(task_id, "new prompt", attachments=attachments)
            new_command = run_structured.call_args.args[2]
            server.run_implementation(task_id, "resume prompt", "thread-123", attachments=attachments)
            resume_command = run_structured.call_args.args[2]

        self.assertEqual(new_command[new_command.index("--image") + 1], image_path)
        self.assertEqual(resume_command[resume_command.index("--image") + 1], image_path)
        self.assertEqual(resume_command[:4], [server.CODEX_BIN, "exec", "resume", "--json"])

    def test_execution_job_resumes_saved_execution_thread(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000032"
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "恢复执行",
            "updatedAt": "",
            "stage": "execute",
            "maxStageIndex": 4,
            "activeJob": "execution",
            "jobState": "running",
            "sessions": {"discussion": None, "execution": "saved-execution-thread", "review": None},
            "discussion": {},
            "plan": {"finalPath": "/tmp/plan.md", "markdown": "# Plan"},
            "paths": {},
            "worktree": {"status": "ready", "path": str(self.repo), "branch": "main"},
            "execution": {"status": "error", "threadId": "saved-execution-thread", "result": None, "review": None, "logs": [], "error": "old error"},
            "verification": {"approved": False},
            "git": {"committed": False},
            "events": [],
        }
        implementation = {"summary": "恢复后完成", "changed_files": [], "verification": [], "manual_cases": []}
        clean_status = {"entries": [], "digest": "clean", "branch": "main", "head": "abc", "diffStat": "", "refreshedAt": "now"}

        with mock.patch.object(server, "run_implementation", return_value=(implementation, None)) as run_implementation, \
                mock.patch.object(server, "run_review", return_value={"verdict": "pass", "summary": "通过", "findings": []}), \
                mock.patch.object(server, "git_status", return_value=clean_status):
            server.execution_job(task_id, "继续")

        self.assertEqual(run_implementation.call_args.args[2], "saved-execution-thread")
        task = server.get_task_copy(task_id)
        self.assertEqual(task["execution"]["status"], "complete")
        self.assertEqual(task["stage"], "verify")

    def test_execution_job_retries_failed_review_without_rerunning_implementation(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000035"
        implementation = {"summary": "实施已完成", "changed_files": [], "verification": [], "manual_cases": []}
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "Review 断点恢复",
            "updatedAt": "",
            "stage": "execute",
            "maxStageIndex": 4,
            "activeJob": "execution",
            "jobState": "running",
            "sessions": {"discussion": None, "execution": "saved-execution-thread", "review": "failed-review-thread"},
            "discussion": {},
            "plan": {"finalPath": "/tmp/plan.md", "markdown": "# Plan"},
            "paths": {},
            "worktree": {"status": "ready", "path": str(self.repo), "branch": "main"},
            "execution": {
                "status": "error", "phase": "review", "threadId": "saved-execution-thread",
                "result": implementation, "review": None, "logs": [], "error": "结构化结果为空",
            },
            "verification": {"approved": False},
            "git": {"committed": False},
            "events": [],
        }
        clean_status = {"entries": [], "digest": "clean", "branch": "main", "head": "abc", "diffStat": "", "refreshedAt": "now"}

        with mock.patch.object(server, "run_implementation") as run_implementation, \
                mock.patch.object(server, "run_review", return_value={"verdict": "pass", "summary": "通过", "findings": []}), \
                mock.patch.object(server, "git_status", return_value=clean_status):
            server.execution_job(task_id, "", retry_review_only=True)

        run_implementation.assert_not_called()
        task = server.get_task_copy(task_id)
        self.assertEqual(task["execution"]["result"], implementation)
        self.assertEqual(task["execution"]["status"], "complete")
        self.assertEqual(task["stage"], "verify")
        self.assertTrue(any("仅重试失败的 Code Review" in event["message"] for event in task["events"]))
        self.assertEqual(task["sessions"]["execution"], "saved-execution-thread")

    def test_review_only_retry_is_decided_before_launch_job_overwrites_status(self) -> None:
        task = {
            "execution": {
                "status": "interrupted",
                "phase": "review",
                "result": {"summary": "实施已完成"},
            }
        }
        self.assertTrue(server.should_retry_review_only(task, "", False))
        self.assertFalse(server.should_retry_review_only(task, "有新的修复要求", False))
        self.assertFalse(server.should_retry_review_only(task, "", True))

    def test_acceptance_fix_is_only_selected_from_completed_verification(self) -> None:
        task = {
            "stage": "verify",
            "execution": {
                "status": "complete",
                "result": {"summary": "完成"},
                "review": {"verdict": "pass"},
            },
        }

        self.assertTrue(server.should_run_acceptance_fix(task, "真机发现计时错误", False))
        self.assertTrue(server.should_run_acceptance_fix(task, "", False, True))
        self.assertFalse(server.should_run_acceptance_fix(task, "", False))
        self.assertFalse(server.should_run_acceptance_fix(task, "真机发现计时错误", True))
        task["stage"] = "execute"
        self.assertFalse(server.should_run_acceptance_fix(task, "真机发现计时错误", False))
        task["stage"] = "bugfix"
        task["bugfix"] = {"status": "verify"}
        self.assertTrue(server.should_run_acceptance_fix(task, "Bug 复验仍有问题", False))

    def test_acceptance_fix_uses_fresh_bounded_worker_and_targeted_review(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000037"
        previous_result = {
            "summary": "完整实施已通过",
            "changed_files": ["old.cs"],
            "verification": [],
            "minimum_manual_verification": {"estimated_minutes": 5, "steps": []},
            "manual_cases": [{"title": "主流程", "expected": "通过"}],
            "acceptance_logs": [{"name": "主流程日志", "expected": "通过"}],
            "risks": [],
            "docs_backfill": [],
        }
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "人工验收返修",
            "updatedAt": "",
            "stage": "verify",
            "maxStageIndex": 5,
            "activeJob": "execution",
            "jobState": "running",
            "sessions": {"discussion": None, "execution": "long-old-thread", "review": None},
            "discussion": {},
            "plan": {"finalPath": "/tmp/plan.md", "markdown": "# Plan"},
            "paths": {},
            "worktree": {"status": "ready", "path": str(self.repo), "branch": "main"},
            "execution": {
                "status": "complete", "phase": "complete", "threadId": "long-old-thread",
                "result": previous_result,
                "review": {"verdict": "pass", "summary": "通过", "findings": []},
                "logs": [], "error": "",
            },
            "verification": {"approved": False, "checks": [True], "revision": 3},
            "git": {"committed": False},
            "events": [],
        }
        fix_result = {
            "summary": "只修复计时",
            "changed_files": ["timer.cs"],
            "verification": [],
            "minimum_manual_verification": {"estimated_minutes": 2, "steps": []},
            "manual_cases": [{"title": "计时返修", "expected": "恢复"}],
            "acceptance_logs": [],
            "risks": [],
            "docs_backfill": [],
        }
        clean_status = {"entries": [], "digest": "clean", "branch": "main", "head": "abc", "diffStat": "", "refreshedAt": "now"}

        with mock.patch.object(server, "run_implementation", return_value=(fix_result, "new-fix-thread")) as run_implementation, \
                mock.patch.object(server, "run_review", return_value={"verdict": "pass", "summary": "定向通过", "findings": []}) as run_review, \
                mock.patch.object(server, "worktree_change_snapshot", side_effect=[{"old.cs": "before"}, {"old.cs": "before", "timer.cs": "after"}]), \
                mock.patch.object(server, "git_status", return_value=clean_status):
            server.execution_job(task_id, "复活后计时不恢复", acceptance_fix=True)

        self.assertIsNone(run_implementation.call_args.args[2])
        self.assertEqual(run_implementation.call_args.kwargs["output_schema"], server.SCHEMA_ROOT / "acceptance-fix.schema.json")
        self.assertEqual(run_implementation.call_args.kwargs["timeout_seconds"], server.ACCEPTANCE_FIX_TIMEOUT_SECONDS)
        self.assertFalse(run_implementation.call_args.kwargs["allow_docs_root"])
        self.assertEqual(run_review.call_args.kwargs["changed_files"], ["timer.cs"])
        self.assertEqual(run_review.call_args.kwargs["acceptance_feedback"], "复活后计时不恢复")
        self.assertEqual(run_review.call_args.kwargs["timeout_seconds"], server.ACCEPTANCE_FIX_REVIEW_TIMEOUT_SECONDS)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["execution"]["mode"], "acceptance_fix")
        self.assertEqual(task["execution"]["previousThreadId"], "long-old-thread")
        self.assertEqual(task["execution"]["roundChangedFiles"], ["timer.cs"])
        self.assertEqual(task["execution"]["result"]["changed_files"], ["timer.cs", "old.cs"])
        self.assertEqual([case["title"] for case in task["execution"]["result"]["manual_cases"]], ["计时返修", "主流程"])
        self.assertEqual(task["verification"]["checks"], [False, True])
        self.assertEqual(task["verification"]["revision"], 4)
        self.assertEqual(task["stage"], "verify")

    def test_manual_verification_rejects_stale_submit_while_execution_is_active(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000038"
        server.TASKS[task_id] = {
            "id": task_id,
            "updatedAt": "",
            "stage": "verify",
            "maxStageIndex": 5,
            "activeJob": "execution",
            "jobState": "running",
            "execution": {
                "status": "running",
                "result": {"manual_cases": [{"title": "主流程", "required": True}]},
                "review": {"verdict": "pass"},
            },
            "verification": {"approved": False},
            "events": [],
        }

        with mock.patch.object(server, "refresh_git_task") as refresh_git:
            with self.assertRaisesRegex(server.WorkflowError, "任务仍在执行"):
                server.approve_manual_verification(task_id, [True], "stale")

        refresh_git.assert_not_called()
        self.assertFalse(server.get_task_copy(task_id)["verification"]["approved"])

    def test_acceptance_review_retry_keeps_round_file_scope(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000039"
        result = {
            "summary": "返修已完成",
            "changed_files": ["timer.cs", "old.cs"],
            "manual_cases": [{"title": "计时", "required": True}],
        }
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "返修 Review 重试",
            "updatedAt": "",
            "stage": "execute",
            "maxStageIndex": 5,
            "activeJob": "execution",
            "jobState": "running",
            "sessions": {"discussion": None, "execution": "fix-thread", "review": "failed-review"},
            "discussion": {},
            "plan": {"finalPath": "/tmp/plan.md", "markdown": "# Plan"},
            "paths": {},
            "worktree": {"status": "ready", "path": str(self.repo), "branch": "main"},
            "execution": {
                "status": "error", "phase": "review", "mode": "acceptance_fix",
                "threadId": "fix-thread", "result": result, "review": None,
                "roundChangedFiles": ["timer.cs"], "feedback": "计时不恢复", "logs": [], "error": "超时",
            },
            "verification": {"approved": False},
            "git": {"committed": False},
            "events": [],
        }
        clean_status = {"entries": [], "digest": "clean", "branch": "main", "head": "abc", "diffStat": "", "refreshedAt": "now"}

        with mock.patch.object(server, "run_implementation") as run_implementation, \
                mock.patch.object(server, "run_review", return_value={"verdict": "pass", "summary": "通过", "findings": []}) as run_review, \
                mock.patch.object(server, "git_status", return_value=clean_status):
            server.execution_job(task_id, "", retry_review_only=True)

        run_implementation.assert_not_called()
        self.assertEqual(run_review.call_args.kwargs["changed_files"], ["timer.cs"])
        self.assertEqual(run_review.call_args.kwargs["acceptance_feedback"], "计时不恢复")
        self.assertEqual(run_review.call_args.kwargs["timeout_seconds"], server.ACCEPTANCE_FIX_REVIEW_TIMEOUT_SECONDS)
        self.assertEqual(server.get_task_copy(task_id)["stage"], "verify")

    def test_manual_verification_approves_only_completed_reviewed_execution(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000040"
        server.TASKS[task_id] = {
            "id": task_id,
            "updatedAt": "",
            "stage": "verify",
            "maxStageIndex": 5,
            "activeJob": None,
            "jobState": "idle",
            "execution": {
                "status": "complete",
                "result": {"manual_cases": [{"title": "主流程", "required": True}]},
                "review": {"verdict": "pass"},
            },
            "verification": {"approved": False},
            "events": [],
        }

        with mock.patch.object(server, "refresh_git_task") as refresh_git:
            server.approve_manual_verification(task_id, [True], "真机通过")

        refresh_git.assert_called_once_with(task_id)
        task = server.get_task_copy(task_id)
        self.assertTrue(task["verification"]["approved"])
        self.assertEqual(task["stage"], "commit")

    def test_bugfix_verification_enters_commit_without_leaving_bugfix_module(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000045"
        server.TASKS[task_id] = {
            "id": task_id,
            "updatedAt": "",
            "stage": "bugfix",
            "maxStageIndex": server.STAGE_INDEX["bugfix"],
            "activeJob": None,
            "execution": {
                "status": "complete",
                "result": {"manual_cases": [{"title": "Bug 复验", "required": True}]},
                "review": {"verdict": "pass"},
            },
            "verification": {"approved": False},
            "bugfix": {"status": "verify"},
            "events": [],
        }

        with mock.patch.object(server, "refresh_git_task") as refresh_git:
            server.approve_manual_verification(task_id, [True], "复验通过")

        refresh_git.assert_called_once_with(task_id)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "bugfix")
        self.assertEqual(task["bugfix"]["status"], "commit")
        self.assertTrue(task["verification"]["approved"])

    def test_failed_new_review_does_not_display_the_previous_pass_as_current(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000036"
        old_review = {"verdict": "pass", "summary": "上一轮通过", "findings": []}
        implementation = {"summary": "本轮实施完成", "changed_files": ["feature.cs"], "verification": [], "manual_cases": []}
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "Review 状态隔离",
            "updatedAt": "",
            "stage": "execute",
            "maxStageIndex": 4,
            "activeJob": "execution",
            "jobState": "running",
            "sessions": {"discussion": None, "execution": "execution-thread", "review": None},
            "discussion": {},
            "plan": {"finalPath": "/tmp/plan.md", "markdown": "# Plan"},
            "paths": {},
            "worktree": {"status": "ready", "path": str(self.repo), "branch": "main"},
            "execution": {
                "status": "error", "phase": "review", "threadId": "execution-thread",
                "result": implementation, "review": old_review, "logs": [], "error": "旧错误",
            },
            "verification": {"approved": False},
            "git": {"committed": False},
            "events": [],
        }

        with mock.patch.object(server, "run_implementation") as run_implementation, \
                mock.patch.object(server, "run_review", side_effect=server.WorkflowError("本轮 Review 超时")):
            with self.assertRaisesRegex(server.WorkflowError, "本轮 Review 超时"):
                server.execution_job(task_id, "", retry_review_only=True)

        run_implementation.assert_not_called()
        task = server.get_task_copy(task_id)
        self.assertIsNone(task["execution"]["review"])
        self.assertEqual(task["execution"]["previousReview"], old_review)

    def test_cancel_task_stops_only_the_active_task_process(self) -> None:
        task_id = self.seed_task()
        server.TASKS[task_id].update({
            "activeJob": "execution",
            "jobState": "running",
            "execution": {"status": "running", "phase": "review", "logs": []},
        })
        process = mock.Mock()
        server.ACTIVE_PROCESSES[task_id] = process

        with mock.patch.object(server, "stop_codex_process") as stop_process:
            result = server.cancel_task(task_id)

        stop_process.assert_called_once_with(process)
        self.assertIn(task_id, server.CANCEL_REQUESTED)
        self.assertEqual(result["execution"]["phase"], "stopping")

    def test_reset_execution_session_keeps_memory_but_drops_resume_thread(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000033"
        server.TASKS[task_id] = {
            "id": task_id,
            "title": "重建执行会话",
            "updatedAt": "",
            "stage": "execute",
            "activeJob": None,
            "jobState": "idle",
            "sessions": {"discussion": "discussion-thread", "execution": "old-execution-thread", "review": "review-thread"},
            "discussion": {"status": "ready", "threadId": "discussion-thread", "result": {"summary": "已确认口径"}},
            "plan": {"markdown": "# Plan", "result": {"scope": ["保留任务记忆"]}},
            "paths": {},
            "worktree": {},
            "execution": {"status": "error", "threadId": "old-execution-thread", "reviewThreadId": "review-thread"},
            "verification": {"approved": True, "checks": [True], "note": "旧验收"},
            "git": {},
            "events": [],
        }

        server.prepare_execution_request(task_id, True)

        task = server.get_task_copy(task_id)
        self.assertIsNone(task["sessions"]["execution"])
        self.assertIsNone(task["execution"]["threadId"])
        self.assertEqual(task["sessions"]["discussion"], "discussion-thread")
        self.assertEqual(task["sessions"]["review"], "review-thread")
        self.assertFalse(task["verification"]["approved"])
        self.assertEqual(task["agentMemory"]["summary"], "已确认口径")
        self.assertEqual(task["agentMemory"]["scope"], ["保留任务记忆"])

    def test_codex_app_deep_link_accepts_only_safe_thread_ids(self) -> None:
        self.assertEqual(server.codex_app_deep_link("thread_123-abc"), "codex://threads/thread_123-abc")
        self.assertEqual(server.codex_app_deep_link("thread/escape"), "")
        self.assertEqual(server.codex_app_deep_link(""), "")

    def test_ensure_task_app_thread_creates_then_reuses_one_persistent_thread(self) -> None:
        task_id = self.seed_execution_task()
        calls: list[tuple[str, dict[str, object]]] = []
        client = mock.Mock()

        def request(method, params, timeout=30):
            calls.append((method, params))
            if method == "thread/start":
                return {"thread": {"id": "app-thread-123"}}
            if method == "thread/resume":
                return {"thread": {"id": params["threadId"]}}
            return {}

        client.request.side_effect = request
        with mock.patch.object(server, "get_app_server_client", return_value=client):
            first = server.ensure_task_app_thread(task_id)
            second = server.ensure_task_app_thread(task_id)

        methods = [method for method, _ in calls]
        self.assertEqual(methods.count("thread/start"), 1)
        self.assertEqual(methods.count("thread/resume"), 1)
        start_params = next(params for method, params in calls if method == "thread/start")
        self.assertEqual(start_params["sandbox"], "workspace-write")
        self.assertFalse(start_params["ephemeral"])
        self.assertEqual(start_params["cwd"], str(self.repo.resolve()))
        self.assertEqual(first["stage"], "execute")
        self.assertEqual(second["sessions"]["app"], "app-thread-123")
        self.assertEqual(second["app"]["deepLink"], "codex://threads/app-thread-123")
        self.assertEqual(second["app"]["cwd"], str(self.repo.resolve()))
        self.assertEqual(sum("已绑定后台快速执行 Thread" in item["message"] for item in second["events"]), 1)

    def test_existing_app_thread_rebinds_to_new_ready_worktree_without_duplication(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000056")
        pending_worktree = self.root / "worktrees" / "later-ready"
        with server.mutate_task(task_id) as task:
            task["sessions"]["app"] = "app-thread-existing"
            task["app"].update({
                "status": "ready",
                "threadId": "app-thread-existing",
                "deepLink": "codex://threads/app-thread-existing",
                "cwd": str(self.repo.resolve()),
            })
            task["worktree"].update({"status": "idle", "path": str(pending_worktree)})
        calls: list[tuple[str, dict[str, object]]] = []
        client = mock.Mock()

        def request(method, params, timeout=30):
            calls.append((method, params))
            if method == "thread/resume":
                return {"thread": {"id": params["threadId"]}}
            return {}

        client.request.side_effect = request
        with mock.patch.object(server, "REPO_ROOT", self.repo), \
                mock.patch.object(server, "get_app_server_client", return_value=client):
            before = server.ensure_task_app_thread(task_id)
            pending_worktree.mkdir(parents=True)
            with server.mutate_task(task_id) as task:
                task["worktree"]["status"] = "ready"
            after = server.ensure_task_app_thread(task_id)

        resumes = [params for method, params in calls if method == "thread/resume"]
        self.assertEqual([params["cwd"] for params in resumes], [str(self.repo.resolve()), str(pending_worktree.resolve())])
        self.assertNotIn("thread/start", [method for method, _ in calls])
        self.assertEqual(before["sessions"]["app"], "app-thread-existing")
        self.assertEqual(after["sessions"]["app"], "app-thread-existing")
        self.assertEqual(after["app"]["cwd"], str(pending_worktree.resolve()))
        self.assertEqual(sum("切换到当前项目目录" in item["message"] for item in after["events"]), 1)

    def test_task_app_cwd_ignores_unready_or_missing_worktree(self) -> None:
        candidate = self.root / "worktrees" / "candidate"
        candidate.mkdir(parents=True)
        with mock.patch.object(server, "REPO_ROOT", self.repo):
            self.assertEqual(server.task_app_cwd({"worktree": {"status": "validated", "path": str(candidate)}}), self.repo.resolve())
            self.assertEqual(server.task_app_cwd({"worktree": {"status": "ready", "path": str(candidate)}}), candidate.resolve())
            self.assertEqual(server.task_app_cwd({"worktree": {"status": "ready", "path": str(candidate / "missing")}}), self.repo.resolve())
            self.assertEqual(server.task_app_cwd({"worktree": {"status": "ready", "path": ""}}), self.repo.resolve())

    def test_linked_codex_app_button_refreshes_backend_binding_before_deep_link(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="openCodexApp"', app_js)
        self.assertIn('on("openCodexApp", "click", openCodexApp)', app_js)
        self.assertIn('post(`/api/tasks/${task.id}/app/open`, {})', app_js)
        self.assertNotIn('<a class="app-link-button primary"', app_js)

    def test_opening_active_app_thread_preserves_running_turn(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000057")
        with server.mutate_task(task_id) as task:
            task["sessions"]["app"] = "app-thread-running"
            task["app"].update({
                "status": "running",
                "threadId": "app-thread-running",
                "turnId": "turn-running",
                "deepLink": "codex://threads/app-thread-running",
                "cwd": str(self.repo.resolve()),
            })
        server.ACTIVE_APP_TURNS[task_id] = ("app-thread-running", "turn-running")

        with mock.patch.object(server, "get_app_server_client") as get_client:
            task = server.ensure_task_app_thread(task_id)

        get_client.assert_not_called()
        self.assertEqual(task["app"]["status"], "running")
        self.assertEqual(task["app"]["turnId"], "turn-running")
        self.assertEqual(task["app"]["cwd"], str(self.repo.resolve()))

    def test_disconnect_codex_app_chat_preserves_background_thread_and_stage(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000058")
        with server.mutate_task(task_id) as task:
            task["sessions"]["app"] = "background-thread"
            task["app"].update({
                "status": "ready",
                "threadId": "background-thread",
                "deepLink": "codex://threads/background-thread",
                "cwd": str(self.repo.resolve()),
            })
            task["sessions"]["codexApp"] = "manual-thread-old"
            task["codexApp"].update({
                "status": "ready",
                "threadId": "manual-thread-old",
                "deepLink": "codex://threads/manual-thread-old",
                "cwd": str(self.repo.resolve()),
            })

        task = server.disconnect_task_codex_app_chat(task_id)

        self.assertEqual(task["stage"], "execute")
        self.assertEqual(task["sessions"]["app"], "background-thread")
        self.assertEqual(task["app"]["threadId"], "background-thread")
        self.assertIsNone(task["sessions"]["codexApp"])
        self.assertEqual(task["codexApp"]["status"], "idle")
        self.assertIsNone(task["codexApp"]["threadId"])
        self.assertEqual(task["codexApp"]["deepLink"], "")
        self.assertEqual(task["codexApp"]["cwd"], str(self.repo.resolve()))
        self.assertTrue(any("旧聊天未删除" in item["message"] for item in task["events"]))

    def test_new_codex_app_chat_uses_isolated_server_and_keeps_background_thread(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000059")
        with server.mutate_task(task_id) as task:
            task["sessions"]["app"] = "background-thread"
            task["app"].update({
                "status": "ready",
                "threadId": "background-thread",
                "deepLink": "codex://threads/background-thread",
                "cwd": str(self.repo.resolve()),
            })
            task["sessions"]["codexApp"] = "manual-thread-old"
            task["codexApp"].update({
                "status": "ready",
                "threadId": "manual-thread-old",
                "deepLink": "codex://threads/manual-thread-old",
                "cwd": str(self.repo.resolve()),
            })
        calls: list[tuple[str, dict[str, object]]] = []
        client = mock.Mock()
        client.process = None

        def request(method, params, timeout=30):
            calls.append((method, params))
            if method == "thread/start":
                return {"thread": {"id": "manual-thread-new"}}
            return {}

        client.request.side_effect = request
        with mock.patch.object(server, "AppServerClient", return_value=client):
            task = server.start_new_task_codex_app_chat(task_id)

        methods = [method for method, _ in calls]
        self.assertEqual(methods.count("thread/start"), 1)
        self.assertNotIn("thread/resume", methods)
        client.close.assert_called_once_with()
        self.assertEqual(task["sessions"]["app"], "background-thread")
        self.assertEqual(task["app"]["threadId"], "background-thread")
        self.assertEqual(task["sessions"]["codexApp"], "manual-thread-new")
        self.assertEqual(task["codexApp"]["threadId"], "manual-thread-new")
        self.assertEqual(task["codexApp"]["deepLink"], "codex://threads/manual-thread-new")
        self.assertTrue(any("旧聊天仍保留" in item["message"] for item in task["events"]))

    def test_isolated_app_server_waits_for_writer_process_to_exit(self) -> None:
        events: list[str] = []
        process = mock.Mock()
        process.poll.return_value = None
        process.wait.side_effect = lambda timeout: events.append(f"wait:{timeout}")
        client = mock.Mock()
        client.process = process
        client.close.side_effect = lambda: events.append("close")

        server.close_isolated_app_server(client)

        self.assertEqual(events, ["close", "wait:5"])

    def test_open_existing_codex_app_chat_does_not_resume_background_writer(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000061")
        with server.mutate_task(task_id) as task:
            task["sessions"]["codexApp"] = "manual-thread-existing"
            task["codexApp"].update({
                "status": "ready",
                "threadId": "manual-thread-existing",
                "deepLink": "codex://threads/manual-thread-existing",
                "cwd": str(self.repo.resolve()),
            })

        with mock.patch.object(server, "AppServerClient") as app_server:
            task = server.ensure_task_codex_app_chat(task_id)

        app_server.assert_not_called()
        self.assertEqual(task["codexApp"]["deepLink"], "codex://threads/manual-thread-existing")

    def test_app_chat_switching_is_blocked_while_task_runs(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000060")
        server.TASKS[task_id]["activeJob"] = "execution"
        server.TASKS[task_id]["jobState"] = "running"

        with mock.patch.object(server, "AppServerClient") as app_server:
            with self.assertRaisesRegex(server.WorkflowError, "切换 Codex App 人工聊天"):
                server.start_new_task_codex_app_chat(task_id)
            with self.assertRaisesRegex(server.WorkflowError, "切换 Codex App 人工聊天"):
                server.disconnect_task_codex_app_chat(task_id)

        app_server.assert_not_called()

    def test_codex_app_panel_exposes_disconnect_and_new_chat_actions(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        self.assertIn('id="newCodexAppChat"', app_js)
        self.assertIn('id="disconnectCodexApp"', app_js)
        self.assertIn('post(`/api/tasks/${task.id}/app/new`, {})', app_js)
        self.assertIn('post(`/api/tasks/${task.id}/app/disconnect`, {})', app_js)
        self.assertIn('const app = task.codexApp || {}', app_js)
        self.assertIn('result.task?.codexApp?.deepLink', app_js)

    def test_app_server_initialization_is_shared_by_concurrent_first_requests(self) -> None:
        client = server.AppServerClient("/mock/codex")
        initialize_entered = threading.Event()
        release_initialize = threading.Event()
        errors: list[Exception] = []

        def initialize(_method, _params, timeout=20):
            initialize_entered.set()
            if not release_initialize.wait(2):
                raise AssertionError("test did not release initialize")
            return {}

        def start_client():
            try:
                client.start()
            except Exception as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        first = threading.Thread(target=start_client)
        second = threading.Thread(target=start_client)
        process = mock.Mock()
        process.poll.return_value = None
        background_thread = mock.Mock()

        with mock.patch.object(server.subprocess, "Popen", return_value=process) as popen, \
                mock.patch.object(server.threading, "Thread", return_value=background_thread), \
                mock.patch.object(client, "_request", side_effect=initialize) as request, \
                mock.patch.object(client, "notify") as notify:
            first.start()
            self.assertTrue(initialize_entered.wait(1))
            second.start()
            self.assertTrue(second.is_alive())
            release_initialize.set()
            first.join(2)
            second.join(2)

        self.assertEqual(errors, [])
        self.assertFalse(first.is_alive())
        self.assertFalse(second.is_alive())
        popen.assert_called_once()
        request.assert_called_once()
        notify.assert_called_once_with("initialized", {})
        self.assertTrue(client._initialized)
        client.process = None

    def test_app_server_turn_uses_installed_workspace_policy_shape(self) -> None:
        task_id = self.seed_execution_task()
        with server.mutate_task(task_id) as task:
            task["sessions"]["app"] = "app-thread-456"
            task["app"].update({"status": "ready", "threadId": "app-thread-456", "deepLink": "codex://threads/app-thread-456"})

        class FakeClient:
            def __init__(self, payload):
                self.payload = payload
                self.listener = None
                self.turn_params = None

            def add_listener(self, _thread_id, listener):
                self.listener = listener

            def remove_listener(self, _thread_id, _listener):
                self.listener = None

            def request(self, method, params, timeout=30):
                if method != "turn/start":
                    return {}
                self.turn_params = params
                self.listener.put({
                    "method": "item/completed",
                    "params": {"threadId": "app-thread-456", "item": {"type": "agentMessage", "text": json.dumps(self.payload, ensure_ascii=False)}},
                })
                self.listener.put({
                    "method": "turn/completed",
                    "params": {"threadId": "app-thread-456", "turn": {"id": "turn-1", "status": "completed"}},
                })
                return {"turn": {"id": "turn-1"}}

            def interrupt(self, _thread_id, _turn_id):
                raise AssertionError("completed turn must not be interrupted")

        client = FakeClient(self.quick_result())
        with mock.patch.object(server, "CODEX_BIN", "/mock/codex"), \
                mock.patch.object(server, "_ensure_task_app_thread", return_value=server.get_task_copy(task_id)), \
                mock.patch.object(server, "get_app_server_client", return_value=client):
            result, thread_id = server.run_app_server_structured(
                task_id,
                "execution",
                "quick task",
                self.repo,
                server.SCHEMA_ROOT / "execution.schema.json",
                timeout_seconds=5,
                timeout_label="快速执行",
                allow_docs_root=False,
            )

        self.assertEqual(result["summary"], "快速修改与自检完成")
        self.assertEqual(thread_id, "app-thread-456")
        self.assertEqual(client.turn_params["sandboxPolicy"]["type"], "workspaceWrite")
        self.assertNotIn("readOnlyAccess", client.turn_params["sandboxPolicy"])
        self.assertFalse(client.turn_params["sandboxPolicy"]["networkAccess"])

    def test_app_server_progress_extends_idle_timeout(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000083")
        payload = self.quick_result()
        with server.mutate_task(task_id) as task:
            task["sessions"]["app"] = "app-thread-progress"
            task["app"].update({"status": "ready", "threadId": "app-thread-progress"})

        class ProgressClient:
            def __init__(self):
                self.listener = None

            def add_listener(self, _thread_id, listener):
                self.listener = listener

            def remove_listener(self, _thread_id, _listener):
                self.listener = None

            def request(self, method, _params, timeout=30):
                if method != "turn/start":
                    return {}
                self.listener.put({
                    "method": "item/completed",
                    "params": {"item": {"type": "agentMessage", "text": json.dumps(payload, ensure_ascii=False)}},
                })
                self.listener.put({
                    "method": "turn/completed",
                    "params": {"turn": {"id": "turn-progress", "status": "completed"}},
                })
                return {"turn": {"id": "turn-progress"}}

            def interrupt(self, _thread_id, _turn_id):
                raise AssertionError("active progress must extend the idle timeout")

        client = ProgressClient()
        with mock.patch.object(server, "CODEX_BIN", "/mock/codex"), \
                mock.patch.object(server, "_ensure_task_app_thread", return_value=server.get_task_copy(task_id)), \
                mock.patch.object(server, "get_app_server_client", return_value=client), \
                mock.patch.object(server.time, "monotonic", side_effect=[0, 4, 4, 8, 8]):
            result, _ = server.run_app_server_structured(
                task_id,
                "execution",
                "quick task",
                self.repo,
                server.SCHEMA_ROOT / "execution.schema.json",
                timeout_seconds=5,
                hard_timeout_seconds=15,
                timeout_label="快速执行",
                allow_docs_root=False,
            )

        self.assertEqual(result["summary"], payload["summary"])

    def test_app_server_hard_timeout_stops_even_with_progress(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000084")
        with server.mutate_task(task_id) as task:
            task["sessions"]["app"] = "app-thread-hard-limit"
            task["app"].update({"status": "ready", "threadId": "app-thread-hard-limit"})

        class NeverCompletesClient:
            def __init__(self):
                self.listener = None
                self.interrupted = False

            def add_listener(self, _thread_id, listener):
                self.listener = listener

            def remove_listener(self, _thread_id, _listener):
                self.listener = None

            def request(self, method, _params, timeout=30):
                if method != "turn/start":
                    return {}
                for _ in range(2):
                    self.listener.put({"method": "item/completed", "params": {"item": {"type": "commandExecution", "exitCode": 0}}})
                return {"turn": {"id": "turn-hard-limit"}}

            def interrupt(self, _thread_id, _turn_id):
                self.interrupted = True

        client = NeverCompletesClient()
        with mock.patch.object(server, "CODEX_BIN", "/mock/codex"), \
                mock.patch.object(server, "_ensure_task_app_thread", return_value=server.get_task_copy(task_id)), \
                mock.patch.object(server, "get_app_server_client", return_value=client), \
                mock.patch.object(server.time, "monotonic", side_effect=[0, 4, 4, 8, 8, 11]):
            with self.assertRaisesRegex(server.WorkflowError, "绝对上限"):
                server.run_app_server_structured(
                    task_id,
                    "execution",
                    "quick task",
                    self.repo,
                    server.SCHEMA_ROOT / "execution.schema.json",
                    timeout_seconds=5,
                    hard_timeout_seconds=10,
                    timeout_label="快速执行",
                    allow_docs_root=False,
                )

        self.assertTrue(client.interrupted)

    def test_quick_timeout_with_changes_saves_partial_checkpoint(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000085")
        status = {"entries": [{"code": " M", "path": "feature.cs"}], "digest": "dirty", "branch": "main", "head": "abc", "diffStat": "1 file changed", "refreshedAt": "now"}

        with mock.patch.object(server, "worktree_change_snapshot", side_effect=[{"plan.md": "plan"}, {"plan.md": "plan", "feature.cs": "changed"}]), \
                mock.patch.object(server, "run_app_server_structured", side_effect=server.WorkflowError("连续 10 分钟没有新进度")), \
                mock.patch.object(server, "git_status", return_value=status):
            with self.assertRaisesRegex(server.PartialWorkflowError, "已保存断点"):
                server.quick_execution_job(task_id, "")

        task = server.get_task_copy(task_id)
        self.assertEqual(task["execution"]["status"], "partial")
        self.assertEqual(task["execution"]["checkpoint"]["changedFiles"], ["feature.cs"])
        self.assertEqual(task["git"]["digest"], "dirty")

    def test_quick_retry_resumes_current_diff_and_keeps_cumulative_files(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000086")
        with server.mutate_task(task_id) as task:
            task["execution"].update({
                "status": "partial",
                "flowMode": "fast",
                "error": "上轮超时",
                "checkpoint": {"attempt": 1, "changedFiles": ["feature.cs"], "lastActivity": "2026-08-11T17:17:57+08:00"},
            })
        status = {"entries": [{"code": " M", "path": "feature.cs"}], "digest": "dirty", "branch": "main", "head": "abc", "diffStat": "1 file changed", "refreshedAt": "now"}

        with mock.patch.object(server, "worktree_change_snapshot", side_effect=[{"feature.cs": "before"}, {"feature.cs": "before"}]), \
                mock.patch.object(server, "run_app_server_structured", return_value=(self.quick_result(), "app-thread-resume")) as run_app, \
                mock.patch.object(server, "git_status", return_value=status):
            server.quick_execution_job(task_id, "")

        prompt = run_app.call_args.args[2]
        self.assertIn("断点续跑", prompt)
        self.assertIn("禁止重新扫描整份 Plan", prompt)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["execution"]["result"]["changed_files"], ["feature.cs"])
        self.assertNotIn("checkpoint", task["execution"])
        self.assertEqual(task["execution"]["status"], "complete")

    def test_prepare_quick_retry_keeps_resume_intent_after_queue_transition(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000087")
        with server.mutate_task(task_id) as task:
            task["execution"].update({
                "status": "partial",
                "flowMode": "fast",
                "checkpoint": {"changedFiles": ["feature.cs"]},
            })

        server.prepare_execution_request(task_id, False, flow_mode="fast")
        with server.mutate_task(task_id) as task:
            task["execution"]["status"] = "queued"

        task = server.get_task_copy(task_id)
        self.assertTrue(task["execution"]["resumeFromCheckpoint"])
        self.assertEqual(server.quick_resume_files(task, {"feature.cs": "changed"}), ["feature.cs"])

    def test_quick_mode_skips_independent_review_and_enters_manual_verification(self) -> None:
        task_id = self.seed_execution_task()
        with mock.patch.object(server, "run_app_server_structured", return_value=(self.quick_result(), "app-thread-fast")), \
                mock.patch.object(server, "run_review") as run_review:
            server.quick_execution_job(task_id, "")

        run_review.assert_not_called()
        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "verify")
        self.assertEqual(task["execution"]["status"], "complete")
        self.assertEqual(task["execution"]["flowMode"], "fast")
        self.assertEqual(task["execution"]["review"]["verdict"], "skipped")
        self.assertEqual(task["sessions"]["app"], "app-thread-fast")

    def test_quick_bugfix_stays_inside_bugfix_module(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000052")
        with server.mutate_task(task_id) as task:
            task["stage"] = "bugfix"
            task["maxStageIndex"] = server.STAGE_INDEX["bugfix"]
            task["bugfix"] = {"status": "running", "description": "返回后计时未恢复", "attachments": [], "history": []}
            task["execution"]["result"] = self.quick_result()
            task["git"]["committed"] = False
        with mock.patch.object(server, "run_app_server_structured", return_value=(self.quick_result(), "app-thread-bug")), \
                mock.patch.object(server, "run_review") as run_review:
            server.quick_execution_job(task_id, "bugfix prompt")

        run_review.assert_not_called()
        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "bugfix")
        self.assertEqual(task["bugfix"]["status"], "verify")
        self.assertEqual(task["bugfix"]["executionMode"], "fast")
        self.assertEqual(task["execution"]["review"]["verdict"], "skipped")

    def test_quick_acceptance_fix_keeps_unaffected_manual_checks(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000082")
        previous_result = self.quick_result()
        previous_result["manual_cases"] = [
            {"title": "返修项", "required": True, "priority": "P0", "steps": ["复验"], "expected": "修复"},
            {"title": "主流程", "required": True, "priority": "P0", "steps": ["运行"], "expected": "正常"},
        ]
        fix_result = self.quick_result()
        fix_result["manual_cases"] = [
            {"title": "返修项", "required": True, "priority": "P0", "steps": ["复验"], "expected": "已修复"},
        ]
        with server.mutate_task(task_id) as task:
            task["stage"] = "verify"
            task["execution"].update({
                "status": "complete",
                "mode": "acceptance_fix",
                "result": previous_result,
                "review": {"verdict": "skipped", "summary": "快速自检", "findings": []},
            })
            task["verification"] = {"approved": False, "checks": [False, True], "note": "", "revision": 8}

        with mock.patch.object(server, "run_app_server_structured", return_value=(fix_result, "app-thread-fix")):
            server.quick_execution_job(task_id, "返修项仍有问题", acceptance_fix=True)

        task = server.get_task_copy(task_id)
        self.assertEqual([case["title"] for case in task["execution"]["result"]["manual_cases"]], ["返修项", "主流程"])
        self.assertEqual(task["verification"]["checks"], [False, True])
        self.assertEqual(task["verification"]["revision"], 9)
        self.assertEqual(task["stage"], "verify")

    def test_fast_manual_verification_accepts_skipped_independent_review(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000053")
        with server.mutate_task(task_id) as task:
            task["stage"] = "verify"
            task["maxStageIndex"] = server.STAGE_INDEX["verify"]
            task["execution"].update({
                "status": "complete",
                "flowMode": "fast",
                "result": self.quick_result(),
                "review": {"verdict": "skipped", "summary": "快速自检", "findings": []},
            })
        with mock.patch.object(server, "refresh_git_task") as refresh_git:
            server.approve_manual_verification(task_id, [True], "人工通过")

        refresh_git.assert_called_once_with(task_id)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "commit")
        self.assertTrue(task["verification"]["approved"])

    def test_cancel_interrupts_only_the_active_app_server_turn(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000054")
        server.TASKS[task_id].update({"activeJob": "execution", "jobState": "running"})
        server.TASKS[task_id]["execution"].update({"status": "running", "phase": "implementation"})
        server.ACTIVE_APP_TURNS[task_id] = ("app-thread-cancel", "turn-cancel")
        client = mock.Mock()

        with mock.patch.object(server, "get_app_server_client", return_value=client):
            server.cancel_task(task_id)

        client.interrupt.assert_called_once_with("app-thread-cancel", "turn-cancel")
        self.assertNotIn(task_id, server.ACTIVE_PROCESSES)
        self.assertIn(task_id, server.CANCEL_REQUESTED)

    def test_load_tasks_migrates_legacy_app_thread_without_changing_stage(self) -> None:
        task_id = "00000000-0000-0000-0000-000000000055"
        legacy = {
            "id": task_id,
            "title": "旧任务迁移",
            "updatedAt": "2026-07-30T10:00:00+08:00",
            "stage": "execute",
            "maxStageIndex": server.STAGE_INDEX["execute"],
            "sessions": {"app": "legacy-app-thread"},
            "discussion": {"status": "ready"},
            "plan": {"status": "ready", "markdown": "# Plan"},
            "worktree": {"status": "ready", "path": str(self.repo), "branch": "main"},
            "execution": {"status": "idle"},
            "verification": {"approved": False},
            "git": {"committed": False},
            "events": [],
        }
        target = server.task_file(task_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
        server.TASKS.clear()

        server.load_tasks()

        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "execute")
        self.assertEqual(task["sessions"]["app"], "legacy-app-thread")
        self.assertEqual(task["app"]["status"], "ready")
        self.assertEqual(task["app"]["deepLink"], "codex://threads/legacy-app-thread")
        self.assertEqual(task["app"]["cwd"], "")
        self.assertIsNone(task["sessions"]["codexApp"])
        self.assertEqual(task["codexApp"]["status"], "idle")
        self.assertEqual(task["codexApp"]["deepLink"], "")
        self.assertEqual(task["knowledge"]["status"], "idle")
        self.assertEqual(task["knowledge"]["candidates"], [])

    def test_knowledge_generation_requires_committed_idle_task(self) -> None:
        task_id = self.seed_execution_task("00000000-0000-0000-0000-000000000072")
        with self.assertRaisesRegex(server.WorkflowError, "已完成 Commit"):
            server.prepare_knowledge_generation(task_id)

        server.TASKS[task_id]["git"]["committed"] = True
        server.TASKS[task_id]["activeJob"] = "execution"
        with self.assertRaisesRegex(server.WorkflowError, "正在执行"):
            server.prepare_knowledge_generation(task_id)

        server.TASKS[task_id]["activeJob"] = None
        server.TASKS[task_id]["bugfix"] = {"status": "verify"}
        with self.assertRaisesRegex(server.WorkflowError, "Bug 修复循环尚未闭环"):
            server.prepare_knowledge_generation(task_id)

        server.TASKS[task_id]["bugfix"] = {"status": "idle"}
        server.prepare_knowledge_generation(task_id)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "knowledge")
        self.assertEqual(task["maxStageIndex"], server.STAGE_INDEX["knowledge"])

    def test_knowledge_payload_allows_zero_and_caps_candidates_at_five(self) -> None:
        task_id = self.seed_committed_knowledge_task("00000000-0000-0000-0000-000000000073")
        task = server.get_task_copy(task_id)
        base = {
            "type": "fact",
            "content": "A reusable verified fact.",
            "scope": "project",
            "appliesTo": ["future tasks"],
            "nonScope": [],
            "evidence": [{"source": "commit", "reference": task["git"]["commitId"], "detail": "delivered"}],
            "suggestedTarget": "Doc/wiki",
            "novelty": "Not recorded before",
        }
        payload = {"summary": "seven raw candidates", "candidates": [{**base, "title": f"Fact {index}"} for index in range(7)]}
        summary, candidates = server.normalize_knowledge_payload(task, payload)
        self.assertEqual(summary, "seven raw candidates")
        self.assertEqual(len(candidates), 5)
        self.assertTrue(all(item["status"] == "pending" for item in candidates))

        empty_summary, empty = server.normalize_knowledge_payload(task, {"summary": "本任务无需沉淀。", "candidates": []})
        self.assertEqual(empty_summary, "本任务无需沉淀。")
        self.assertEqual(empty, [])

    def test_knowledge_job_is_read_only_and_persists_runtime_candidates(self) -> None:
        task_id = self.seed_committed_knowledge_task("00000000-0000-0000-0000-000000000074")
        server.prepare_knowledge_generation(task_id)
        payload = {
            "summary": "one reusable decision",
            "candidates": [{
                "type": "decision",
                "title": "Keep validation separate",
                "content": "Automatic and manual validation remain separate gates.",
                "scope": "project",
                "appliesTo": ["delivery workflow"],
                "nonScope": [],
                "evidence": [{"source": "test", "reference": "tests/test_controller.py", "detail": "gate coverage"}],
                "suggestedTarget": "Doc/decisions",
                "novelty": "Reusable delivery boundary",
            }],
        }
        with mock.patch.object(server, "run_codex_structured", return_value=(payload, None)) as run_structured:
            server.knowledge_job(task_id)

        command = run_structured.call_args.args[2]
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertNotIn("git", command)
        prompt = command[-1]
        self.assertIn(str(server.task_memory_file(task_id).resolve()), prompt)
        self.assertIn(str(server.TASK_RUNTIME_CONTRACT.resolve()), prompt)
        self.assertIn("sha256:", prompt)
        self.assertNotIn('"logicalAgentId"', prompt)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "knowledge")
        self.assertEqual(task["knowledge"]["status"], "ready")
        self.assertEqual(len(task["knowledge"]["candidates"]), 1)
        self.assertTrue(server.task_file(task_id).is_file())

    def test_knowledge_review_only_updates_runtime_and_aggregates_source_task(self) -> None:
        task_id = self.seed_committed_knowledge_task("00000000-0000-0000-0000-000000000075")
        task = server.get_task_copy(task_id)
        _, candidates = server.normalize_knowledge_payload(task, {
            "summary": "candidate",
            "candidates": [{
                "type": "pitfall",
                "title": "Avoid stale state",
                "content": "Refresh runtime state before the final gate.",
                "scope": "project",
                "appliesTo": ["controller"],
                "nonScope": [],
                "evidence": [{"source": "test", "reference": "test_controller.py", "detail": "stale digest test"}],
                "suggestedTarget": "Doc/wiki",
                "novelty": "Prevents repeated failure",
            }],
        })
        with server.mutate_task(task_id) as live:
            live["knowledge"].update({"status": "ready", "generatedAt": "2026-08-10T12:00:00+08:00", "summary": "candidate", "candidates": candidates})
        head_before = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip()

        with mock.patch.object(server, "run_command") as run_command:
            reviewed = server.review_knowledge_candidate(task_id, candidates[0]["id"], "approved")

        run_command.assert_not_called()
        self.assertEqual(reviewed["knowledge"]["candidates"][0]["status"], "approved")
        self.assertEqual(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=self.repo, text=True).strip(), head_before)
        aggregate = server.list_knowledge_candidates()
        item = next(item for item in aggregate if item["taskId"] == task_id)
        self.assertEqual(item["taskTitle"], "Codex App 快速模式")
        self.assertEqual(item["status"], "approved")

        server.TASKS[task_id]["archivedAt"] = "2026-08-10T12:30:00+08:00"
        with self.assertRaisesRegex(server.WorkflowError, "先恢复"):
            server.review_knowledge_candidate(task_id, candidates[0]["id"], "ignored")

    def test_new_bugfix_withdraws_candidates_from_the_previous_commit(self) -> None:
        task_id = self.seed_committed_knowledge_task("00000000-0000-0000-0000-000000000076")
        with server.mutate_task(task_id) as task:
            task["stage"] = "knowledge"
            task["maxStageIndex"] = server.STAGE_INDEX["knowledge"]
            task["knowledge"].update({
                "status": "ready",
                "generatedAt": "2026-08-10T12:00:00+08:00",
                "candidates": [{"id": "old-candidate", "status": "approved", "title": "Old evidence"}],
            })
        status = server.git_status(self.repo)
        server.TASKS[task_id]["git"].update({**status, "committed": True, "commitId": status["head"]})

        server.prepare_bugfix_request(task_id, "new regression", status["digest"])

        task = server.get_task_copy(task_id)
        self.assertEqual(task["stage"], "bugfix")
        self.assertEqual(task["maxStageIndex"], server.STAGE_INDEX["bugfix"])
        self.assertEqual(task["knowledge"]["status"], "idle")
        self.assertEqual(task["knowledge"]["candidates"], [])

    def test_frontend_exposes_knowledge_stage_center_and_runtime_only_copy(self) -> None:
        app_js = (SERVER_PATH.parent / "app.js").read_text(encoding="utf-8")
        index_html = (SERVER_PATH.parent / "index.html").read_text(encoding="utf-8")
        self.assertIn('id: "knowledge"', app_js)
        self.assertIn('id="generateKnowledge"', app_js)
        self.assertIn('/api/knowledge', app_js)
        self.assertIn('data-knowledge-review', app_js)
        self.assertIn("不会自动修改项目文档、Skill 或 Git", app_js)
        self.assertIn('id="knowledgeCenterButton"', index_html)

    def test_health_advertises_codex_app_and_quick_mode(self) -> None:
        lark_reader = {
            "installed": True, "authenticated": True, "ready": True,
            "version": "lark-cli 1.0.82", "message": "已安装且授权状态有效。",
        }
        with mock.patch.object(server, "CODEX_BIN", ""), \
                mock.patch.object(server, "lark_cli_status", return_value=lark_reader):
            health = server.health_payload()

        self.assertTrue(health["features"]["codexAppLink"])
        self.assertTrue(health["features"]["appServer"])
        self.assertTrue(health["features"]["quickMode"])
        self.assertTrue(health["features"]["larkCliReader"])
        self.assertTrue(health["features"]["knowledge"])
        self.assertTrue(health["readers"]["larkCli"]["ready"])
        self.assertGreaterEqual(health["limits"]["quickExecutionSeconds"], 120)
        self.assertGreaterEqual(health["limits"]["quickExecutionHardSeconds"], health["limits"]["quickExecutionSeconds"])
        self.assertGreaterEqual(health["limits"]["knowledgeSeconds"], 60)


if __name__ == "__main__":
    unittest.main()
