from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.js"
NODE_BIN = shutil.which("node")


@unittest.skipUnless(NODE_BIN, "Node.js is required to execute frontend regression tests")
class SourceReadUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = APP_PATH.read_text(encoding="utf-8")
        names = (
            "escapeHTML", "isLarkLink", "formatTime", "formatDateTime", "currentStageId",
            "callout", "sectionError", "eventLogDetails", "estimateProgress", "renderProgress",
            "hasSourceReadStep", "sourceReadyForDiscussion", "sourceReadDraft", "sourceReadItems",
            "captureSourceReadDraft", "confirmSourceReadCoverage", "sourceDocumentLink", "sourceSnapshotDetails", "sourceAttachmentNotice",
            "previousDiscussionDetails", "renderSourceRead", "renderDiscuss",
            "renderDiscussionContent", "questionFieldset", "staticCheck", "importSourceRead",
            "continueSourceRead", "retrySourceRead", "newSourceReadingOptions", "renderSourceInputOptions",
            "sourceConfigurationLocked", "renderSourceConfiguration", "configureSourceReading",
            "startDiscussion", "copySourceReadPrompt",
        )
        functions = []
        for name in names:
            match = re.search(rf"^  (?:async )?function {name}\([^\n]*\) \{{.*?^  \}}", source, re.MULTILINE | re.DOTALL)
            if match is None:
                raise AssertionError(f"Missing app function: {name}")
            functions.append(match.group())
        cls.functions = "\n".join(functions)

    def evaluate(self, expression: str, task: dict, setup: str = "", fields: dict | None = None):
        script = """
const input = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
let task = input.task;
const ui = { module: "flow", viewStage: "discuss", discussionNote: "", answers: {}, customAnswers: {} };
const busy = false;
const health = { readers: { chromeMcp: { ready: false, status: "unverified", automatic: false, message: "后台读取尚未验证" } } };
const sourceReadDrafts = new Map();
const localStorageWrites = [];
const localStorage = { setItem: (...args) => localStorageWrites.push(args) };
let selectedFile = null;
let selectedPlanFile = null;
const copied = [];
const copyText = async value => copied.push(value);
const fields = input.fields;
const document = { querySelector: id => fields[id.slice(1)], getElementById: id => fields[id] };
const stages = ["input", "discuss", "plan", "worktree", "execute", "verify", "commit", "bugfix", "knowledge"].map(id => ({ id }));
const requests = [];
const toasts = [];
const showToast = (...args) => toasts.push(args);
const withAction = async action => action();
const setTask = next => { task = next; };
const captureVisibleFields = () => captureSourceReadDraft();
let post = async (url, payload) => { requests.push({ url, payload }); return { task }; };
""" + self.functions + "\n" + setup + f"\n(async () => {{ process.stdout.write(JSON.stringify(await ({expression}))); }})().catch(error => {{ console.error(error); process.exitCode = 1; }});\n"
        result = subprocess.run(
            [NODE_BIN, "-e", script],
            input=json.dumps({"task": task, "fields": fields or {}}),
            text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    def task(self, status: str | None = "blocked", discussion_status: str = "ready") -> dict:
        task = {
            "id": "source-task-a", "title": "需求任务", "stage": "discuss", "maxStageIndex": 1,
            "source": {"type": "link", "reader": "chrome_mcp", "url": "https://example.feishu.cn/docx/source"},
            "activeJob": None,
            "discussion": {"status": discussion_status, "result": {"summary": "此前讨论保留", "questions": [
                {"id": "q1", "question": "此前要求重连 Chrome", "reason": "读取失败", "options": []}
            ]}, "messages": [{"note": "此前用户回复"}]},
        }
        if status is not None:
            task["sourceRead"] = {"status": status, "snapshot": None, "logs": []}
        return task

    def snapshot(self, coverage: str = "complete") -> dict:
        return {
            "title": "原文标题", "url": "https://example.feishu.cn/docx/source", "body": "# 完整正文\n规则与表格内容。",
            "readAt": "2026-09-09T12:00:00Z", "sections": ["规则"], "missingSections": [], "missingAttachments": [],
            "coverage": coverage, "reader": "chrome_mcp", "method": "desktop_import", "digest": "snapshot-a",
        }

    def assert_read_gate(self, html: str) -> None:
        self.assertNotIn('id="generatePlan"', html)
        self.assertNotIn('id="directExecute"', html)
        self.assertNotIn('id="sendDiscussionNote"', html)
        self.assertNotIn('data-question-id=', html)

    def test_legacy_link_tasks_gate_old_questions_and_retain_history_for_both_readers(self) -> None:
        for reader in ("manual_import", "chrome_mcp", "lark_cli"):
            with self.subTest(reader=reader):
                task = self.task(None)
                task["source"]["reader"] = reader
                html = self.evaluate("renderDiscuss()", task)
                self.assert_read_gate(html)
                self.assertEqual('id="sourceReadBody"' in html, reader in ("manual_import", "chrome_mcp"))
                self.assertIn("查看此前讨论记录", html)
                self.assertIn("此前用户回复", html)
                self.assertIn("此前讨论保留", html)

    def test_unready_statuses_do_not_expose_discussion_or_plan_actions(self) -> None:
        for status in ("idle", "running", "blocked", "error", "interrupted"):
            with self.subTest(status=status):
                task = self.task(status)
                html = self.evaluate("renderDiscuss()", task)
                self.assert_read_gate(html)
                self.assertNotIn('id="continueSourceRead"', html)
                if status == "running":
                    self.assertNotIn('id="sourceReadBody"', html)

    def test_partial_empty_or_missing_material_cannot_continue_even_if_status_is_ready(self) -> None:
        incomplete = [
            {"coverage": "partial"}, {"body": "  "},
            {"missingSections": ["交互规则"]},
        ]
        for update in incomplete:
            with self.subTest(update=update):
                task = self.task("ready", "idle")
                task["sourceRead"]["snapshot"] = {**self.snapshot(), **update}
                html = self.evaluate("renderDiscuss()", task)
                self.assert_read_gate(html)
                self.assertNotIn('id="continueSourceRead"', html)
                self.assertIn('id="sourceReadBody"', html)

    def test_complete_body_with_unread_attachments_can_continue_with_visible_notice(self) -> None:
        for reader in ("manual_import", "chrome_mcp", "lark_cli"):
            with self.subTest(reader=reader):
                task = self.task("ready", "idle")
                task["source"]["reader"] = reader
                task["sourceRead"]["snapshot"] = {
                    **self.snapshot(), "reader": reader,
                    "missingAttachments": ["交互图 <未读>", "内嵌表格 A", "画板 B"],
                }
                self.assertTrue(self.evaluate("sourceReadyForDiscussion()", task))
                html = self.evaluate("renderDiscuss()", task)
                self.assertIn('id="continueSourceRead"', html)
                notice = "正文已读取；以下附件/引用未读取，本次讨论仅依据已保存内容。"
                self.assertIn(notice, html)
                self.assertLess(html.index(notice), html.index('<details class="source-read-preview">'))
                self.assertIn("交互图 &lt;未读&gt;", html)
                self.assertNotIn("交互图 <未读>", html)
                self.assertIn("另 1 项", html)
                self.assertIn("附件/引用：画板 B", html)
                result = self.evaluate("continueSourceRead().then(() => ({requests, toasts}))", task)
                self.assertEqual(result["requests"][0]["url"], "/api/tasks/source-task-a/source/continue")

    def test_complete_import_shows_preview_and_explicit_continue_without_plan(self) -> None:
        task = self.task("ready", "idle")
        task["sourceRead"]["snapshot"] = self.snapshot()
        html = self.evaluate("renderDiscuss()", task)
        self.assert_read_gate(html)
        self.assertIn('id="continueSourceRead"', html)
        self.assertIn("使用材料，恢复讨论", html)
        self.assertIn("用户已确认正文和章节覆盖完整", html)
        self.assertIn("系统未重新读取网页核验", html)
        self.assertIn("完整正文", html)
        self.assertNotIn('id="sourceReadBody"', html)

    def test_missing_or_invalid_coverage_lists_do_not_satisfy_ready_gate(self) -> None:
        for field in ("missingSections", "missingAttachments"):
            for value in (None, "", {}):
                with self.subTest(field=field, value=value):
                    task = self.task("ready", "idle")
                    snapshot = self.snapshot()
                    if value is None:
                        del snapshot[field]
                    else:
                        snapshot[field] = value
                    task["sourceRead"]["snapshot"] = snapshot
                    self.assertFalse(self.evaluate("sourceReadyForDiscussion()", task))
                    html = self.evaluate("renderDiscuss()", task)
                    self.assert_read_gate(html)
                    self.assertNotIn('id="continueSourceRead"', html)

    def test_started_discussion_displays_source_and_normal_controls(self) -> None:
        task = self.task("ready")
        task["sourceRead"]["snapshot"] = self.snapshot()
        html = self.evaluate("renderDiscuss()", task)
        self.assertIn('id="generatePlan"', html)
        self.assertIn('id="retrySourceRead"', html)
        self.assertIn("本次讨论使用的需求材料", html)

    def test_started_discussion_keeps_unread_attachments_notice_visible(self) -> None:
        task = self.task("ready")
        task["sourceRead"]["snapshot"] = {**self.snapshot(), "missingAttachments": ["引用需求表"]}
        html = self.evaluate("renderDiscuss()", task)
        self.assertIn('id="generatePlan"', html)
        self.assertIn('id="sendDiscussionNote"', html)
        self.assertIn("本次讨论仅依据已保存内容", html)
        self.assertIn("引用需求表", html)
        self.assertLess(html.index("本次讨论仅依据已保存内容"), html.index('<details class="source-read-preview">'))

    def test_stale_complete_snapshot_is_only_a_preview_after_retry(self) -> None:
        task = self.task("blocked", "idle")
        task["sourceRead"]["snapshot"] = self.snapshot()
        html = self.evaluate("renderDiscuss()", task)
        self.assert_read_gate(html)
        self.assertNotIn('id="continueSourceRead"', html)
        self.assertIn("查看上次保存的材料", html)
        self.assertIn("当前材料不可用于开始讨论", html)
        self.assertFalse(self.evaluate("sourceReadDraft().complete", task))

    def test_lark_reader_exposes_retry_or_cancel_without_chrome_import_controls(self) -> None:
        for status in ("blocked", "running"):
            with self.subTest(status=status):
                task = self.task(status)
                task["source"]["reader"] = "lark_cli"
                if status == "running":
                    task["activeJob"] = "sourceRead"
                html = self.evaluate("renderDiscuss()", task)
                self.assertNotIn('id="sourceReadBody"', html)
                self.assertNotIn('id="importSourceRead"', html)
                self.assertNotIn('id="copySourceReadPrompt"', html)
                self.assertIn('id="retrySourceRead"', html)
                self.assertEqual('id="cancelSourceRead"' in html, status == "running")

    def test_background_connection_label_and_existing_thread_are_visible_before_continue(self) -> None:
        task = self.task("ready", "idle")
        task["sourceRead"]["snapshot"] = self.snapshot()
        task["discussion"] = {"status": "idle", "threadId": "existing-thread"}
        setup = 'health.codex = {backgroundConnection: {id: "api", label: "现有 NewAPI"}};'
        html = self.evaluate("renderDiscuss()", task, setup)
        self.assertIn("后续讨论使用：现有 NewAPI", html)
        self.assertIn("桌面聊天的连接选择不会改变后台讨论连接", html)
        self.assertIn("使用材料，恢复讨论", html)

    def test_snapshot_body_title_and_source_error_are_escaped(self) -> None:
        task = self.task("ready", "idle")
        task["sourceRead"]["snapshot"] = {**self.snapshot(), "title": '<img src=x onerror="bad()">', "body": "<script>bad()</script>"}
        html = self.evaluate("renderDiscuss()", task)
        self.assertNotIn("<script>", html)
        self.assertNotIn("<img src=x", html)
        self.assertIn("&lt;script&gt;bad()&lt;/script&gt;", html)
        task["sourceRead"].update(status="error", error="Auth missing: <token>", errorCode="codex_auth_missing")
        html = self.evaluate("renderDiscuss()", task)
        self.assertIn("Auth missing: &lt;token&gt;", html)
        self.assertNotIn("codex_auth_missing", html)
        self.assertNotIn("Auth missing: <token>", html)

    def test_unsafe_source_url_is_not_rendered_as_a_link(self) -> None:
        task = self.task()
        task["source"]["url"] = "javascript:bad()"
        self.assertEqual(self.evaluate("sourceDocumentLink()", task), "")

    def test_form_drafts_are_task_scoped_and_not_written_to_local_storage(self) -> None:
        fields = {
            "sourceReadTitle": {"value": "用户输入标题"}, "sourceReadBody": {"value": "本地正文草稿"},
            "sourceReadSections": {"value": "规则"}, "sourceReadMissingSections": {"value": ""},
            "sourceReadMissingAttachments": {"value": ""}, "sourceReadComplete": {"checked": True},
        }
        setup = """
captureSourceReadDraft();
const firstTask = task;
task = { ...firstTask, id: "source-task-b" };
const secondDraft = { ...sourceReadDraft() };
task = firstTask;
"""
        value = self.evaluate("({firstDraft: sourceReadDraft(), secondDraft, localStorageWrites, ui})", self.task(), setup, fields)
        self.assertEqual(value["firstDraft"]["body"], "本地正文草稿")
        self.assertTrue(value["firstDraft"]["complete"])
        self.assertEqual(value["secondDraft"]["body"], "")
        self.assertFalse(value["secondDraft"]["complete"])
        self.assertEqual(value["localStorageWrites"], [])
        self.assertNotIn("本地正文草稿", json.dumps(value["ui"], ensure_ascii=False))

    def test_import_only_saves_source_and_never_starts_discussion_or_plan(self) -> None:
        for complete in (False, True):
            with self.subTest(complete=complete):
                fields = {
                    "sourceReadTitle": {"value": " 原文标题 "}, "sourceReadBody": {"value": "原文正文"},
                    "sourceReadSections": {"value": "规则\n\n表格"}, "sourceReadMissingSections": {"value": ""},
                    "sourceReadMissingAttachments": {"value": ""}, "sourceReadComplete": {"checked": complete},
                }
                setup = """
post = async (url, payload) => {
  requests.push({url, payload});
  return {task: {...task, sourceRead: {status: payload.coverage === "complete" ? "ready" : "blocked", snapshot: {...payload, method: "desktop_import"}}, discussion: {...task.discussion, status: "idle"}}};
};
"""
                result = self.evaluate("importSourceRead().then(() => ({requests, html: renderDiscuss()}))", self.task(), setup, fields)
                self.assertEqual(len(result["requests"]), 1)
                request = result["requests"][0]
                self.assertEqual(request["url"], "/api/tasks/source-task-a/source/import")
                self.assertEqual(request["payload"]["coverage"], "complete" if complete else "partial")
                self.assertEqual(request["payload"]["sections"], ["规则", "表格"])
                self.assertEqual(request["payload"]["url"], self.task()["source"]["url"])
                self.assert_read_gate(result["html"])
                self.assertEqual('id="continueSourceRead"' in result["html"], complete)

    def test_import_confirmation_and_coverage_allow_unread_attachments(self) -> None:
        for missing_sections in ("", "交互规则"):
            with self.subTest(missing_sections=missing_sections):
                fields = {
                    "sourceReadTitle": {"value": "原文标题"}, "sourceReadBody": {"value": "已保存的正文"},
                    "sourceReadSections": {"value": "规则"}, "sourceReadMissingSections": {"value": missing_sections},
                    "sourceReadMissingAttachments": {"value": "交互图\n内嵌表格"}, "sourceReadComplete": {"checked": True},
                }
                setup = 'confirmSourceReadCoverage({currentTarget: fields.sourceReadComplete});'
                result = self.evaluate("importSourceRead().then(() => ({requests, toasts, checked: fields.sourceReadComplete.checked}))", self.task(), setup, fields)
                self.assertEqual(result["checked"], not bool(missing_sections))
                self.assertEqual(result["requests"][0]["payload"]["coverage"], "partial" if missing_sections else "complete")
                self.assertEqual(result["requests"][0]["payload"]["missingAttachments"], ["交互图", "内嵌表格"])
                if missing_sections:
                    self.assertIn("缺失正文章节", result["toasts"][0][0])

    def test_continue_requires_ready_source_and_only_calls_source_continue_endpoint(self) -> None:
        for ready in (False, True):
            with self.subTest(ready=ready):
                task = self.task("ready" if ready else "blocked", "idle")
                task["sourceRead"]["snapshot"] = self.snapshot()
                result = self.evaluate("continueSourceRead().then(() => ({requests, toasts}))", task)
                self.assertEqual(len(result["requests"]), 1 if ready else 0)
                if ready:
                    self.assertEqual(result["requests"][0]["url"], "/api/tasks/source-task-a/source/continue")
                else:
                    self.assertIn("请先保存正文并确认内容覆盖完整", result["toasts"][0][0])

    def test_new_link_defaults_follow_project_without_mutating_selection(self) -> None:
        setup = """
ui.sourceReader = "auto";
ui.attachmentPolicy = "";
ui.sourceUrl = "https://example.org/requirements";
health.sourceReading = {defaultReader: "manual_import", attachmentPolicy: "required"};
const first = newSourceReadingOptions();
health.sourceReading = {defaultReader: "auto", attachmentPolicy: "optional"};
const second = newSourceReadingOptions();
ui.sourceUrl = "https://example.feishu.cn/docx/source";
const lark = newSourceReadingOptions();
"""
        result = self.evaluate("({first, second, lark, requested: ui.sourceReader, policy: ui.attachmentPolicy})", self.task(), setup)
        self.assertEqual(result["first"], {"reader": "manual_import", "attachmentPolicy": "required"})
        self.assertEqual(result["second"], {"reader": "codex_read_only", "attachmentPolicy": "optional"})
        self.assertEqual(result["lark"], {"reader": "manual_import", "attachmentPolicy": "optional"})
        self.assertEqual((result["requested"], result["policy"]), ("auto", ""))

    def test_source_options_restrict_capabilities_and_keep_manual_available(self) -> None:
        scenarios = (
            ("https://example.org/doc", "lark_cli", "optional", True, "manual_import"),
            ("https://example.feishu.cn/docx/a", "lark_cli", "optional", False, "lark_cli"),
            ("https://example.feishu.cn/docx/a", "lark_cli", "optional", True, "lark_cli"),
            ("https://feishu.cn.attacker.org/doc", "lark_cli", "optional", True, "manual_import"),
            ("ftp://example.feishu.cn/docx/a", "lark_cli", "optional", True, "manual_import"),
            ("https://example.feishu.cn/docx/a", "codex_read_only", "optional", True, "manual_import"),
            ("https://example.org/doc", "codex_read_only", "required", True, "manual_import"),
            ("https://example.org/doc", "manual_import", "optional", False, "manual_import"),
        )
        for url, requested, policy, ready, expected in scenarios:
            with self.subTest(url=url, requested=requested, policy=policy, ready=ready):
                setup = f"Object.assign(ui, {{sourceUrl: {json.dumps(url)}, sourceReader: {json.dumps(requested)}, attachmentPolicy: {json.dumps(policy)}}}); health.readers.larkCli = {{ready: {json.dumps(ready)}}};"
                result = self.evaluate("({options: newSourceReadingOptions(), html: renderSourceInputOptions()})", self.task(), setup)
                self.assertEqual(result["options"]["reader"], expected)
                self.assertIn('value="manual_import"', result["html"])
                self.assertIn("无需安装指定浏览器或工具", result["html"])
                self.assertNotIn("Agent Skills", result["html"])
                if policy == "required":
                    self.assertIn("附件必读时需先保存完整材料", result["html"])

    def test_unavailable_lark_preserves_project_default_or_explicit_selection(self) -> None:
        for default_reader, selected_reader, expected in (
            ("lark_cli", "auto", "lark_cli"),
            ("manual_import", "lark_cli", "lark_cli"),
            ("lark_cli", "manual_import", "manual_import"),
        ):
            with self.subTest(default_reader=default_reader, selected_reader=selected_reader):
                setup = f"""
Object.assign(ui, {{title: "飞书需求", intakeMode: "new", workflowMode: "standard", sourceType: "link", sourceUrl: "https://example.feishu.cn/docx/a", sourceReader: {json.dumps(selected_reader)}, attachmentPolicy: "", sourceText: "", baseBranch: "main"}});
health.sourceReading = {{defaultReader: {json.dumps(default_reader)}, attachmentPolicy: "optional"}};
health.readers.larkCli = {{ready: false, message: "CLI 认证暂不可用"}};
post = async (url, payload) => {{
  requests.push({{url, payload}});
  return {{task: {{...task, source: {{...task.source, reader: payload.sourceReader}}, sourceRead: {{status: "blocked"}}}}}};
}};
"""
                result = self.evaluate("startDiscussion().then(() => ({requests, options: newSourceReadingOptions(), html: renderSourceInputOptions(), toasts}))", self.task(), setup)
                self.assertEqual(result["options"]["reader"], expected)
                self.assertEqual(result["requests"][0]["payload"]["sourceReader"], expected)
                if expected == "lark_cli":
                    self.assertIn('data-source-reader="lark_cli" checked disabled', result["html"])
                    self.assertIn("已保留此读取方式", result["html"])
                    self.assertIn("保留 Lark CLI 读取方式", result["toasts"][0][0])
                    self.assertNotIn("已启动", result["toasts"][0][0])

    def test_create_link_sends_effective_reader_and_policy_without_legacy_lark_field(self) -> None:
        setup = """
Object.assign(ui, {title: "通用需求", intakeMode: "new", workflowMode: "standard", sourceType: "link", sourceUrl: "https://example.org/doc", sourceReader: "auto", attachmentPolicy: "", sourceText: "", baseBranch: "main"});
health.sourceReading = {defaultReader: "manual_import", attachmentPolicy: "required"};
"""
        result = self.evaluate("startDiscussion().then(() => requests)", self.task(), setup)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], "/api/tasks")
        self.assertEqual(result[0]["payload"]["sourceReader"], "manual_import")
        self.assertEqual(result[0]["payload"]["attachmentPolicy"], "required")
        self.assertNotIn("larkReader", result[0]["payload"])

    def test_required_attachments_block_discussion_without_changing_body_coverage(self) -> None:
        task = self.task("ready", "idle")
        task["source"].update(reader="manual_import", attachmentPolicy="required")
        task["sourceRead"]["snapshot"] = {**self.snapshot(), "missingAttachments": ["流程图"]}
        result = self.evaluate("continueSourceRead().then(() => ({ready: sourceReadyForDiscussion(), html: renderDiscuss(), requests, toasts}))", task)
        self.assertFalse(result["ready"])
        self.assertEqual(result["requests"], [])
        self.assertIn("必读附件", result["toasts"][0][0])
        self.assertIn("以下附件/引用必读", result["html"])
        self.assertIn("正文覆盖单独判断", result["html"])
        self.assertNotIn('id="continueSourceRead"', result["html"])
        self.assertNotIn("本次讨论仅依据已保存内容", result["html"])
        task["sourceRead"]["snapshot"]["missingAttachments"] = []
        self.assertTrue(self.evaluate("sourceReadyForDiscussion()", task))

    def test_required_attachment_import_keeps_complete_body_and_separate_missing_list(self) -> None:
        task = self.task()
        task["source"].update(reader="manual_import", attachmentPolicy="required")
        fields = {
            "sourceReadTitle": {"value": "原文标题"}, "sourceReadBody": {"value": "已保存的完整正文"},
            "sourceReadSections": {"value": "规则"}, "sourceReadMissingSections": {"value": ""},
            "sourceReadMissingAttachments": {"value": "流程图"}, "sourceReadComplete": {"checked": True},
        }
        result = self.evaluate("importSourceRead().then(() => ({requests, checked: fields.sourceReadComplete.checked}))", task,
                               "confirmSourceReadCoverage({currentTarget: fields.sourceReadComplete});", fields)
        self.assertTrue(result["checked"])
        self.assertEqual(result["requests"][0]["payload"]["coverage"], "complete")
        self.assertEqual(result["requests"][0]["payload"]["missingSections"], [])
        self.assertEqual(result["requests"][0]["payload"]["missingAttachments"], ["流程图"])

    def test_configure_reader_posts_configuration_only_and_clears_old_form_assertion(self) -> None:
        task = self.task("ready", "idle")
        task["sourceRead"]["snapshot"] = self.snapshot()
        fields = {"sourceConfigReader": {"value": "manual_import"}, "sourceConfigAttachmentPolicy": {"value": "required"}}
        setup = """
sourceReadDraft().complete = true;
post = async (url, payload) => {
  requests.push({url, payload});
  return {task: {...task, source: {...task.source, ...payload}, sourceRead: {...task.sourceRead, status: "blocked"}}};
};
"""
        result = self.evaluate("configureSourceReading().then(() => ({requests, complete: sourceReadDraft().complete}))", task, setup, fields)
        self.assertEqual(result["requests"], [{"url": "/api/tasks/source-task-a/source/configure", "payload": {"reader": "manual_import", "attachmentPolicy": "required"}}])
        self.assertFalse(result["complete"])

    def test_configuration_locked_during_jobs_archive_or_stage_history(self) -> None:
        fields = {"sourceConfigReader": {"value": "manual_import"}, "sourceConfigAttachmentPolicy": {"value": "required"}}
        for update in ({"activeJob": "ask"}, {"archivedAt": "2026-09-15"}, {"stage": "plan"}):
            with self.subTest(update=update):
                task = {**self.task(), **update}
                result = self.evaluate("configureSourceReading().then(() => ({requests, html: renderSourceConfiguration()}))", task, fields=fields)
                self.assertEqual(result["requests"], [])
                self.assertIn('id="configureSourceReading" type="button" disabled', result["html"])
                self.assertIn('id="sourceConfigReader" disabled', result["html"])

    def test_existing_direct_link_can_enter_import_step_without_chrome_requirement(self) -> None:
        task = self.task(None)
        task["source"].update(reader="codex_read_only", url="https://example.org/req")
        html = self.evaluate("renderDiscuss()", task)
        self.assertIn('id="configureSourceReading"', html)
        self.assertIn("保存设置后将进入独立材料读取步骤", html)
        self.assertNotIn('id="sourceReadBody"', html)
        task["source"].update(reader="manual_import")
        html = self.evaluate("renderDiscuss()", task)
        self.assertIn('id="sourceReadBody"', html)
        self.assertIn("不要求特定浏览器或工具", html)
        self.assertNotIn("后台读取尚未验证", html)

    def test_refresh_required_prevents_reusing_old_ready_snapshot(self) -> None:
        task = self.task("ready", "idle")
        task["sourceRead"].update(snapshot=self.snapshot(), refreshRequired=True)
        self.assertFalse(self.evaluate("sourceReadyForDiscussion()", task))
        html = self.evaluate("renderDiscuss()", task)
        self.assertNotIn('id="continueSourceRead"', html)
        self.assertIn("查看上次保存的材料", html)

    def test_configure_unavailable_lark_is_allowed_without_starting_read(self) -> None:
        task = self.task()
        task["source"]["reader"] = "lark_cli"
        fields = {"sourceConfigReader": {"value": "lark_cli"}, "sourceConfigAttachmentPolicy": {"value": "required"}}
        result = self.evaluate("configureSourceReading().then(() => ({requests, html: renderSourceConfiguration()}))", task, fields=fields)
        self.assertEqual(len(result["requests"]), 1)
        self.assertEqual(result["requests"][0]["url"], "/api/tasks/source-task-a/source/configure")
        self.assertIn("读取前需配置", result["html"])
        self.assertNotIn('value="lark_cli" selected disabled', result["html"])

    def test_policy_configuration_keeps_unsaved_body_draft(self) -> None:
        fields = {"sourceConfigReader": {"value": "manual_import"}, "sourceConfigAttachmentPolicy": {"value": "required"}}
        setup = 'Object.assign(sourceReadDraft(), {body: "尚未保存的手工修订", complete: true});'
        result = self.evaluate("configureSourceReading().then(() => sourceReadDraft())", self.task(), setup, fields)
        self.assertEqual(result["body"], "尚未保存的手工修订")
        self.assertFalse(result["complete"])

    def test_ready_configuration_does_not_capture_absent_import_form(self) -> None:
        task = self.task("ready", "idle")
        task["sourceRead"]["snapshot"] = self.snapshot()
        fields = {"sourceConfigReader": {"value": "manual_import"}, "sourceConfigAttachmentPolicy": {"value": "required"}}
        setup = 'Object.assign(sourceReadDraft(), {title: "草稿标题", body: "未保存正文", sections: "完整章节", missingAttachments: "草稿附件", complete: true});'
        result = self.evaluate("configureSourceReading().then(() => ({draft: sourceReadDraft(), snapshot: task.sourceRead.snapshot}))", task, setup, fields)
        self.assertEqual(result["draft"]["title"], "草稿标题")
        self.assertEqual(result["draft"]["body"], "未保存正文")
        self.assertEqual(result["draft"]["sections"], "完整章节")
        self.assertEqual(result["draft"]["missingAttachments"], "草稿附件")
        self.assertEqual(result["snapshot"]["body"], self.snapshot()["body"])

    def test_read_prompt_follows_policy_and_treats_chrome_as_optional(self) -> None:
        for policy in ("optional", "required"):
            with self.subTest(policy=policy):
                task = self.task()
                task["source"]["attachmentPolicy"] = policy
                result = self.evaluate("copySourceReadPrompt().then(() => copied)", task)
                self.assertIn("Chrome 工具只是可选方式", result[0])
                self.assertIn("缺失正文章节与未读附件必须分开记录", result[0])
                self.assertIn("本任务要求附件必读" if policy == "required" else "附件可选", result[0])
                self.assertNotIn("请先检查 Chrome 通道", result[0])


if __name__ == "__main__":
    unittest.main()
