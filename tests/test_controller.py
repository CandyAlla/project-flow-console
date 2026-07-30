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
        server.CANCEL_REQUESTED.clear()
        server.JOB_SLOTS = threading.BoundedSemaphore(2)

    def tearDown(self) -> None:
        server.TASKS.clear()
        server.ACTIVE_THREADS.clear()
        server.ACTIVE_PROCESSES.clear()
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

    def create_linked_worktree(self) -> Path:
        path = self.root / "worktrees" / "existing-task"
        path.parent.mkdir(parents=True, exist_ok=True)
        run(["git", "worktree", "add", "-b", "worktree/existing-task", str(path)], self.repo)
        return path

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
        self.assertEqual(task["stage"], "execute")
        self.assertEqual(task["maxStageIndex"], server.STAGE_INDEX["bugfix"])
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
        with mock.patch.object(server, "WORKTREES_ROOT", worktrees_root), mock.patch.object(server, "launch_job"):
            task = server.create_task({
                "title": "线性关卡 V2",
                "sourceType": "paste",
                "sourceText": "实现线性关卡的第二版流程。",
                "baseBranch": "develop",
            })

            self.assertEqual(task["worktree"]["name"], f"{server.WORKTREE_NAME_PREFIX}_pending_{task['id'][:8]}")
            changed = server.apply_semantic_worktree_slug(task["id"], "linear-level-v2")

        updated = server.get_task_copy(task["id"])
        expected_name = f"{server.WORKTREE_NAME_PREFIX}_linear-level-v2_{task['id'][:8]}"
        self.assertTrue(changed)
        self.assertEqual(updated["worktree"]["slug"], "linear-level-v2")
        self.assertEqual(updated["worktree"]["name"], expected_name)
        self.assertEqual(updated["worktree"]["branch"], f"worktree/{expected_name}")
        self.assertEqual(Path(updated["worktree"]["path"]), worktrees_root / expected_name)

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

        self.assertIn("minimum_manual_verification", prompt)
        self.assertIn("3–5 分钟", prompt)
        self.assertIn("P0/P1/P2", prompt)
        self.assertIn("acceptance_logs", prompt)
        self.assertIn("禁止每帧刷屏", prompt)
        self.assertIn("不得写成 passed", prompt)

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

    def test_lark_links_require_chrome_mcp_without_accepting_spoofed_hosts(self) -> None:
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
            "worktree": {"name": "Project_running", "status": "idle"}, "execution": {}, "git": {"committed": False},
        }
        server.TASKS.update({older["id"]: older, newer["id"]: newer})
        summaries = server.list_task_summaries()
        self.assertEqual([item["id"] for item in summaries], [newer["id"], older["id"]])
        self.assertEqual(summaries[0]["state"], "queued")
        self.assertNotIn("source", summaries[0])

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
        self.assertEqual(memory, disk)
        self.assertEqual(memory["summary"], "实现完成")
        self.assertEqual(memory["sessions"], {"discussion": "discussion-thread", "execution": "execution-thread", "review": "review-thread"})
        self.assertIn("worker_count: 2", memory["decisions"])
        self.assertIn("server.py", memory["relevantFiles"])
        self.assertIn("人工验收", memory["completedSteps"])
        self.assertTrue(memory["fingerprints"]["planSha256"])

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
            "verification": {"approved": False},
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


if __name__ == "__main__":
    unittest.main()
