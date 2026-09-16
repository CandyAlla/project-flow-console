from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest import mock

import test_controller as controller


server = controller.server


class SourceReadFlowTests(unittest.TestCase):
    """Exercise the reading workflow without invoking accounts, browsers or CLIs."""

    seed_execution_task = controller.ControllerTests.seed_execution_task
    tearDown = controller.ControllerTests.tearDown

    def setUp(self) -> None:
        controller.ControllerTests.setUp(self)
        for name, value in (
            ("REPO_ROOT", self.repo),
            ("WORKSPACE_ROOT", self.root),
            ("WORKTREES_ROOT", self.root / "worktrees"),
            ("DOCS_ROOT", self.root / "docs"),
            ("HTML_TASK_ROOT", self.root / "docs" / "tasks"),
        ):
            patcher = mock.patch.object(server, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, kwargs in (
            ("shared_memory_context", {"return_value": "测试不访问共享记忆服务。"}),
            ("lark_cli_status", {"return_value": {"ready": True, "message": "测试读取通道可用。"}}),
            ("run_codex_structured", {"side_effect": AssertionError("Test attempted an unmocked Codex call")}),
        ):
            patcher = mock.patch.object(server, name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        fetch_patch = mock.patch.object(server.lark_source, "fetch_document", side_effect=lambda url, call: {
            "title": "活动入口需求", "url": url,
            "body": "# 活动入口\n点击按钮打开指定页面。\n\n## 失败处理\n网络失败展示重试入口。",
            "sections": ["活动入口", "失败处理"], "missingSections": [], "missingAttachments": [],
            "coverage": "complete", "rawResults": {"document": {}, "sheets": []},
        })
        fetch_patch.start()
        self.addCleanup(fetch_patch.stop)

    def seed_source_task(self, reader: str = "chrome_mcp") -> str:
        task_id = self.seed_execution_task()
        with server.mutate_task(task_id) as task:
            task.update({
                "stage": "discuss", "maxStageIndex": server.STAGE_INDEX["discuss"], "archivedAt": "",
                "source": {"type": "link", "reader": reader, "url": "https://example.feishu.cn/docx/actual-document"},
                "sourceRead": server.source_reading.default_state(),
            })
            task["plan"].update({"status": "idle", "approved": False})
            task["discussion"].update({
                "status": "error", "threadId": "original-discussion-thread",
                "messages": [{"role": "user", "note": "保留原讨论答案", "answers": {"platform": "both"}}],
                "logs": ["此前读取失败"], "error": "Codex auth token is unavailable",
                "result": {"summary": "此前已有讨论", "questions": [], "ready_for_plan": True},
            })
            task["sessions"]["discussion"] = "original-discussion-thread"
        return task_id

    def document(self, task_id: str, **changes) -> dict:
        return {
            "title": "活动入口需求", "url": server.get_task_copy(task_id)["source"]["url"],
            "body": "# 活动入口\n点击按钮打开指定页面。\n\n## 失败处理\n网络失败展示重试入口。",
            "sections": ["活动入口", "失败处理"], "missingSections": [], "missingAttachments": [],
            "coverage": "complete", **changes,
        }

    def test_link_creation_waits_for_manual_import_without_launching_codex(self) -> None:
        with mock.patch.object(server, "launch_job") as launch:
            task = server.create_task({
                "title": "读取活动入口需求", "sourceType": "link",
                "sourceUrl": "https://example.feishu.cn/docx/actual-document", "baseBranch": "main",
            })
        self.assertEqual(task["sourceRead"]["status"], "blocked")
        self.assertEqual(task["sourceRead"]["errorCode"], "manual_import_required")
        self.assertEqual(task["source"]["reader"], "manual_import")
        self.assertEqual(task["discussion"]["status"], "idle")
        self.assertIsNone(task["discussion"]["threadId"])
        self.assertIsNone(task["sourceRead"]["snapshot"])
        launch.assert_not_called()
        server.run_codex_structured.assert_not_called()

    def test_profile_defaults_are_resolved_and_frozen_on_each_new_task(self) -> None:
        payload = {"title": "读取通用文档", "sourceType": "link", "sourceUrl": "https://docs.example.com/requirements"}
        with mock.patch.object(server, "PROJECT_PROFILE", {"sourceReading": {"defaultReader": "manual_import", "attachmentPolicy": "required"}}), mock.patch.object(server, "launch_job"):
            first = server.create_task(payload)
            self.assertEqual(first["source"]["reader"], "manual_import")
            self.assertEqual(first["source"]["attachmentPolicy"], "required")
        with mock.patch.object(server, "PROJECT_PROFILE", {"sourceReading": {"defaultReader": "auto", "attachmentPolicy": "optional"}}), mock.patch.object(server, "launch_job") as launch:
            second = server.create_task(payload)
            self.assertEqual(second["source"]["reader"], "codex_read_only")
            self.assertNotIn("sourceRead", second)
            self.assertEqual(launch.call_args.args[1], "discussion")
            self.assertEqual(server.source_attachment_policy(server.get_task_copy(first["id"])), "required")

    def test_reader_defaults_fall_back_to_a_valid_material_path(self) -> None:
        public_url = "https://docs.example.com/requirements"
        lark_url = "https://example.feishu.cn/docx/Abc123"
        cases = (
            ("auto", public_url, "optional", "codex_read_only"),
            ("auto", public_url, "required", "manual_import"),
            ("auto", lark_url, "optional", "manual_import"),
            ("lark_cli", public_url, "optional", "manual_import"),
            ("codex_read_only", lark_url, "optional", "manual_import"),
            ("codex_read_only", public_url, "required", "manual_import"),
        )
        for default, url, policy, expected in cases:
            with self.subTest(default=default, url=url, policy=policy), mock.patch.object(server, "PROJECT_PROFILE", {"sourceReading": {"defaultReader": default}}):
                self.assertEqual(server.resolve_source_reader(url, None, policy), expected)
        for requested, url, policy in (("lark_cli", public_url, "optional"), ("codex_read_only", lark_url, "optional"), ("codex_read_only", public_url, "required")):
            with self.subTest(reader=requested, policy=policy), self.assertRaises(server.WorkflowError):
                server.resolve_source_reader(url, requested, policy)

    def test_manual_import_accepts_non_lark_sources_and_records_generic_method(self) -> None:
        with mock.patch.object(server, "launch_job") as launch:
            task = server.create_task({"title": "外部文档", "sourceType": "link", "sourceUrl": "https://docs.example.com/spec", "sourceReader": "manual_import"})
        imported = server.import_source_document(task["id"], self.document(task["id"]))
        self.assertEqual(imported["sourceRead"]["status"], "ready")
        self.assertEqual(imported["sourceRead"]["snapshot"]["method"], "manual_import")
        self.assertNotIn("Chrome", imported["sourceRead"]["error"])
        launch.assert_not_called()

    def test_required_attachments_block_every_discussion_and_plan_entry(self) -> None:
        task_id = self.seed_source_task("manual_import")
        server.configure_source_reading(task_id, {"reader": "manual_import", "attachmentPolicy": "required"})
        task = server.import_source_document(task_id, self.document(task_id, missingAttachments=["核心交互图"]))
        self.assertEqual(task["sourceRead"]["snapshot"]["coverage"], "complete")
        self.assertEqual(task["sourceRead"]["errorCode"], "attachments_required")
        for action in ("discussion", "discussion/retry", "plan", "plan/direct"):
            with self.subTest(action=action), self.assertRaises(server.WorkflowError):
                server.ensure_flow_action_allowed(task, action)
        approval = copy.deepcopy(task)
        approval["stage"] = "plan"
        with self.assertRaises(server.WorkflowError):
            server.ensure_flow_action_allowed(approval, "plan/approve")
        with self.assertRaises(server.WorkflowError):
            server.continue_from_source(task_id)
        # A stale or forged ready flag must not bypass the attachment policy.
        task["sourceRead"]["status"] = "ready"
        with self.assertRaises(server.WorkflowError):
            server.require_source_ready(task)

    def test_policy_changes_recheck_saved_material_and_require_discussion_again(self) -> None:
        task_id = self.seed_source_task("manual_import")
        task = server.import_source_document(task_id, self.document(task_id, missingAttachments=["设计稿"]))
        revision = task["sourceRead"]["revision"]
        with server.mutate_task(task_id) as live:
            live["discussion"].update({"status": "ready", "sourceRevision": revision})
        strict = server.configure_source_reading(task_id, {"reader": "manual_import", "attachmentPolicy": "required"})
        self.assertEqual(strict["sourceRead"]["errorCode"], "attachments_required")
        self.assertEqual(strict["sourceRead"]["revision"], revision)
        self.assertEqual(strict["discussion"]["threadId"], "original-discussion-thread")
        relaxed = server.configure_source_reading(task_id, {"reader": "manual_import", "attachmentPolicy": "optional"})
        self.assertEqual(relaxed["sourceRead"]["status"], "ready")
        self.assertNotIn("sourceRevision", relaxed["discussion"])
        with self.assertRaises(server.WorkflowError):
            server.require_source_applied(relaxed)
        with mock.patch.object(server, "launch_job") as launch:
            server.continue_from_source(task_id)
        self.assertEqual(launch.call_args.args[:2], (task_id, "discussion"))

    def test_explicit_reader_switch_preserves_history_and_requires_fresh_confirmation(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        with server.mutate_task(task_id) as live:
            snapshot = server.source_reading.validate_snapshot(live["source"], self.document(task_id), read_at=server.now_iso(), method="automated")
            server.store_source_snapshot(live, snapshot)
        old = server.get_task_copy(task_id)
        changed = server.configure_source_reading(task_id, {"reader": "manual_import", "attachmentPolicy": "optional"})
        self.assertTrue(changed["sourceRead"]["refreshRequired"])
        self.assertEqual(changed["sourceRead"]["snapshot"], old["sourceRead"]["snapshot"])
        self.assertEqual(changed["discussion"]["messages"], old["discussion"]["messages"])
        with self.assertRaises(server.WorkflowError):
            server.require_source_ready(changed)
        imported = server.import_source_document(task_id, self.document(task_id))
        self.assertEqual(imported["sourceRead"]["revision"], old["sourceRead"]["revision"] + 1)
        self.assertFalse(imported["sourceRead"]["refreshRequired"])
        self.assertEqual(imported["sourceRead"]["status"], "ready")

    def test_policy_change_cannot_reactivate_material_after_explicit_retry(self) -> None:
        task_id = self.seed_source_task("manual_import")
        server.import_source_document(task_id, self.document(task_id))
        server.prepare_source_retry(task_id)
        changed = server.configure_source_reading(task_id, {"reader": "manual_import", "attachmentPolicy": "required"})
        self.assertTrue(changed["sourceRead"]["refreshRequired"])
        with self.assertRaises(server.WorkflowError):
            server.require_source_ready(changed)

    def test_legacy_tasks_keep_optional_policy_when_profile_defaults_change(self) -> None:
        task_id = self.seed_source_task()
        with mock.patch.object(server, "PROJECT_PROFILE", {"sourceReading": {"attachmentPolicy": "required"}}):
            task = server.import_source_document(task_id, self.document(task_id, missingAttachments=["可选参考"]))
            self.assertEqual(task["sourceRead"]["status"], "ready")
            self.assertEqual(task["sourceRead"]["snapshot"]["method"], "desktop_import")
            self.assertEqual(server.source_attachment_policy(task), "optional")
            server.require_source_ready(task)

    def test_legacy_reader_can_be_migrated_without_losing_confirmed_material(self) -> None:
        task_id = self.seed_source_task()
        before = server.import_source_document(task_id, self.document(task_id))
        with server.mutate_task(task_id) as live:
            live["discussion"].update({"status": "ready", "sourceRevision": before["sourceRead"]["revision"]})
        migrated = server.configure_source_reading(task_id, {"reader": "manual_import", "attachmentPolicy": "optional"})
        self.assertEqual(migrated["source"]["reader"], "manual_import")
        self.assertEqual(migrated["sourceRead"]["snapshot"], before["sourceRead"]["snapshot"])
        self.assertEqual(migrated["discussion"]["status"], "ready")
        server.require_source_ready(migrated)
        server.require_source_applied(migrated)
        retried = server.prepare_source_retry(task_id)
        self.assertEqual(retried["sourceRead"]["errorCode"], "manual_import_required")
        self.assertNotIn("Chrome", retried["sourceRead"]["error"])

    def test_complete_required_material_is_ready_but_needs_explicit_discussion(self) -> None:
        task_id = self.seed_source_task("manual_import")
        server.configure_source_reading(task_id, {"reader": "manual_import", "attachmentPolicy": "required"})
        task = server.import_source_document(task_id, self.document(task_id, body="完整正文，含已读取附件的规则与数据。"))
        server.require_source_ready(task)
        self.assertEqual(task["sourceRead"]["status"], "ready")
        with self.assertRaises(server.WorkflowError):
            server.require_source_applied(task)
        self.assertIn("附件和引用全部读取", server.source_prompt(task))

    def test_configuration_is_guarded_and_does_not_start_external_reading(self) -> None:
        task_id = self.seed_source_task("manual_import")
        settings = {"reader": "lark_cli", "attachmentPolicy": "required"}
        with mock.patch.object(server, "launch_job") as launch, mock.patch.object(server, "lark_cli_status", side_effect=AssertionError("configuration must not probe credentials")):
            changed = server.configure_source_reading(task_id, settings)
        self.assertEqual(changed["source"]["reader"], "lark_cli")
        launch.assert_not_called()
        for update in ({"activeJob": "ask"}, {"archivedAt": "archived"}, {"stage": "plan"}):
            with self.subTest(update=update):
                before = server.get_task_copy(task_id)
                with server.mutate_task(task_id) as live:
                    live.update(update)
                guarded = server.get_task_copy(task_id)
                with self.assertRaises(server.WorkflowError):
                    server.configure_source_reading(task_id, {"reader": "manual_import", "attachmentPolicy": "optional"})
                self.assertEqual(server.get_task_copy(task_id), guarded)
                server.TASKS[task_id] = before

    def test_configuration_rejects_invalid_policy_and_gate_bypasses_atomically(self) -> None:
        task_id = self.seed_source_task("manual_import")
        before = server.get_task_copy(task_id)
        for payload in (
            {"reader": "codex_read_only", "attachmentPolicy": "optional"},
            {"reader": [], "attachmentPolicy": "required"},
            {"reader": "manual_import", "attachmentPolicy": "skip"},
            {"reader": "manual_import", "attachmentPolicy": "required", "command": "anything"},
        ):
            with self.subTest(payload=payload), self.assertRaises(server.WorkflowError):
                server.configure_source_reading(task_id, payload)
            self.assertEqual(server.get_task_copy(task_id), before)

    def test_lark_required_policy_cannot_lose_host_reader_attachment_gaps(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        server.configure_source_reading(task_id, {"reader": "lark_cli", "attachmentPolicy": "required"})
        material = {**self.document(task_id), "missingAttachments": ["需求图片"], "rawResults": {}}
        with mock.patch.object(server.lark_source, "fetch_document", return_value=material):
            server.source_read_job(task_id)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["sourceRead"]["snapshot"]["coverage"], "complete")
        self.assertEqual(task["sourceRead"]["snapshot"]["missingAttachments"], ["需求图片"])
        self.assertEqual(task["sourceRead"]["errorCode"], "attachments_required")
        self.assertEqual(task["sourceRead"]["status"], "blocked")
        server.run_codex_structured.assert_not_called()

    def test_blocked_read_prevents_discussion_plan_direct_and_approval(self) -> None:
        task_id = self.seed_source_task()
        before = server.get_task_copy(task_id)
        for action in ("discussion", "discussion/retry", "plan", "plan/direct"):
            with self.subTest(action=action), self.assertRaisesRegex(server.WorkflowError, "正文尚未完整读取"):
                server.ensure_flow_action_allowed(before, action)
        approval = copy.deepcopy(before)
        approval["stage"] = "plan"
        approval["plan"].update({"status": "ready", "approved": False})
        with self.assertRaisesRegex(server.WorkflowError, "正文尚未完整读取"):
            server.ensure_flow_action_allowed(approval, "plan/approve")
        for operation in (
            lambda: server.initial_discussion_job(task_id),
            lambda: server.continue_discussion_job(task_id, {}, ""),
            lambda: server.plan_job(task_id, {}, ""),
            lambda: server.prepare_direct_execution(task_id),
            lambda: server.continue_from_source(task_id),
        ):
            with self.assertRaisesRegex(server.WorkflowError, "正文尚未完整读取"):
                operation()
        self.assertEqual(server.get_task_copy(task_id), before)
        server.run_codex_structured.assert_not_called()

    def test_partial_snapshot_is_saved_for_inspection_but_cannot_continue(self) -> None:
        task_id = self.seed_source_task()
        document = self.document(task_id, missingSections=["埋点"], missingAttachments=["平台差异图"])
        task = server.import_source_document(task_id, document)
        self.assertEqual(task["sourceRead"]["status"], "blocked")
        self.assertEqual(task["sourceRead"]["errorCode"], "read_incomplete")
        self.assertEqual(task["sourceRead"]["snapshot"]["coverage"], "partial")
        self.assertEqual(server.source_snapshot_path(task).read_text(encoding="utf-8"), document["body"])
        with mock.patch.object(server, "launch_job") as launch, self.assertRaises(server.WorkflowError):
            server.continue_from_source(task_id)
        launch.assert_not_called()

    def test_complete_import_with_unread_attachments_can_continue(self) -> None:
        task_id = self.seed_source_task()
        task = server.import_source_document(task_id, self.document(task_id, missingAttachments=["外部参考文档"]))
        self.assertEqual(task["sourceRead"]["status"], "ready")
        self.assertEqual(task["sourceRead"]["snapshot"]["missingAttachments"], ["外部参考文档"])
        with mock.patch.object(server, "launch_job") as launch:
            server.continue_from_source(task_id)
        self.assertEqual(launch.call_args.args[:2], (task_id, "discussion"))
        prompt = server.source_prompt(task)
        self.assertIn("外部参考文档", prompt)
        self.assertIn("用户允许不读取附件和引用文档", prompt)

    def test_complete_import_persists_revisions_and_preserves_original_session(self) -> None:
        task_id = self.seed_source_task()
        before = server.get_task_copy(task_id)
        document = self.document(task_id)
        first = server.import_source_document(task_id, document)
        self.assertEqual(first["sourceRead"]["status"], "ready")
        self.assertEqual(first["sourceRead"]["snapshot"]["method"], "desktop_import")
        first_path = server.task_dir(task_id) / "source" / "document-1.md"
        self.assertEqual(first_path.read_text(encoding="utf-8"), document["body"])
        self.assertEqual(first["discussion"]["threadId"], before["discussion"]["threadId"])
        self.assertEqual(first["discussion"]["messages"], before["discussion"]["messages"])
        self.assertEqual(first["sessions"]["discussion"], before["sessions"]["discussion"])
        second_document = self.document(task_id, body=document["body"] + "\n第二版增加失败处理文案。")
        second = server.import_source_document(task_id, second_document)
        self.assertEqual(second["sourceRead"]["revision"], 2)
        second_path = server.task_dir(task_id) / "source" / "document-2.md"
        self.assertEqual(second_path.read_text(encoding="utf-8"), second_document["body"])
        self.assertEqual(first_path.read_text(encoding="utf-8"), document["body"])
        persisted = json.loads(server.task_file(task_id).read_text(encoding="utf-8"))
        self.assertEqual(persisted["sourceRead"], second["sourceRead"])

    def test_existing_discussion_resumes_with_current_local_source_material(self) -> None:
        task_id = self.seed_source_task()
        task = server.import_source_document(task_id, self.document(task_id))
        previous_messages = copy.deepcopy(task["discussion"]["messages"])
        result = {"summary": "根据正文更新结论", "questions": [], "ready_for_plan": True}
        with mock.patch.object(server, "launch_job", side_effect=lambda _id, _name, target: target()) as launch, \
                mock.patch.object(server, "run_codex_structured", return_value=(result, "original-discussion-thread")) as run:
            server.continue_from_source(task_id)
        launch.assert_called_once()
        command = run.call_args.args[2]
        self.assertEqual(command[1:3], ["exec", "resume"])
        self.assertEqual(command[-2], "original-discussion-thread")
        self.assertIn(str(server.source_snapshot_path(task)), command[-1])
        self.assertIn("本次已保存正文替代本会话此前的在线读取要求", command[-1])
        self.assertNotIn("$chrome:control-chrome", command[-1])
        current = server.get_task_copy(task_id)
        self.assertEqual(current["discussion"]["threadId"], "original-discussion-thread")
        self.assertEqual(current["sessions"]["discussion"], "original-discussion-thread")
        self.assertEqual(current["discussion"]["messages"][:-1], previous_messages)
        self.assertEqual(current["discussion"]["sourceRevision"], current["sourceRead"]["revision"])
        self.assertEqual(current["discussion"]["status"], "ready")
        with mock.patch.object(server, "launch_job") as duplicate, self.assertRaisesRegex(server.WorkflowError, "无需重复启动"):
            server.continue_from_source(task_id)
        duplicate.assert_not_called()

    def test_new_discussion_is_launched_only_after_source_is_ready(self) -> None:
        task_id = self.seed_source_task()
        with server.mutate_task(task_id) as task:
            task["discussion"]["threadId"] = None
            task["sessions"]["discussion"] = None
        server.import_source_document(task_id, self.document(task_id))
        with mock.patch.object(server, "launch_job", side_effect=lambda _id, _name, target: target()), \
                mock.patch.object(server, "initial_discussion_job") as initial, \
                mock.patch.object(server, "continue_discussion_job") as resume:
            server.continue_from_source(task_id)
        initial.assert_called_once_with(task_id)
        resume.assert_not_called()

    def test_imported_revision_must_be_applied_to_discussion_before_planning(self) -> None:
        task_id = self.seed_source_task()
        task = server.import_source_document(task_id, self.document(task_id))
        with server.mutate_task(task_id) as live:
            live["discussion"].update({"status": "ready", "sourceRevision": 0})
        for action in ("plan", "plan/direct"):
            with self.subTest(action=action), self.assertRaisesRegex(server.WorkflowError, "文档内容已更新"):
                server.ensure_flow_action_allowed(server.get_task_copy(task_id), action)
        with self.assertRaisesRegex(server.WorkflowError, "文档内容已更新"):
            server.plan_job(task_id, {}, "")
        with server.mutate_task(task_id) as live:
            live["discussion"]["sourceRevision"] = task["sourceRead"]["revision"]
        server.ensure_flow_action_allowed(server.get_task_copy(task_id), "plan")

    def test_retry_invalidates_readiness_but_retains_snapshot_and_discussion(self) -> None:
        task_id = self.seed_source_task()
        before = server.import_source_document(task_id, self.document(task_id))
        with mock.patch.object(server, "launch_job") as launch:
            server.start_source_read(task_id)
        launch.assert_not_called()
        task = server.get_task_copy(task_id)
        self.assertEqual(task["sourceRead"]["status"], "blocked")
        self.assertEqual(task["sourceRead"]["errorCode"], "manual_import_required")
        self.assertEqual(task["sourceRead"]["snapshot"], before["sourceRead"]["snapshot"])
        self.assertEqual(task["sourceRead"]["revision"], before["sourceRead"]["revision"])
        self.assertEqual(task["discussion"], before["discussion"])
        self.assertEqual(task["sessions"], before["sessions"])
        self.assertTrue(server.source_snapshot_path(task).is_file())
        with self.assertRaises(server.WorkflowError):
            server.require_source_ready(task)

    def test_busy_archived_and_completed_stage_reject_source_mutations(self) -> None:
        task_id = self.seed_source_task()
        server.import_source_document(task_id, self.document(task_id))
        clean = server.get_task_copy(task_id)
        for state in ({"activeJob": "plan"}, {"archivedAt": "2026-09-09T12:30:00Z"}, {"stage": "execute"}):
            for action in ("import", "retry", "continue"):
                with self.subTest(state=state, action=action):
                    server.TASKS[task_id] = copy.deepcopy({**clean, **state})
                    before = server.get_task_copy(task_id)
                    operation = {
                        "import": lambda: server.import_source_document(task_id, self.document(task_id)),
                        "retry": lambda: server.start_source_read(task_id),
                        "continue": lambda: server.continue_from_source(task_id),
                    }[action]
                    # Real launch_job performs the busy guard before starting a thread.
                    with mock.patch.object(server.threading, "Thread") as thread, self.assertRaises(server.WorkflowError):
                        operation()
                    thread.assert_not_called()
                    self.assertEqual(server.get_task_copy(task_id), before)

    def test_invalid_import_does_not_replace_the_saved_snapshot(self) -> None:
        task_id = self.seed_source_task()
        before = server.import_source_document(task_id, self.document(task_id))
        for changes in ({"url": "https://example.feishu.cn/docx/other"}, {"body": ""}, {"summary": "摘要不是正文"}):
            with self.subTest(changes=changes), self.assertRaises(server.WorkflowError):
                server.import_source_document(task_id, self.document(task_id, **changes))
            self.assertEqual(server.get_task_copy(task_id), before)

    def test_failed_snapshot_write_preserves_previous_ready_revision_and_discussion(self) -> None:
        task_id = self.seed_source_task()
        server.import_source_document(task_id, self.document(task_id))
        with server.mutate_task(task_id) as task:
            task["discussion"].update({"status": "ready", "sourceRevision": task["sourceRead"]["revision"]})
        before = server.get_task_copy(task_id)
        persisted_before = server.task_file(task_id).read_bytes()
        old_body = server.source_snapshot_path(before).read_text(encoding="utf-8")
        failed_path = server.task_dir(task_id) / "source" / "document-2.tmp"
        original_write = Path.write_text
        attempted = []

        def fail_new_snapshot(path, text, *args, **kwargs):
            if path == failed_path:
                attempted.append(path)
                raise OSError("simulated full disk")
            return original_write(path, text, *args, **kwargs)

        with mock.patch.object(Path, "write_text", new=fail_new_snapshot), self.assertRaises(OSError):
            server.import_source_document(task_id, self.document(task_id, body="第二份正文无法落盘。"))
        self.assertEqual(attempted, [failed_path])
        self.assertEqual(server.get_task_copy(task_id), before)
        self.assertEqual(server.task_file(task_id).read_bytes(), persisted_before)
        self.assertEqual(server.source_snapshot_path(before).read_text(encoding="utf-8"), old_body)
        self.assertFalse(failed_path.with_suffix(".md").exists())
        server.require_source_ready(server.get_task_copy(task_id))

    def test_direct_execution_rejects_material_changed_during_worktree_preview(self) -> None:
        task_id = self.seed_source_task()
        server.import_source_document(task_id, self.document(task_id))
        with server.mutate_task(task_id) as task:
            task["discussion"].update({"status": "ready", "sourceRevision": task["sourceRead"]["revision"]})
        after_concurrent_update = []

        def replace_source_and_finish_discussion(candidate):
            self.assertEqual(candidate["sourceRead"]["revision"], 1)
            server.import_source_document(task_id, self.document(task_id, body="第二版正文：改为活动结束后关闭入口。"))
            with server.mutate_task(task_id) as task:
                task["discussion"].update({
                    "status": "ready", "sourceRevision": task["sourceRead"]["revision"],
                    "result": {"summary": "第二版要求结束后关闭入口", "questions": [], "ready_for_plan": True},
                })
            after_concurrent_update.append(server.get_task_copy(task_id))
            return "dry-run 完成，但需求正文和讨论已更新"

        with mock.patch.object(server, "worktree_preview", side_effect=replace_source_and_finish_discussion) as preview, \
                self.assertRaisesRegex(server.WorkflowError, "需求材料或讨论结果已变化"):
            server.prepare_direct_execution(task_id, "这是第一版的执行补充")
        preview.assert_called_once()
        current = server.get_task_copy(task_id)
        self.assertEqual(current, after_concurrent_update[0])
        self.assertEqual(current["sourceRead"]["revision"], 2)
        self.assertEqual(current["discussion"]["sourceRevision"], 2)
        self.assertEqual(current["stage"], "discuss")
        self.assertFalse(current["plan"]["approved"])
        self.assertFalse((server.task_dir(task_id) / "direct-execution.md").exists())

    def test_missing_snapshot_file_prevents_source_prompt_generation(self) -> None:
        task_id = self.seed_source_task()
        task = server.import_source_document(task_id, self.document(task_id))
        server.source_snapshot_path(task).unlink()
        with self.assertRaisesRegex(server.WorkflowError, "正文文件不存在"):
            server.source_prompt(task)

    def test_restart_interrupts_queued_or_running_reads_without_dropping_material(self) -> None:
        task_id = self.seed_source_task()
        saved = server.import_source_document(task_id, self.document(task_id))
        for status in ("queued", "running"):
            with self.subTest(status=status):
                server.TASKS[task_id] = copy.deepcopy(saved)
                with server.mutate_task(task_id) as task:
                    task["sourceRead"]["status"] = status
                    task.update({"activeJob": "sourceRead", "jobState": status})
                server.TASKS.clear()
                server.load_tasks()
                task = server.get_task_copy(task_id)
                self.assertEqual(task["sourceRead"]["status"], "interrupted")
                self.assertEqual(task["sourceRead"]["snapshot"], saved["sourceRead"]["snapshot"])
                self.assertEqual(task["discussion"], saved["discussion"])
                self.assertEqual(task["sessions"]["discussion"], "original-discussion-thread")
                self.assertIsNone(task["activeJob"])
                self.assertEqual(task["jobState"], "idle")

    def test_restart_preserves_legacy_plan_and_execution_without_adding_read_gate(self) -> None:
        task_id = self.seed_source_task()
        for stage in ("plan", "execute"):
            with self.subTest(stage=stage):
                with server.mutate_task(task_id) as task:
                    task.update({"stage": stage, "maxStageIndex": server.STAGE_INDEX[stage]})
                    task.pop("sourceRead", None)
                    task["discussion"]["status"] = "ready"
                    task["plan"].update({"status": "ready", "approved": stage == "execute", "markdown": "# 已有 Plan 不重写"})
                    task["execution"].update({"status": "idle", "phase": "idle", "taskChangedFiles": ["keep-existing.cs"]})
                before = server.get_task_copy(task_id)
                server.TASKS.clear()
                server.load_tasks()
                current = server.get_task_copy(task_id)
                self.assertNotIn("sourceRead", current)
                self.assertEqual(current["stage"], stage)
                self.assertEqual(current["plan"], before["plan"])
                self.assertEqual(current["execution"], before["execution"])
                server.require_source_ready(current)

    def test_lark_retry_queues_a_separate_reader_and_forbids_implicit_import(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        with self.assertRaisesRegex(server.WorkflowError, "不能隐式切换"):
            server.import_source_document(task_id, self.document(task_id))
        with mock.patch.object(server, "launch_job") as launch:
            server.start_source_read(task_id)
        self.assertEqual(launch.call_args.args[:2], (task_id, "sourceRead"))
        self.assertEqual(server.get_task_copy(task_id)["sessions"]["discussion"], "original-discussion-thread")

    def test_lark_read_does_not_overwrite_discussion_binding_or_create_a_codex_session(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        before = server.get_task_copy(task_id)
        server.source_read_job(task_id)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["sourceRead"]["status"], "ready")
        self.assertEqual(task["sourceRead"]["snapshot"]["method"], "automated")
        self.assertNotIn("sourceRead", task["sessions"])
        self.assertEqual(task["sessions"]["discussion"], before["sessions"]["discussion"])
        self.assertEqual(task["discussion"]["threadId"], before["discussion"]["threadId"])
        self.assertEqual(task["discussion"]["messages"], before["discussion"]["messages"])
        server.run_codex_structured.assert_not_called()

    def test_lark_cli_failures_are_classified_without_echoing_credentials(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        for raw, expected in (
            ("keychain Get failed: keychain not initialized", "lark_credentials_unavailable"),
            ("Please sign in", "document_login_required"),
            ("Permission denied", "document_permission_denied"),
            ("Network request timed out", "read_failed"),
        ):
            failure = server.source_reading.SourceReadError(raw + " credential-secret-123")
            with self.subTest(expected=expected), mock.patch.object(server.lark_source, "fetch_document", side_effect=failure):
                server.source_read_job(task_id)
            task = server.get_task_copy(task_id)
            self.assertEqual(task["sourceRead"]["status"], "blocked")
            self.assertEqual(task["sourceRead"]["errorCode"], expected)
            self.assertNotIn("credential-secret-123", json.dumps(task["sourceRead"], ensure_ascii=False))
            self.assertEqual(task["sessions"]["discussion"], "original-discussion-thread")
        server.run_codex_structured.assert_not_called()

    def test_lark_unavailable_stops_before_fetch_and_partial_material_cannot_proceed(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        with mock.patch.object(server, "lark_cli_status", return_value={"ready": False, "message": "测试读取通道未就绪。"}), \
                mock.patch.object(server.lark_source, "fetch_document") as fetch:
            server.source_read_job(task_id)
        fetch.assert_not_called()
        self.assertEqual(server.get_task_copy(task_id)["sourceRead"]["errorCode"], "reader_unavailable")
        material = {
            **self.document(task_id), "coverage": "partial", "missingSections": ["最后一段"],
            "rawResults": {},
        }
        with mock.patch.object(server.lark_source, "fetch_document", return_value=material):
            server.source_read_job(task_id)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["sourceRead"]["status"], "blocked")
        self.assertEqual(task["sourceRead"]["snapshot"]["coverage"], "partial")
        self.assertEqual(task["sourceRead"]["snapshot"]["missingSections"], ["最后一段"])
        server.run_codex_structured.assert_not_called()
        with self.assertRaises(server.WorkflowError):
            server.continue_from_source(task_id)

    def test_complete_host_material_is_validated_and_stored_without_codex(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        original = self.document(task_id, title="CLI 原始标题", sections=["总览", "失败处理"])
        material = {**original, "rawResults": {"document": {"ok": True}, "sheets": []}}
        with mock.patch.object(server.lark_source, "fetch_document", return_value=material):
            server.source_read_job(task_id)
        task = server.get_task_copy(task_id)
        snapshot = task["sourceRead"]["snapshot"]
        self.assertEqual(task["sourceRead"]["status"], "ready")
        self.assertEqual(snapshot["title"], original["title"])
        self.assertEqual(snapshot["body"], original["body"])
        self.assertEqual(snapshot["sections"], original["sections"])
        self.assertEqual(snapshot["missingSections"], [])
        self.assertEqual(snapshot["reader"], "lark_cli")
        self.assertEqual(snapshot["method"], "automated")
        self.assertEqual(snapshot["digest"], hashlib.sha256(original["body"].encode()).hexdigest())
        self.assertEqual(server.source_snapshot_path(task).read_text(encoding="utf-8"), original["body"])
        material_path, = (server.task_dir(task_id) / "source").glob("lark-read-*.json")
        persisted_material = json.loads(material_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted_material, material)
        self.assertEqual(material_path.stat().st_mode & 0o777, 0o600)
        server.run_codex_structured.assert_not_called()

    def test_host_partial_material_is_saved_and_blocks_without_codex(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        material = {**self.document(task_id), "coverage": "partial", "missingSections": ["正文末段"], "missingAttachments": ["表格：缺少 sheets:spreadsheet:read"], "rawResults": {}}
        with mock.patch.object(server.lark_source, "fetch_document", return_value=material):
            server.source_read_job(task_id)
        server.run_codex_structured.assert_not_called()
        task = server.get_task_copy(task_id)
        self.assertEqual(task["sourceRead"]["status"], "blocked")
        self.assertEqual(task["sourceRead"]["snapshot"]["missingAttachments"], material["missingAttachments"])
        self.assertEqual(task["sourceRead"]["errorCode"], "read_incomplete")
        self.assertEqual(task["sourceRead"]["snapshot"]["body"], material["body"])
        self.assertEqual(task["sessions"]["discussion"], "original-discussion-thread")
        with self.assertRaises(server.WorkflowError):
            server.continue_from_source(task_id)

    def test_host_unread_attachment_is_optional_and_preserved_without_codex(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        original = self.document(task_id)
        material = {**original, "missingAttachments": ["Max SDK 接入统计：未读引用文档"], "rawResults": {}}
        with mock.patch.object(server.lark_source, "fetch_document", return_value=material):
            server.source_read_job(task_id)
        task = server.get_task_copy(task_id)
        server.require_source_ready(task)
        self.assertEqual(task["sourceRead"]["status"], "ready")
        self.assertEqual(task["sourceRead"]["snapshot"]["missingAttachments"], material["missingAttachments"])
        self.assertEqual(task["sourceRead"]["snapshot"]["body"], original["body"])
        self.assertIn("Max SDK 接入统计", server.source_prompt(task))
        self.assertEqual(task["sessions"]["discussion"], "original-discussion-thread")
        server.run_codex_structured.assert_not_called()

    def test_host_credentials_failure_blocks_without_codex(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        with mock.patch.object(server.lark_source, "fetch_document", side_effect=server.source_reading.SourceReadError("keychain Get failed: keychain not initialized")):
            server.source_read_job(task_id)
        server.run_codex_structured.assert_not_called()
        self.assertEqual(server.get_task_copy(task_id)["sourceRead"]["errorCode"], "lark_credentials_unavailable")

    def test_running_source_read_can_be_cancelled_without_losing_saved_material(self) -> None:
        task_id = self.seed_source_task("lark_cli")
        snapshot = server.source_reading.validate_snapshot(
            server.get_task_copy(task_id)["source"], self.document(task_id),
            read_at="2026-09-09T12:00:00Z", method="automated",
        )
        with server.mutate_task(task_id) as task:
            server.store_source_snapshot(task, snapshot)
            task.update({"activeJob": "sourceRead", "jobState": "running"})
            task["sourceRead"]["status"] = "running"
        before = server.get_task_copy(task_id)
        process = mock.Mock()
        server.ACTIVE_PROCESSES[task_id] = process
        with mock.patch.object(server, "stop_codex_process") as stop, \
                mock.patch.object(server.threading, "Timer") as timer:
            server.cancel_task(task_id)
        stop.assert_called_once_with(process)
        timer.return_value.start.assert_called_once()
        self.assertIn(task_id, server.CANCEL_REQUESTED)
        server.source_read_job(task_id)
        task = server.get_task_copy(task_id)
        self.assertEqual(task["sourceRead"]["status"], "interrupted")
        self.assertEqual(task["sourceRead"]["errorCode"], "cancelled")
        self.assertEqual(task["sourceRead"]["snapshot"], before["sourceRead"]["snapshot"])
        self.assertEqual(task["sourceRead"]["revision"], before["sourceRead"]["revision"])
        self.assertEqual(task["discussion"], before["discussion"])
        self.assertEqual(task["sessions"]["discussion"], before["sessions"]["discussion"])
        server.run_codex_structured.assert_not_called()


if __name__ == "__main__":
    unittest.main()
