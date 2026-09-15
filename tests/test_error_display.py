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
class ErrorDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = APP_PATH.read_text(encoding="utf-8")
        names = (
            "escapeHTML", "formatTime", "currentStageId", "callout", "sectionError",
            "eventLogDetails", "hasSourceReadStep", "sourceReadyForDiscussion",
            "renderDiscuss", "renderDiscussionContent", "estimateProgress", "renderProgress",
            "renderSourceConfiguration", "sourceConfigurationLocked", "isLarkLink",
        )
        functions = []
        for name in names:
            match = re.search(rf"^  function {name}\([^\n]*\) \{{.*?^  \}}", source, re.MULTILINE | re.DOTALL)
            if match is None:
                raise AssertionError(f"Missing app function: {name}")
            functions.append(match.group())
        cls.functions = "\n".join(functions)

    def render(self, expression: str, task: dict, module: str = "flow", stage: str = "discuss") -> str:
        script = """
const input = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
const task = input.task;
const ui = input.ui;
const busy = false;
const stages = ["input", "discuss", "plan", "worktree", "execute", "verify", "commit", "bugfix", "knowledge"].map(id => ({ id }));
""" + self.functions + f"\nprocess.stdout.write(JSON.stringify({expression}));\n"
        result = subprocess.run(
            [NODE_BIN, "-e", script],
            input=json.dumps({"task": {"maxStageIndex": 8, **task}, "ui": {"module": module, "viewStage": stage}}),
            text=True, capture_output=True, check=True,
        )
        return json.loads(result.stdout)

    def test_failed_discussion_keeps_logs_after_active_job_clears_and_sorts_by_time(self) -> None:
        task = {
            "activeJob": None,
            "events": [{"time": "2026-09-08T11:13:02+08:00", "message": "Failure recorded"}],
            "discussion": {"logs": [
                {"time": "2026-09-08T11:13:00+08:00", "message": "First event"},
                {"time": "2026-09-08T03:13:01Z", "message": "Missing environment variable"},
            ]},
        }
        html = self.render("eventLogDetails()", task)
        self.assertLess(html.index("Failure recorded"), html.index("Missing environment variable"))
        self.assertLess(html.index("Missing environment variable"), html.index("First event"))

    def test_logs_follow_viewed_stage_and_module_while_other_job_runs(self) -> None:
        task = {"activeJob": "ask"}
        for name in ("discussion", "plan", "worktree", "execution", "ask", "knowledge"):
            task[name] = {"logs": [{"message": f"{name} detail"}]}
        for module, stage, selected in (
            ("flow", "discuss", "discussion"), ("flow", "plan", "plan"),
            ("flow", "worktree", "worktree"), ("flow", "execute", "execution"),
            ("flow", "verify", "execution"), ("flow", "bugfix", "execution"),
            ("flow", "knowledge", "knowledge"), ("ask", "execute", "ask"),
            ("knowledge-center", "execute", "knowledge"),
        ):
            with self.subTest(module=module, stage=stage):
                html = self.render("eventLogDetails()", task, module, stage)
                self.assertIn(f"{selected} detail", html)
                for name in task.keys() - {"activeJob", selected}:
                    self.assertNotIn(f"{name} detail", html)

    def test_latest_error_is_kept_when_more_than_thirty_logs_share_a_timestamp(self) -> None:
        timestamp = "2026-09-08T11:13:01+08:00"
        logs = [{"time": timestamp, "message": f"Older progress {index:02d}"} for index in range(35)]
        logs.append({"time": timestamp, "kind": "error", "message": "Latest concrete failure"})
        task = {"activeJob": None, "discussion": {"logs": logs}}

        html = self.render("eventLogDetails()", task)

        self.assertEqual(html.count('class="event-row"'), 30)
        self.assertIn("Latest concrete failure", html)
        self.assertLess(html.index("Latest concrete failure"), html.index("Older progress 34"))
        self.assertNotIn("Older progress 00", html)

    def test_running_plan_shown_on_discussion_page_keeps_plan_logs(self) -> None:
        task = {
            "activeJob": "plan",
            "plan": {"status": "running", "logs": [{"message": "Plan detail"}]},
            "discussion": {"status": "ready", "logs": [{"message": "Old discussion detail"}]},
        }
        html = self.render("renderDiscuss()", task)
        details = html.split("<details>", 1)[1]
        self.assertIn("Plan detail", details)
        self.assertNotIn("Old discussion detail", details)

    def test_legacy_exit_code_uses_latest_actionable_error_and_escapes_html(self) -> None:
        task = {"activeJob": None, "discussion": {
            "status": "error", "error": "codex exec 退出码 1",
            "logs": [
                {"kind": "error", "message": "Earlier error"},
                {"kind": "error", "message": "Missing environment variable: <CODEX_NEWAPI_KEY>."},
                {"kind": "error", "message": "Codex 返回失败事件。"},
                {"kind": "info", "message": "Unrelated progress"},
            ],
        }}
        html = self.render("renderDiscuss()", task).split("</section>", 1)[0]
        self.assertIn("Missing environment variable: &lt;CODEX_NEWAPI_KEY&gt;.", html)
        self.assertNotIn("<CODEX_NEWAPI_KEY>", html)
        self.assertNotIn("Earlier error", html)
        self.assertNotIn("codex exec 退出码", html)

    def test_concrete_error_is_preserved_and_placeholder_logs_do_not_replace_exit_code(self) -> None:
        for error, logs in (
            ("Current specific failure", [{"kind": "error", "message": "Earlier specific failure"}]),
            ("codex exec 退出码 2", [{"kind": "error", "message": "Codex 返回失败事件。"}]),
            ("codex exec 退出码 1", [{"kind": "info", "message": "Reading facts"}]),
        ):
            with self.subTest(error=error, logs=logs):
                task = {"discussion": {"error": error, "logs": logs}}
                self.assertEqual(self.render("sectionError(task.discussion)", task), error)


if __name__ == "__main__":
    unittest.main()
