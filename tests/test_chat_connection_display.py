from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "app.js"
NODE_BIN = shutil.which("node")
DEFAULT_CONNECTIONS = [{"id": "default", "label": "默认 Codex 环境", "available": True, "reason": ""}]
TEAM_CONNECTIONS = [
    {"id": "team-a", "label": "研发团队", "available": True, "reason": ""},
    {"id": "personal", "label": "个人账号", "available": True, "reason": ""},
]


@unittest.skipUnless(NODE_BIN, "Node.js is required to execute frontend regression tests")
class ChatConnectionDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = APP_PATH.read_text(encoding="utf-8")
        parts = []
        for name in ("defaultUi", "taskViewKeys"):
            match = re.search(rf"^  const {name} = .*?^  [\}}\]];", source, re.MULTILINE | re.DOTALL)
            if match is None:
                raise AssertionError(f"Missing app constant: {name}")
            parts.append(match.group())
        for name in (
            "escapeHTML", "codexAppConnections", "codexAppConnectionLabel", "codexAppConnectionsError",
            "codexAppConnectionIssue", "selectedCodexAppConnectionMode", "refreshedCodexAppConnectionMode",
            "selectCodexAppConnectionMode", "renderCodexAppPanel", "openCodexApp",
            "newCodexAppChat", "withAction", "taskViewSnapshot", "uiStorageKey", "loadUi",
            "saveUi", "activateTaskView", "captureVisibleFields",
        ):
            match = re.search(rf"^  (?:async )?function {name}\([^\n]*\) \{{.*?^  \}}", source, re.MULTILINE | re.DOTALL)
            if match is None:
                raise AssertionError(f"Missing app function: {name}")
            parts.append(match.group())
        for element, event in (("codexAppConnectionMode", "change"), ("resetCodexAppConnectionMode", "click")):
            selector_handler = re.search(
                rf'^    on\("{element}", "{event}", .*?^    \}}\);', source, re.MULTILINE | re.DOTALL,
            )
            if selector_handler is None:
                raise AssertionError(f"Missing connection handler: {element}")
            parts.append(selector_handler.group())
        cls.source = "\n".join(parts)

    def run_ui(self, body: str, **inputs) -> dict:
        inputs.setdefault("connections", DEFAULT_CONNECTIONS)
        script = """
const input = JSON.parse(require("node:fs").readFileSync(0, "utf8"));
const calls = [], toasts = [], prompts = [];
const handlers = new Map();
const on = (id, event, handler) => handlers.set(`${id}:${event}`, handler);
const storage = new Map();
const localStorage = { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) };
const UI_KEY_BASE = "test-ui";
let currentProjectId = "project";
let task = { id: "task-1", ...(input.task || {}) };
let busy = input.busy || false;
let refreshCount = 0;
const health = { features: input.features || { codexAppLink: true, codexConnectionModes: false }, paths: { repo: "/test/repo" }, codex: { desktopConnectionMode: input.desktopMode, desktopConnectionError: input.connectionError } };
if (!input.oldWorker) health.codex.desktopConnections = input.connections;
const document = { querySelector: selector => selector === "#codexAppConnectionMode" && input.fieldValue !== undefined ? { value: input.fieldValue } : null };
const window = {
  confirm: prompt => { prompts.push(prompt); return input.confirm !== false; },
  location: { set href(value) { throw new Error("Generic protocol navigation is forbidden"); } },
};
function render() {}
function showToast(message, error = false) { toasts.push({ message, error }); }
function setTask(next) { task = next; }
async function refreshSessionToken() {
  refreshCount++;
  if (input.refreshFails) return false;
  if (input.refreshedDesktopMode !== undefined) health.codex.desktopConnectionMode = input.refreshedDesktopMode;
  if (input.refreshedConnections !== undefined) health.codex.desktopConnections = input.refreshedConnections;
  if (input.refreshedConnectionError !== undefined) health.codex.desktopConnectionError = input.refreshedConnectionError;
  return true;
}
async function post(path, request) {
  calls.push({ path, request });
  return input.response || {
    desktopOpened: true,
    task: { ...task, codexApp: { threadId: "manual-thread", connectionMode: request.connectionMode || task.codexApp?.connectionMode || "default" } },
  };
}
""" + self.source + "\nlet ui = { ...structuredClone(defaultUi), ...(input.ui || {}) };\n" + """
(async () => {
  const value = await (async () => {
""" + body + """
  })();
  process.stdout.write(JSON.stringify({ value, calls, toasts, prompts, ui, task, refreshCount }));
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        result = subprocess.run([NODE_BIN, "-e", script], input=json.dumps(inputs), text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def assert_button_enabled(self, html: str, button_id: str, enabled: bool = True) -> None:
        button = re.search(rf'<button[^>]*id="{button_id}"[^>]*>', html)
        self.assertIsNotNone(button)
        self.assertEqual(" disabled" not in button.group(), enabled)

    def test_single_default_environment_opens_without_selector_or_restart_warning(self) -> None:
        for features in ({"codexAppLink": True}, {"codexAppLink": True, "codexConnectionModes": False}):
            with self.subTest(features=features):
                html = self.run_ui("return renderCodexAppPanel();", features=features)["value"]
                self.assertNotIn("<select", html)
                self.assertNotIn("重启", html)
                self.assertIn("默认 Codex 环境", html)
                self.assert_button_enabled(html, "openCodexApp")
                for action in ("openCodexApp", "newCodexAppChat"):
                    result = self.run_ui(f"await {action}();", features=features)
                    self.assertEqual(result["calls"][0]["request"], {"connectionMode": "default"})
                    self.assertFalse(any(item["error"] for item in result["toasts"]))

    def test_single_custom_connection_needs_no_selector(self) -> None:
        for connection in (TEAM_CONNECTIONS[0], {"id": "account", "label": "账号版", "available": True, "reason": ""}):
            with self.subTest(connection=connection["id"]):
                html = self.run_ui("return renderCodexAppPanel();", connections=[connection])["value"]
                self.assertNotIn("<select", html)
                self.assertIn(connection["label"], html)
                self.assert_button_enabled(html, "openCodexApp")
                result = self.run_ui("await openCodexApp();", connections=[connection])
                self.assertEqual(result["calls"][0]["request"], {"connectionMode": connection["id"]})

    def test_multiple_connections_use_dynamic_labels_and_desktop_default(self) -> None:
        html = self.run_ui("return renderCodexAppPanel();", connections=TEAM_CONNECTIONS, desktopMode="personal")["value"]
        self.assertIn('option value="personal" selected', html)
        self.assertIn('option value="team-a"', html)
        self.assertIn("研发团队", html)
        self.assertIn("个人账号", html)
        self.assertNotIn("API 登录版", html)
        self.assertNotIn("登录方式", html)
        for action in ("openCodexApp", "newCodexAppChat"):
            with self.subTest(action=action):
                result = self.run_ui(f"await {action}();", connections=TEAM_CONNECTIONS, desktopMode="personal")
                self.assertEqual(result["calls"][0]["request"], {"connectionMode": "personal"})

    def test_auto_selection_uses_default_then_first_available(self) -> None:
        for connections, expected in ((TEAM_CONNECTIONS + DEFAULT_CONNECTIONS, "default"), (TEAM_CONNECTIONS, "team-a")):
            result = self.run_ui("await openCodexApp();", connections=connections)
            self.assertEqual(result["calls"][0]["request"], {"connectionMode": expected})

    def test_invalid_configured_desktop_default_requires_reselection(self) -> None:
        connections = TEAM_CONNECTIONS + [{"id": "offline", "label": "离线环境", "available": False, "reason": "目录不存在"}]
        for mode in ("removed", "offline"):
            inputs = {"connections": connections, "desktopMode": mode}
            html = self.run_ui("return renderCodexAppPanel();", **inputs)["value"]
            self.assert_button_enabled(html, "openCodexApp", False)
            self.assertIn("重新选择", html)
            for action in ("openCodexApp", "newCodexAppChat"):
                result = self.run_ui(f"await {action}();", **inputs)
                self.assertFalse(result["calls"])
                self.assertFalse(result["prompts"])
                self.assertIn("重新选择", result["toasts"][-1]["message"])

    def test_explicit_selection_survives_refresh_of_desktop_default(self) -> None:
        result = self.run_ui("await newCodexAppChat();", connections=TEAM_CONNECTIONS, desktopMode="team-a", refreshedDesktopMode="personal", ui={"codexAppConnectionMode": "team-a"})
        self.assertEqual(result["calls"][0]["request"], {"connectionMode": "team-a"})
        self.assertEqual(result["refreshCount"], 1)

    def test_default_mode_refreshes_after_switching_desktop_without_reloading_page(self) -> None:
        for action in ("openCodexApp", "newCodexAppChat"):
            with self.subTest(action=action):
                result = self.run_ui(f"await {action}();", connections=TEAM_CONNECTIONS, desktopMode="team-a", refreshedDesktopMode="personal")
                self.assertEqual(result["calls"][0]["request"], {"connectionMode": "personal"})
                if action == "newCodexAppChat":
                    self.assertIn("个人账号", result["prompts"][0])

    def test_default_mode_refresh_failure_stops_creation(self) -> None:
        for action in ("openCodexApp", "newCodexAppChat"):
            result = self.run_ui(f"await {action}();", refreshFails=True)
            self.assertFalse(result["calls"])
            self.assertFalse(result["prompts"])
            self.assertTrue(result["toasts"][-1]["error"])

    def test_binding_label_uses_saved_mode_while_selector_controls_next_chat(self) -> None:
        for saved_mode, expected_label in (("personal", "个人账号"), ("team-a", "研发团队"), (None, "待识别")):
            with self.subTest(mode=saved_mode):
                app = {"threadId": "existing-thread"}
                if saved_mode:
                    app["connectionMode"] = saved_mode
                html = self.run_ui("return renderCodexAppPanel();", connections=TEAM_CONNECTIONS, task={"codexApp": app}, ui={"codexAppConnectionMode": "team-a"})["value"]
                self.assertIn(f"连接 <strong>{expected_label}</strong>", html)
                self.assertIn("新聊天连接", html)
                self.assertIn('option value="team-a" selected', html)

    def test_selector_is_disabled_during_work_and_absent_for_archived_tasks(self) -> None:
        html = self.run_ui("return renderCodexAppPanel();", connections=TEAM_CONNECTIONS, task={"activeJob": "discussion"})["value"]
        self.assertIn('select id="codexAppConnectionMode" disabled', html)
        archived = self.run_ui("return renderCodexAppPanel();", connections=TEAM_CONNECTIONS, task={"archivedAt": "2026-09-08"})["value"]
        self.assertNotIn('select id="codexAppConnectionMode"', archived)

    def test_old_worker_missing_connection_list_disables_open_and_new(self) -> None:
        for features in ({"codexAppLink": True}, {"codexAppLink": True, "codexConnectionModes": False}):
            for binding in ({}, {"codexApp": {"threadId": "existing-thread"}}):
                with self.subTest(features=features, binding=binding):
                    html = self.run_ui("return renderCodexAppPanel();", task=binding, features=features, oldWorker=True)["value"]
                    self.assert_button_enabled(html, "openCodexApp", False)
                    if binding:
                        self.assert_button_enabled(html, "newCodexAppChat", False)
                    self.assertIn("本地服务需重启", html)
                    for action in ("openCodexApp", "newCodexAppChat"):
                        result = self.run_ui(f"await {action}();", task=binding, features=features, oldWorker=True)
                        self.assertEqual(result["calls"], [])
                        self.assertEqual(result["prompts"], [])
                        self.assertIn("本地服务需重启", result["toasts"][-1]["message"])

    def test_invalid_configuration_shows_error_and_blocks_requests(self) -> None:
        for connections in ([], [{"id": "team-a", "label": "研发团队", "available": False, "reason": "连接目录不存在"}]):
            with self.subTest(connections=connections):
                inputs = {"connections": connections, "connectionError": "连接配置无效"}
                html = self.run_ui("return renderCodexAppPanel();", **inputs)["value"]
                self.assertIn("连接配置无效", html)
                self.assertNotIn("重启", html)
                self.assert_button_enabled(html, "openCodexApp", False)
                if connections:
                    self.assertIn("连接目录不存在", html)
                for action in ("openCodexApp", "newCodexAppChat"):
                    result = self.run_ui(f"await {action}();", **inputs)
                    self.assertFalse(result["calls"])
                    self.assertEqual(result["toasts"][-1]["message"], "连接配置无效")

    def test_unavailable_options_remain_visible_with_reason_and_cannot_be_selected(self) -> None:
        connections = [TEAM_CONNECTIONS[0], {"id": "offline", "label": "离线环境", "available": False, "reason": "启动器不存在"}]
        html = self.run_ui("return renderCodexAppPanel();", connections=connections)["value"]
        self.assertRegex(html, r'<option value="offline"[^>]* disabled>')
        self.assertIn("启动器不存在", html)
        self.assert_button_enabled(html, "openCodexApp")
        result = self.run_ui('handlers.get("codexAppConnectionMode:change")({ target: { value: "offline" } });', connections=connections)
        self.assertEqual(result["ui"]["codexAppConnectionMode"], "")
        self.assertTrue(result["toasts"][-1]["error"])

    def test_removed_or_unavailable_explicit_selection_requires_reselection(self) -> None:
        connections = TEAM_CONNECTIONS + [{"id": "offline", "label": "离线环境", "available": False, "reason": "目录不存在"}]
        for mode in ("removed", "offline"):
            inputs = {"connections": connections, "ui": {"codexAppConnectionMode": mode}}
            html = self.run_ui("return renderCodexAppPanel();", **inputs)["value"]
            self.assertIn("请重新选择连接", html)
            self.assert_button_enabled(html, "openCodexApp", False)
            for action in ("openCodexApp", "newCodexAppChat"):
                result = self.run_ui(f"await {action}();", **inputs)
                self.assertFalse(result["calls"])
                self.assertFalse(result["prompts"])
                self.assertEqual(result["ui"]["codexAppConnectionMode"], mode)
                self.assertIn("重新选择", result["toasts"][-1]["message"])

    def test_selection_removed_during_health_refresh_never_silently_falls_back(self) -> None:
        for refreshed in ([TEAM_CONNECTIONS[1]], [{**TEAM_CONNECTIONS[0], "available": False, "reason": "目录不存在"}, TEAM_CONNECTIONS[1]]):
            result = self.run_ui("await newCodexAppChat();", connections=TEAM_CONNECTIONS, ui={"codexAppConnectionMode": "team-a"}, refreshedConnections=refreshed)
            self.assertFalse(result["calls"])
            self.assertFalse(result["prompts"])
            self.assertIn("重新选择", result["toasts"][-1]["message"])

    def test_removed_selection_can_be_replaced_with_single_available_connection(self) -> None:
        html = self.run_ui("return renderCodexAppPanel();", ui={"codexAppConnectionMode": "removed"})["value"]
        self.assertNotIn("<select", html)
        self.assertIn("使用此连接", html)
        self.assert_button_enabled(html, "openCodexApp", False)
        result = self.run_ui('handlers.get("resetCodexAppConnectionMode:click")(); await openCodexApp();', ui={"codexAppConnectionMode": "removed"})
        self.assertEqual(result["ui"]["codexAppConnectionMode"], "default")
        self.assertEqual(result["calls"][0]["request"], {"connectionMode": "default"})

    def test_missing_bound_connection_blocks_only_open_and_preserves_new_chat_route(self) -> None:
        binding = {"codexApp": {"threadId": "old-thread", "connectionMode": "removed"}}
        html = self.run_ui("return renderCodexAppPanel();", task=binding)["value"]
        self.assertIn("未配置", html)
        self.assertNotIn("重启", html)
        self.assert_button_enabled(html, "openCodexApp", False)
        self.assert_button_enabled(html, "newCodexAppChat")
        self.assert_button_enabled(html, "disconnectCodexApp")
        opened = self.run_ui("await openCodexApp();", task=binding)
        self.assertFalse(opened["calls"])
        created = self.run_ui("await newCodexAppChat();", task=binding)
        self.assertEqual(created["calls"][0]["request"], {"connectionMode": "default"})

    def test_valid_binding_opens_even_with_invalid_next_chat_selection(self) -> None:
        inputs = {"task": {"codexApp": {"threadId": "existing", "connectionMode": "default"}}, "ui": {"codexAppConnectionMode": "removed"}}
        html = self.run_ui("return renderCodexAppPanel();", **inputs)["value"]
        self.assert_button_enabled(html, "openCodexApp")
        self.assert_button_enabled(html, "newCodexAppChat", False)
        result = self.run_ui("await openCodexApp();", **inputs)
        self.assertEqual(result["calls"][0]["request"], {})

    def test_binding_removed_during_refresh_cannot_open_through_a_different_connection(self) -> None:
        result = self.run_ui(
            "await openCodexApp();", connections=TEAM_CONNECTIONS,
            task={"codexApp": {"threadId": "existing", "connectionMode": "team-a"}},
            refreshedConnections=[TEAM_CONNECTIONS[1]], refreshedDesktopMode="personal",
        )
        self.assertFalse(result["calls"])
        self.assertIn("team-a", result["toasts"][-1]["message"])
        self.assertEqual(result["task"]["codexApp"]["connectionMode"], "team-a")

    def test_configuration_error_discovered_during_refresh_blocks_creation(self) -> None:
        for action in ("openCodexApp", "newCodexAppChat"):
            result = self.run_ui(f"await {action}();", refreshedConnections=[], refreshedConnectionError="连接配置无法读取")
            self.assertFalse(result["calls"])
            self.assertFalse(result["prompts"])
            self.assertEqual(result["toasts"][-1]["message"], "连接配置无法读取")

    def test_opening_unbound_chat_sends_selected_mode_and_uses_backend_desktop_open(self) -> None:
        for mode in ("team-a", "personal"):
            with self.subTest(mode=mode):
                result = self.run_ui("await openCodexApp();", connections=TEAM_CONNECTIONS, ui={"codexAppConnectionMode": mode})
                self.assertEqual(result["calls"], [{"path": "/api/tasks/task-1/app/open", "request": {"connectionMode": mode}}])
                self.assertTrue(result["toasts"])
                self.assertFalse(any(item["error"] for item in result["toasts"]))

    def test_opening_bound_chat_preserves_binding_instead_of_selector_mode(self) -> None:
        for binding in (
            {"codexApp": {"threadId": "personal-thread", "connectionMode": "personal"}},
            {"codexApp": {"threadId": "team-thread", "connectionMode": "team-a"}},
        ):
            with self.subTest(binding=binding):
                result = self.run_ui("await openCodexApp();", connections=TEAM_CONNECTIONS, task=binding, ui={"codexAppConnectionMode": "team-a"})
                self.assertEqual(result["calls"], [{"path": "/api/tasks/task-1/app/open", "request": {}}])
                self.assertFalse(any(item["error"] for item in result["toasts"]))

    def test_opening_legacy_binding_sends_current_connection_as_rebuild_preference(self) -> None:
        result = self.run_ui("await openCodexApp();", connections=TEAM_CONNECTIONS, desktopMode="personal", task={"sessions": {"codexApp": "legacy-thread"}})
        self.assertEqual(result["calls"][0]["request"], {"connectionMode": "personal"})

    def test_new_chat_sends_selection_and_respects_existing_confirmation(self) -> None:
        for confirmed in (True, False):
            with self.subTest(confirmed=confirmed):
                result = self.run_ui("await newCodexAppChat();", connections=TEAM_CONNECTIONS, ui={"codexAppConnectionMode": "personal"}, confirm=confirmed)
                self.assertIn("个人账号", result["prompts"][0])
                expected = [{"path": "/api/tasks/task-1/app/new", "request": {"connectionMode": "personal"}}] if confirmed else []
                self.assertEqual(result["calls"], expected)
                self.assertFalse(any(item["error"] for item in result["toasts"]))

    def test_missing_desktop_open_confirmation_is_reported_without_protocol_fallback(self) -> None:
        for action in ("openCodexApp", "newCodexAppChat"):
            with self.subTest(action=action):
                response = {"task": {"id": "task-1", "codexApp": {"threadId": "created-thread", "deepLink": "codex://threads/created-thread"}}}
                result = self.run_ui(f"await {action}();", response=response)
                self.assertEqual(result["task"]["codexApp"]["threadId"], "created-thread")
                self.assertTrue(result["toasts"][-1]["error"])
                self.assertIn("尚未确认在桌面打开", result["toasts"][-1]["message"])

    def test_selected_mode_persists_per_task_and_restores_after_reload(self) -> None:
        result = self.run_ui("""
handlers.get("codexAppConnectionMode:change")({ target: { value: "personal" } });
activateTaskView("task-2");
const freshMode = ui.codexAppConnectionMode;
task = { id: "task-2" };
saveUi();
ui = loadUi();
activateTaskView("task-1");
return { freshMode, restoredMode: ui.codexAppConnectionMode };
""", connections=TEAM_CONNECTIONS)
        self.assertEqual(result["value"], {"freshMode": "", "restoredMode": "personal"})

    def test_capture_visible_fields_preserves_connection_selection(self) -> None:
        result = self.run_ui('handlers.get("codexAppConnectionMode:change")({ target: { value: "personal" } }); captureVisibleFields(); ui = loadUi(); return ui.codexAppConnectionMode;', connections=TEAM_CONNECTIONS, fieldValue="personal")
        self.assertEqual(result["value"], "personal")

    def test_capturing_other_fields_does_not_pin_automatic_desktop_mode(self) -> None:
        result = self.run_ui('captureVisibleFields(); ui = loadUi(); await newCodexAppChat();', connections=TEAM_CONNECTIONS, desktopMode="team-a", fieldValue="team-a", refreshedDesktopMode="personal")
        self.assertEqual(result["calls"][0]["request"], {"connectionMode": "personal"})

    def test_connection_labels_and_reasons_are_escaped(self) -> None:
        connections = [{"id": "team-a", "label": "<img src=x>", "available": True, "reason": ""}, {"id": "offline", "label": "Offline", "available": False, "reason": "<script>bad</script>"}]
        html = self.run_ui("return renderCodexAppPanel();", connections=connections, task={"codexApp": {"threadId": "existing", "connectionMode": "team-a"}})["value"]
        self.assertNotIn("<img", html)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;img src=x&gt;", html)
        self.assertIn("&lt;script&gt;bad&lt;/script&gt;", html)

    def test_disabled_app_feature_hides_panel_and_blocks_actions(self) -> None:
        features = {"codexAppLink": False, "codexConnectionModes": True}
        self.assertEqual(self.run_ui("return renderCodexAppPanel();", features=features)["value"], "")
        for action in ("openCodexApp", "newCodexAppChat"):
            self.assertFalse(self.run_ui(f"await {action}();", features=features)["calls"])


if __name__ == "__main__":
    unittest.main()
