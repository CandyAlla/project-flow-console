from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

try:
    import tomllib
except ImportError:
    tomllib = None

import codex_connections as connections
import codex_desktop


class CodexConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codex-connections-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings_path = self.root / "connections.json"
        self.patch = mock.patch.object(connections, "SETTINGS_PATH", self.settings_path)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        for name in ("base", "api", "account", "Codex.app", "API Launcher.app", "Account Launcher.app"):
            (self.root / name).mkdir()
        self.state_path = self.root / "state.json"
        self.state_path.write_text(json.dumps({"homes_ready": True, "active": "newapi"}))
        self.credential_path = self.root / "api-auth.json"
        self.secret = "test-secret-not-for-command-lines"
        self.credential_path.write_text(json.dumps({"OPENAI_API_KEY": self.secret}))
        self.settings = {
            "baseHome": str(self.root / "base"),
            "switcherStatePath": str(self.state_path),
            "desktopApp": str(self.root / "Codex.app"),
            "connections": {
                "api": {
                    "home": str(self.root / "api"),
                    "launcher": str(self.root / "API Launcher.app"),
                    "credentialFile": str(self.credential_path),
                    "envKey": "TEST_CODEX_API_KEY",
                    "config": {
                        "model_provider": "test_api", "forced_login_method": "api", "model": "example-model",
                        "model_providers.test_api.env_key": "TEST_CODEX_API_KEY",
                        "model_providers.test_api.requires_openai_auth": False,
                        "model_providers.test_api.base_url": "https://example.invalid/v1",
                        "model_providers.test_api.request_max_retries": 2,
                    },
                },
                "account": {
                    "home": str(self.root / "account"),
                    "launcher": str(self.root / "Account Launcher.app"),
                    "config": {"model_provider": "openai", "forced_login_method": "chatgpt", "model": "example-model"},
                },
            },
        }
        self.write_settings()
        platform_patch = mock.patch.object(codex_desktop.sys, "platform", "darwin")
        platform_patch.start()
        self.addCleanup(platform_patch.stop)
        opener_patch = mock.patch.object(codex_desktop, "_platform_command", return_value=["/usr/bin/open"])
        opener_patch.start()
        self.addCleanup(opener_patch.stop)

    def write_settings(self) -> None:
        self.settings_path.write_text(json.dumps(self.settings), encoding="utf-8")

    def test_background_description_keeps_legacy_api_without_reading_credentials(self) -> None:
        self.state_path.write_text(json.dumps({"homes_ready": True, "active": "chatgpt"}))
        with mock.patch.object(connections, "_credential", side_effect=AssertionError("credentials must not be loaded")):
            self.assertEqual(connections.background_connection(), {"id": "api", "label": "API 登录版"})
        self.settings_path.unlink()
        self.assertEqual(connections.background_connection(), {"id": "default", "label": "默认 Codex 环境"})

    def test_api_overrides_are_toml_scalars_and_credentials_stay_in_child_environment(self) -> None:
        original = ["/bin/codex", "exec", "--json", "prompt"]
        with mock.patch.dict(os.environ, {"CODEX_HOME": "/original/home", "OPENAI_API_KEY": "old-secret", "TEST_CODEX_API_KEY": "old-key"}):
            before = dict(os.environ)
            command, env = connections.resolve(original)
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(original, ["/bin/codex", "exec", "--json", "prompt"])
        self.assertEqual(command[0], original[0])
        self.assertEqual(command[-3:], original[1:])
        assignments = command[2:-3:2]
        self.assertIn('model_provider="test_api"', assignments)
        self.assertIn('forced_login_method="api"', assignments)
        self.assertIn("model_providers.test_api.requires_openai_auth=false", assignments)
        self.assertIn("model_providers.test_api.request_max_retries=2", assignments)
        self.assertEqual(env["TEST_CODEX_API_KEY"], self.secret)
        self.assertEqual(env["CODEX_HOME"], str(self.root / "api"))
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn(self.secret, repr(command))
        self.assertEqual(json.loads(self.credential_path.read_text()), {"OPENAI_API_KEY": self.secret})

    @unittest.skipUnless(tomllib is not None, "TOML parser is available on Python 3.11 and later")
    def test_override_values_parse_as_toml_scalars(self) -> None:
        command, _ = connections.resolve(["codex", "exec"])
        parsed = tomllib.loads("\n".join(command[2:-1:2]))
        self.assertEqual(parsed["model_provider"], "test_api")
        self.assertEqual(parsed["forced_login_method"], "api")
        self.assertFalse(parsed["model_providers"]["test_api"]["requires_openai_auth"])
        self.assertEqual(parsed["model_providers"]["test_api"]["request_max_retries"], 2)

    def test_api_provider_cannot_require_account_authentication(self) -> None:
        for value in (True, None, "false", 0):
            self.settings["connections"]["api"]["config"]["model_providers.test_api.requires_openai_auth"] = value
            self.write_settings()
            with self.subTest(value=value):
                with self.assertRaises(connections.ConnectionError):
                    connections.resolve(["codex"])

    def test_backend_uses_base_home_before_desktop_initialization(self) -> None:
        self.state_path.write_text(json.dumps({"homes_ready": False, "active": None}))
        (self.root / "api").rmdir()
        command, env = connections.resolve(["codex", "app-server"])
        self.assertEqual(env["CODEX_HOME"], str(self.root / "base"))
        self.assertIn('model_provider="test_api"', command)
        self.assertEqual(env["TEST_CODEX_API_KEY"], self.secret)
        self.assertFalse((self.root / "api").exists())

    def test_desktop_mode_reads_initialized_launcher_state_without_switching(self) -> None:
        for active, ready, expected in (
            ("chatgpt", True, "account"), ("newapi", True, "api"),
            ("legacy", True, "api"), (None, True, "api"), ("chatgpt", False, "api"),
        ):
            with self.subTest(active=active, ready=ready):
                self.state_path.write_text(json.dumps({"homes_ready": ready, "active": active}))
                before = self.state_path.read_bytes()
                with mock.patch.object(codex_desktop.subprocess, "run") as run:
                    self.assertEqual(connections.desktop_mode(), expected)
                    run.assert_not_called()
                self.assertEqual(self.state_path.read_bytes(), before)
        self.settings_path.unlink()
        self.assertEqual(connections.desktop_mode(), "default")

    def test_desktop_mode_reports_invalid_state_without_guessing_api(self) -> None:
        self.state_path.write_text("invalid JSON")
        with self.assertRaises(connections.ConnectionError):
            connections.desktop_mode()

    def test_account_uses_only_account_home_and_removes_api_environment(self) -> None:
        api_names = {"OPENAI_API_KEY", "OPENAI_ACCESS_TOKEN", "CODEX_API_KEY", "CODEX_ACCESS_TOKEN", "TEST_CODEX_API_KEY", "OPENAI_BASE_URL", "CODEX_SQLITE_HOME"}
        with mock.patch.dict(os.environ, {key: "must-not-leak" for key in api_names}):
            before = dict(os.environ)
            command, env = connections.resolve(["codex", "app-server"], mode="account", desktop=True)
            self.assertEqual(dict(os.environ), before)
        self.assertTrue(api_names.isdisjoint(env))
        self.assertEqual(env["CODEX_HOME"], str(self.root / "account"))
        self.assertIn('model_provider="openai"', command)
        self.assertIn('forced_login_method="chatgpt"', command)

    def test_desktop_requires_completed_initialization_and_existing_home(self) -> None:
        for ready, missing_home in ((False, False), (True, True)):
            with self.subTest(ready=ready):
                self.state_path.write_text(json.dumps({"homes_ready": ready, "active": "newapi"}))
                if missing_home:
                    (self.root / "api").rmdir()
                with mock.patch.object(codex_desktop.subprocess, "run") as run:
                    with self.assertRaisesRegex(connections.ConnectionError, "先手动打开.*初始化"):
                        connections.resolve(["codex", "app-server"], desktop=True)
                    with self.assertRaisesRegex(connections.ConnectionError, "初始化"):
                        connections.open_desktop("api", "codex://threads/thread-1")
                    run.assert_not_called()

    def test_missing_configuration_preserves_legacy_behavior(self) -> None:
        self.settings_path.unlink()
        original = ["codex", "exec", "prompt"]
        command, env = connections.resolve(original)
        self.assertEqual(command, original)
        self.assertIsNot(command, original)
        self.assertEqual(env, dict(os.environ))
        self.assertIsNot(env, os.environ)
        connections.validate_desktop("default")
        with mock.patch.object(codex_desktop.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            connections.open_desktop("default", "codex://threads/thread_1")
        self.assertEqual(run.call_args.args[0], ["/usr/bin/open", "codex://threads/thread_1"])

    def test_invalid_connections_are_rejected_without_fallback(self) -> None:
        for configured in (True, False):
            if not configured:
                self.settings_path.unlink()
            for mode in ("newapi", "chatgpt", "", [], {}):
                with self.subTest(configured=configured, mode=mode):
                    with self.assertRaises(connections.ConnectionError):
                        connections.resolve(["codex"], mode=mode)
                    with self.assertRaises(connections.ConnectionError):
                        connections.validate_desktop(mode)
            if not configured:
                with self.assertRaises(connections.ConnectionError):
                    connections.resolve(["codex"], mode="account")

    def test_bad_configuration_fails_without_credential_content(self) -> None:
        variants = [[], {"connections": {}}, {**self.settings, "baseHome": "relative"}]
        for value in (None, [], {}, float("inf")):
            setting = copy.deepcopy(self.settings)
            setting["connections"]["api"]["config"]["invalid_value"] = value
            variants.append(setting)
        for setting in variants:
            self.settings_path.write_text(json.dumps(setting))
            with self.subTest(setting_type=type(setting).__name__):
                with self.assertRaises(connections.ConnectionError):
                    connections.resolve(["codex"])
        self.settings_path.write_text('{"password":"' + self.secret)
        with self.assertRaises(connections.ConnectionError) as raised:
            connections.resolve(["codex"])
        self.assertNotIn(self.secret, str(raised.exception))

    def test_missing_or_invalid_key_never_falls_back_to_inherited_key(self) -> None:
        for raw in ('{}', '{"OPENAI_API_KEY":" "}', '{"OPENAI_API_KEY":5}', '{"OPENAI_API_KEY":"' + self.secret):
            self.credential_path.write_text(raw)
            with mock.patch.dict(os.environ, {"TEST_CODEX_API_KEY": "inherited-key"}):
                with self.assertRaises(connections.ConnectionError) as raised:
                    connections.resolve(["codex"])
            self.assertNotIn(self.secret, str(raised.exception))
        self.credential_path.unlink()
        with self.assertRaisesRegex(connections.ConnectionError, "连接凭据"):
            connections.resolve(["codex"])

    def test_existing_connection_overrides_cannot_bypass_fixed_api(self) -> None:
        for flags in (["-c", 'model_provider="openai"'], ['--config=model="other"'], ["--profile", "account"], ["--model=other"], ["-paccount"], ["-mother"], ["-c", "model_providers={}"]):
            with self.subTest(flags=flags):
                with self.assertRaisesRegex(connections.ConnectionError, "不能覆盖"):
                    connections.resolve(["codex", "exec", *flags])
        command, _ = connections.resolve(["codex", "exec", "-c", 'approval_policy="never"'])
        self.assertEqual(command[-2:], ["-c", 'approval_policy="never"'])

    def test_rpc_overrides_pin_provider_on_new_and_resumed_threads(self) -> None:
        for mode, provider in (("api", "test_api"), ("account", "openai")):
            for method in ("thread/start", "thread/resume"):
                with self.subTest(mode=mode, method=method):
                    self.assertEqual(connections.rpc_overrides(method, mode=mode), {"modelProvider": provider, "model": "example-model"})

    def test_turn_overrides_only_include_supported_model_and_effort(self) -> None:
        self.assertEqual(connections.rpc_overrides("turn/start"), {"model": "example-model"})
        self.settings["connections"]["api"]["config"]["model_reasoning_effort"] = "high"
        self.write_settings()
        self.assertEqual(connections.rpc_overrides("turn/start"), {"model": "example-model", "effort": "high"})
        self.assertEqual(connections.rpc_overrides("thread/read"), {})
        self.assertEqual(connections.rpc_overrides("initialize"), {})

    def test_rpc_overrides_validate_mode_and_settings_without_config_fallback(self) -> None:
        with self.assertRaises(connections.ConnectionError):
            connections.rpc_overrides("thread/resume", mode={})
        self.settings_path.write_text("invalid JSON")
        with self.assertRaises(connections.ConnectionError):
            connections.rpc_overrides("thread/resume")
        self.settings_path.unlink()
        self.assertEqual(connections.rpc_overrides("thread/resume", mode="default"), {})
        for mode in ("api", "account"):
            with self.assertRaises(connections.ConnectionError):
                connections.rpc_overrides("thread/resume", mode=mode)

    def test_launcher_opens_even_when_same_mode_then_targets_configured_app(self) -> None:
        with mock.patch.object(codex_desktop.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            connections.open_desktop("api", "codex://threads/thread-1")
        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[0], ["/usr/bin/open", "-W", "-a", str(self.root / "API Launcher.app")])
        self.assertEqual(run.call_args_list[0].kwargs["timeout"], 60)
        self.assertEqual(run.call_args_list[1].args[0], ["/usr/bin/open", "-a", str(self.root / "Codex.app"), "codex://threads/thread-1"])

    def test_account_launcher_must_report_chatgpt_before_opening_link(self) -> None:
        def run(command, **kwargs):
            if "-W" in command:
                self.state_path.write_text(json.dumps({"homes_ready": True, "active": "chatgpt"}))
            return mock.Mock(returncode=0)
        with mock.patch.object(codex_desktop.subprocess, "run", side_effect=run) as process:
            connections.open_desktop("account", "codex://threads/account-thread")
        self.assertEqual(process.call_count, 2)

    def test_wrong_mode_or_failed_launcher_never_opens_deeplink(self) -> None:
        for failure in (None, subprocess.TimeoutExpired("open", 60), OSError("private message")):
            self.state_path.write_text(json.dumps({"homes_ready": True, "active": "chatgpt"}))
            with mock.patch.object(codex_desktop.subprocess, "run", return_value=mock.Mock(returncode=0), side_effect=failure) as run:
                with self.assertRaises(connections.ConnectionError):
                    connections.open_desktop("api", "codex://threads/thread-1")
                self.assertEqual(run.call_count, 1)
        with mock.patch.object(codex_desktop.subprocess, "run", return_value=mock.Mock(returncode=1, stderr=self.secret)) as run:
            with self.assertRaises(connections.ConnectionError) as raised:
                connections.open_desktop("api", "codex://threads/thread-1")
            self.assertEqual(run.call_count, 1)
            self.assertNotIn(self.secret, str(raised.exception))

    def test_bad_deeplinks_never_start_a_process(self) -> None:
        for link in ("https://example.invalid", "codex://threads/../thread", "codex://threads/a?mode=api", "codex://threads/", "codex://threads/" + "a" * 161, "codex://threads/a\n"):
            with self.subTest(link=link), mock.patch.object(codex_desktop.subprocess, "run") as run:
                with self.assertRaisesRegex(connections.ConnectionError, "链接无效"):
                    connections.open_desktop("api", link)
                run.assert_not_called()


class NamedConnectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="codex-named-connection-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings_path = self.root / "connections.json"
        patch = mock.patch.object(connections, "SETTINGS_PATH", self.settings_path)
        patch.start()
        self.addCleanup(patch.stop)
        self.home = self.root / "account-home"
        self.home.mkdir()
        self.opener = self.root / "desktop-opener"
        self.opener.write_text("test fixture; never executed")
        self.opener.chmod(0o700)
        self.settings = {"version": 2, "connections": {}}

    def write_settings(self) -> None:
        self.settings_path.write_text(json.dumps(self.settings), encoding="utf-8")

    def add_connection(self, connection_id: str = "personal", **values) -> dict:
        connection = {"home": str(self.home), "desktop": {"type": "command", "command": [str(self.opener), "{url}"]}, **values}
        self.settings["connections"][connection_id] = connection
        self.write_settings()
        return connection

    def test_unconfigured_install_has_one_default_and_preserves_ambient_connection(self) -> None:
        original = ["codex", "exec", "--profile", "personal"]
        with mock.patch.object(codex_desktop, "_platform_command", return_value=["/usr/bin/open"]):
            self.assertEqual(connections.desktop_mode(), "default")
            self.assertEqual(connections.desktop_options(), [{"id": "default", "label": "默认 Codex 环境", "available": True, "reason": ""}])
            command, env = connections.resolve(original, desktop=True)
        self.assertEqual(command, original)
        self.assertIsNot(command, original)
        self.assertEqual(env, dict(os.environ))
        self.assertEqual(connections.rpc_overrides("thread/start"), {})
        for mode in ("api", "account", "unknown"):
            with self.assertRaises(connections.ConnectionError):
                connections.resolve(["codex"], mode=mode)

    def test_empty_version_two_uses_default(self) -> None:
        self.settings = {"version": 2}
        self.write_settings()
        self.assertEqual(connections.desktop_mode(), "default")
        self.assertEqual(connections.resolve(["codex"])[1], dict(os.environ))

    def test_single_account_connection_needs_no_api_launcher_or_model(self) -> None:
        auth = self.home / "auth.json"
        auth.write_text('{"existing_account":"fixture"}')
        before = auth.read_bytes()
        self.add_connection("personal", label="个人账号")
        self.settings["defaultDesktopConnection"] = "personal"
        self.settings["backgroundConnection"] = "personal"
        self.write_settings()
        self.assertEqual(connections.desktop_mode(), "personal")
        for desktop in (False, True):
            command, env = connections.resolve(["codex", "app-server"], desktop=desktop)
            self.assertEqual(command, ["codex", "app-server"])
            self.assertEqual(env["CODEX_HOME"], str(self.home))
            self.assertEqual(connections.rpc_overrides("thread/start", desktop=desktop), {})
        with mock.patch.object(codex_desktop.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            connections.open_desktop(None, "codex://threads/personal-1")
        self.assertEqual(run.call_args.args[0], [str(self.opener), "codex://threads/personal-1"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertEqual(auth.read_bytes(), before)

    def test_background_connection_is_independent_of_desktop_default_and_state(self) -> None:
        self.add_connection("personal", config={"model": "desktop-model"})
        automation_home = self.root / "automation"
        automation_home.mkdir()
        self.settings["connections"]["team-work"] = {"home": str(automation_home), "config": {"model_provider": "team", "model": "worker-model"}}
        self.settings.update(backgroundConnection="team-work", defaultDesktopConnection="personal")
        self.write_settings()
        with mock.patch.object(codex_desktop, "_state", side_effect=AssertionError("background read desktop state")), mock.patch.object(codex_desktop, "unavailable_reason", side_effect=AssertionError("background checked desktop")):
            command, env = connections.resolve(["codex", "app-server"])
            overrides = connections.rpc_overrides("thread/start")
        self.assertEqual(env["CODEX_HOME"], str(automation_home))
        self.assertIn('model="worker-model"', command)
        self.assertEqual(overrides, {"model": "worker-model", "modelProvider": "team"})
        self.assertEqual(connections.rpc_overrides("thread/start", desktop=True), {"model": "desktop-model"})
        self.assertEqual([item["id"] for item in connections.desktop_options()], ["default", "personal"])
        with self.assertRaisesRegex(connections.ConnectionError, "仅用于后台"):
            connections.resolve(["codex"], mode="team-work", desktop=True)

    def test_unknown_defaults_do_not_hide_working_desktop_options(self) -> None:
        self.add_connection()
        self.settings.update(backgroundConnection="missing-worker", defaultDesktopConnection="missing-desktop")
        self.write_settings()
        self.assertEqual(connections.desktop_mode(), "missing-desktop")
        self.assertTrue(next(item for item in connections.desktop_options() if item["id"] == "personal")["available"])
        connections.validate_desktop("personal")
        with self.assertRaises(connections.ConnectionError):
            connections.resolve(["codex"])
        with self.assertRaises(connections.ConnectionError):
            connections.resolve(["codex"], desktop=True)
        self.assertEqual(connections.resolve(["codex"], mode="personal")[1]["CODEX_HOME"], str(self.home))

    def test_current_opener_checks_home_without_switching(self) -> None:
        self.add_connection(desktop={"type": "current"})
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home)}), mock.patch.object(codex_desktop, "_platform_command", return_value=["/usr/bin/open"]):
            connections.validate_desktop("personal")
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "different-home")}):
            item = next(item for item in connections.desktop_options() if item["id"] == "personal")
            self.assertFalse(item["available"])
            self.assertIn("不同", item["reason"])
            self.assertNotIn(str(self.root), item["reason"])
            with self.assertRaises(connections.ConnectionError):
                connections.resolve(["codex"], mode="personal", desktop=True)

    def test_current_opener_uses_default_home_when_codex_home_unset(self) -> None:
        current_home = self.root / ".codex"
        current_home.mkdir()
        self.add_connection(home=str(current_home), desktop={"type": "current"})
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(codex_desktop.Path, "home", return_value=self.root), mock.patch.object(codex_desktop, "_platform_command", return_value=["/usr/bin/open"]):
            connections.validate_desktop("personal")

    def test_current_opener_rejects_inherited_alternate_database_home(self) -> None:
        self.add_connection(desktop={"type": "current"})
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.home), "CODEX_SQLITE_HOME": str(self.root / "other-database")}), mock.patch.object(codex_desktop, "_platform_command", return_value=["/usr/bin/open"]):
            with self.assertRaisesRegex(connections.ConnectionError, "数据库目录"):
                connections.validate_desktop("personal")
            self.assertTrue(connections.desktop_options()[0]["available"])
            self.assertEqual(connections.resolve(["codex"], mode="default")[1]["CODEX_SQLITE_HOME"], str(self.root / "other-database"))
            self.assertNotIn("CODEX_SQLITE_HOME", connections.resolve(["codex"], mode="personal")[1])

    def test_named_config_cannot_redirect_database_or_select_another_profile(self) -> None:
        for key in ("sqlite_home", "profile", "profiles", "profiles.other.model", "profiles.other.sqlite_home", "nested.sqlite_home"):
            with self.subTest(key=key):
                self.add_connection(config={key: "alternate"})
                with self.assertRaisesRegex(connections.ConnectionError, "覆盖连接目录"):
                    connections.resolve(["codex"], mode="personal")

    def test_missing_home_or_opener_is_unavailable_and_never_launches(self) -> None:
        connection = self.add_connection()
        for change in ("home", "executable", "permissions"):
            with self.subTest(change=change):
                connection["home"] = str(self.home)
                connection["desktop"]["command"][0] = str(self.opener)
                self.opener.chmod(0o700)
                if change == "home":
                    connection["home"] = str(self.root / "missing-home")
                elif change == "executable":
                    connection["desktop"]["command"][0] = str(self.root / "missing-program")
                else:
                    self.opener.chmod(0o600)
                self.write_settings()
                item = next(item for item in connections.desktop_options() if item["id"] == "personal")
                self.assertFalse(item["available"])
                self.assertNotIn(str(self.root), json.dumps(item))
                with mock.patch.object(codex_desktop.subprocess, "run") as run:
                    with self.assertRaises(connections.ConnectionError):
                        connections.open_desktop("personal", "codex://threads/id-1")
                    run.assert_not_called()

    def test_command_arguments_are_literal_and_url_is_one_complete_argument(self) -> None:
        self.add_connection(desktop={"type": "command", "command": [str(self.opener), "--literal=$(do-not-run); `also-literal`", "{url}"]})
        with mock.patch.object(codex_desktop.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            connections.open_desktop("personal", "codex://threads/abc_123")
        self.assertEqual(run.call_args.args[0], [str(self.opener), "--literal=$(do-not-run); `also-literal`", "codex://threads/abc_123"])
        self.assertFalse(run.call_args.kwargs["shell"])

    def test_unsafe_command_templates_fail_before_starting_processes(self) -> None:
        for command in (
            "open {url}", [], ["relative-opener", "{url}"], [str(self.opener)],
            [str(self.opener), "{url}", "{url}"], [str(self.opener), "--url={url}"],
            [str(self.opener), "{url}", "{other}"], [str(self.opener), "{url}\x00"],
            ["/bin/sh", "-c", "{url}"], [str(self.opener), 5],
        ):
            with self.subTest(command=command), mock.patch.object(codex_desktop.subprocess, "run") as run:
                self.add_connection(desktop={"type": "command", "command": command})
                with self.assertRaises(connections.ConnectionError):
                    connections.open_desktop("personal", "codex://threads/valid")
                run.assert_not_called()

    def test_custom_credentials_stay_in_selected_child_environment(self) -> None:
        secret = "fixture-selected-secret"
        auth = self.root / "credentials.json"
        auth.write_text(json.dumps({"access": secret}))
        self.add_connection("team", credentialFile=str(auth), credentialKey="access", envKey="TEAM_CODEX_KEY")
        self.settings["connections"]["other"] = {"home": str(self.home), "envKey": "OTHER_CODEX_KEY"}
        self.write_settings()
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "other-key", "TEAM_CODEX_KEY": "stale", "OTHER_CODEX_KEY": "other", "CODEX_SQLITE_HOME": "wrong"}):
            before = dict(os.environ)
            command, env = connections.resolve(["codex"], mode="team")
            self.assertEqual(dict(os.environ), before)
        self.assertEqual(env["TEAM_CODEX_KEY"], secret)
        for key in ("OPENAI_API_KEY", "OTHER_CODEX_KEY", "CODEX_SQLITE_HOME"):
            self.assertNotIn(key, env)
        self.assertNotIn(secret, repr(command))
        self.assertNotIn(secret, json.dumps(connections.desktop_options()))

    def test_env_key_only_preserves_selected_key_and_never_substitutes_another(self) -> None:
        self.add_connection(envKey="PERSONAL_KEY")
        with mock.patch.dict(os.environ, {"PERSONAL_KEY": "selected", "OPENAI_API_KEY": "wrong"}):
            _, env = connections.resolve(["codex"], mode="personal")
        self.assertEqual(env["PERSONAL_KEY"], "selected")
        self.assertNotIn("OPENAI_API_KEY", env)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "wrong"}, clear=True):
            with self.assertRaisesRegex(connections.ConnectionError, "环境变量"):
                connections.resolve(["codex"], mode="personal")

    def test_missing_credential_file_never_uses_inherited_value(self) -> None:
        self.add_connection(credentialFile=str(self.root / "missing-secret.json"), envKey="PERSONAL_KEY")
        with mock.patch.dict(os.environ, {"PERSONAL_KEY": "stale-secret"}):
            with self.assertRaises(connections.ConnectionError) as raised:
                connections.resolve(["codex"], mode="personal")
        self.assertNotIn("stale-secret", str(raised.exception))
        self.assertNotIn(str(self.root), str(raised.exception))

    def test_rpc_overrides_include_only_explicit_supported_fields(self) -> None:
        connection = self.add_connection(config={"model_provider": "custom", "model_reasoning_effort": "high"})
        self.assertEqual(connections.rpc_overrides("thread/start", mode="personal"), {"modelProvider": "custom"})
        self.assertEqual(connections.rpc_overrides("turn/start", mode="personal"), {"effort": "high"})
        self.assertEqual(connections.rpc_overrides("thread/read", mode="personal"), {})
        connection["config"] = {}
        self.write_settings()
        self.assertEqual(connections.rpc_overrides("thread/resume", mode="personal"), {})
        self.assertEqual(connections.rpc_overrides("thread/start", mode="default"), {})

    def test_app_server_spec_freezes_process_and_rpc_configuration_from_one_read(self) -> None:
        connection = self.add_connection(config={"model": "original", "model_provider": "original-provider", "model_reasoning_effort": "high"})
        self.settings.update(backgroundConnection="personal", defaultDesktopConnection="personal")
        self.write_settings()
        with mock.patch.object(connections, "_settings", wraps=connections._settings) as read:
            command, env, overrides = connections.app_server_spec(["codex", "app-server"])
        read.assert_called_once_with()
        new_home = self.root / "replacement-home"
        new_home.mkdir()
        connection.update(home=str(new_home), config={"model": "replacement"})
        self.settings.update(backgroundConnection="default", defaultDesktopConnection="default")
        self.write_settings()
        self.assertEqual(env["CODEX_HOME"], str(self.home))
        self.assertIn('model="original"', command)
        self.assertEqual(overrides, {
            "thread/start": {"model": "original", "modelProvider": "original-provider"},
            "thread/resume": {"model": "original", "modelProvider": "original-provider"},
            "turn/start": {"model": "original", "effort": "high"},
        })
        self.assertEqual(connections.rpc_overrides("thread/start"), {})

    def test_desktop_app_server_spec_uses_desktop_default(self) -> None:
        self.add_connection(config={"model": "desktop-only"})
        self.settings["defaultDesktopConnection"] = "personal"
        self.write_settings()
        _, env, overrides = connections.app_server_spec(["codex", "app-server"], desktop=True)
        self.assertEqual(env["CODEX_HOME"], str(self.home))
        self.assertEqual(overrides["thread/start"], {"model": "desktop-only"})
        self.assertEqual(connections.app_server_spec(["codex", "app-server"])[2]["thread/start"], {})

    def test_version_two_rejects_private_adapter_and_malformed_configuration_without_values(self) -> None:
        secret = "sensitive-fixture-value"
        variants = [
            {"version": 1}, {"version": True}, {"version": 2, "_legacy": {}},
            {"version": 2, "connections": {"default": {"home": str(self.home)}}},
            {"version": 2, "connections": {"../secret": {"home": str(self.home)}}},
        ]
        for extra in ({"config": {"model": []}}, {"config": {"bad": float("nan")}}, {"home": secret}, {"desktop": {"type": "legacy"}}, {"credentialFile": str(self.root / "secret")}, {"envKey": "HOME"}):
            variants.append({"version": 2, "connections": {"test": {"home": str(self.home), **extra}}})
        for value in variants:
            self.settings = value
            self.write_settings()
            with self.subTest(value=value), self.assertRaises(connections.ConnectionError) as raised:
                connections.resolve(["codex"])
            self.assertNotIn(secret, str(raised.exception))
            self.assertNotIn(str(self.root), str(raised.exception))

    def test_platform_openers_are_selected_without_shell(self) -> None:
        link = "codex://threads/default-1"
        for platform, expected in (("darwin", ["/usr/bin/open", link]), ("linux", ["/usr/bin/xdg-open", link])):
            with self.subTest(platform=platform), mock.patch.object(codex_desktop.sys, "platform", platform), mock.patch.object(codex_desktop, "_executable", return_value=True), mock.patch.object(codex_desktop.shutil, "which", return_value="/usr/bin/xdg-open"), mock.patch.object(codex_desktop.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
                connections.open_desktop("default", link)
                self.assertEqual(run.call_args.args[0], expected)
                self.assertFalse(run.call_args.kwargs["shell"])
        with mock.patch.object(codex_desktop.sys, "platform", "win32"), mock.patch.object(codex_desktop.os, "startfile", create=True) as startfile, mock.patch.object(codex_desktop.subprocess, "run") as run:
            connections.open_desktop("default", link)
            startfile.assert_called_once_with(link)
            run.assert_not_called()

    def test_missing_platform_opener_is_reported_unavailable(self) -> None:
        with mock.patch.object(codex_desktop.sys, "platform", "linux"), mock.patch.object(codex_desktop.shutil, "which", return_value=None):
            self.assertFalse(connections.desktop_options()[0]["available"])
            with self.assertRaises(connections.ConnectionError):
                connections.validate_desktop("default")
            self.assertEqual(connections.resolve(["codex"])[0], ["codex"])


if __name__ == "__main__":
    unittest.main()
