from __future__ import annotations

import json
import subprocess
import unittest
from unittest import mock

import test_controller as controller


server = controller.server


class LarkSourceProcessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task_id = "lark-process-test"
        self.arguments = [
            "docs", "+fetch", "--doc", "https://example.feishu.cn/docx/document",
            "--as", "user", "--doc-format", "xml", "--detail", "full",
        ]
        for target, name, value in (
            (server, "ACTIVE_PROCESSES", {}),
            (server, "CANCEL_REQUESTED", set()),
        ):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for name, kwargs in (
            ("resolve_lark_cli_bin", {"return_value": "/test/bin/lark-cli"}),
            ("codex_process_spec", {"side_effect": AssertionError("Lark must inherit the service environment")}),
        ):
            patcher = mock.patch.object(server, name, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)

    def run_command(self, *, output=b'{"ok":true,"data":{"body":"document"}}', error=b"", returncode=0, cancel=False, deadline=100, wait_error=None, clock_values=None):
        process = mock.Mock()
        process.returncode = returncode
        process.poll.side_effect = lambda: process.returncode
        process.wait.side_effect = wait_error
        process.wait.return_value = returncode
        captured = {}

        def start(command, **kwargs):
            captured.update(command=command, **kwargs)
            kwargs["stdout"].write(output)
            kwargs["stdout"].flush()
            kwargs["stderr"].write(error)
            kwargs["stderr"].flush()
            if cancel:
                server.CANCEL_REQUESTED.add(self.task_id)
            return process

        def stop(target, force=False):
            target.returncode = -9

        with mock.patch.object(server.subprocess, "Popen", side_effect=start) as popen, \
                mock.patch.object(server, "stop_codex_process", side_effect=stop) as stop_process, \
                mock.patch.object(server.time, "monotonic", return_value=1, side_effect=clock_values):
            self.process = process
            self.popen = popen
            self.stop_process = stop_process
            self.captured = captured
            return server.run_lark_source_command(self.task_id, self.arguments, deadline)

    def test_success_uses_fixed_argument_array_and_service_environment(self) -> None:
        with mock.patch.dict(server.os.environ, {"LARK_PROCESS_SENTINEL": "service-value", "CODEX_HOME": "/service/codex-home"}):
            result = self.run_command()
        self.assertEqual(result, {"ok": True, "data": {"body": "document"}})
        self.assertEqual(self.captured["command"], ["/test/bin/lark-cli", *self.arguments])
        self.assertEqual(self.captured["env"]["LARK_PROCESS_SENTINEL"], "service-value")
        self.assertEqual(self.captured["env"]["CODEX_HOME"], "/service/codex-home")
        self.assertEqual(self.captured["env"]["LARKSUITE_CLI_NO_UPDATE_NOTIFIER"], "1")
        self.assertEqual(self.captured["env"]["LARKSUITE_CLI_NO_SKILLS_NOTIFIER"], "1")
        self.assertEqual(self.captured["cwd"], server.WORKSPACE_ROOT)
        self.assertEqual(self.captured["stdin"], subprocess.DEVNULL)
        self.assertTrue(self.captured["start_new_session"])
        self.assertFalse(self.captured.get("shell", False))
        self.assertTrue(self.captured["stdout"].closed)
        self.assertTrue(self.captured["stderr"].closed)
        server.codex_process_spec.assert_not_called()
        self.stop_process.assert_not_called()
        self.assertNotIn(self.task_id, server.ACTIVE_PROCESSES)

    def test_mutating_command_is_rejected_before_process_start(self) -> None:
        self.arguments = ["docs", "+update", "--as", "user"]
        with self.assertRaises(server.source_reading.SourceReadError):
            self.run_command()
        self.popen.assert_not_called()

    def test_keychain_failure_is_lark_specific_without_echoing_secret(self) -> None:
        with self.assertRaises(server.source_reading.SourceReadError) as caught:
            self.run_command(returncode=1, error=b"keychain Get failed: keychain not initialized; credential-secret-123")
        self.assertIn("lark_credentials_unavailable", str(caught.exception))
        self.assertIn("Lark CLI", str(caught.exception))
        for forbidden in ("credential-secret-123", "Codex", "Chrome"):
            self.assertNotIn(forbidden, str(caught.exception))
        self.assertNotIn(self.task_id, server.ACTIVE_PROCESSES)

    def test_missing_scope_returns_fixed_permission_reason(self) -> None:
        for scopes in (["sheets:spreadsheet:read"], None):
            with self.subTest(scopes=scopes):
                raw = json.dumps({"ok": False, "error": {
                    "subtype": "missing_scope", "missing_scopes": scopes,
                    "message": "credential-secret-123",
                }}).encode()
                with self.assertRaises(server.source_reading.SourceReadError) as caught:
                    self.run_command(returncode=1, error=raw)
                self.assertIn("document_permission_denied", str(caught.exception))
                if scopes:
                    self.assertIn("sheets:spreadsheet:read", str(caught.exception))
                self.assertNotIn("credential-secret-123", str(caught.exception))

    def test_cancel_stops_process_and_removes_active_registration(self) -> None:
        with self.assertRaisesRegex(server.WorkflowError, "用户已停止"):
            self.run_command(returncode=None, cancel=True)
        self.stop_process.assert_called_once_with(self.process, True)
        self.process.wait.assert_called_once_with(timeout=5)
        self.assertNotIn(self.task_id, server.ACTIVE_PROCESSES)
        self.assertTrue(self.captured["stdout"].closed)
        self.assertTrue(self.captured["stderr"].closed)

    def test_expired_deadline_prevents_starting_another_attachment_process(self) -> None:
        with self.assertRaisesRegex(server.source_reading.SourceReadError, "读取超时"):
            self.run_command(returncode=None, deadline=0)
        self.popen.assert_not_called()
        self.assertNotIn(self.task_id, server.ACTIVE_PROCESSES)

    def test_running_timeout_stops_process_without_discarding_main_body(self) -> None:
        with self.assertRaisesRegex(server.source_reading.SourceReadError, "读取超时"):
            self.run_command(returncode=None, clock_values=[1, 101])
        self.stop_process.assert_called_once_with(self.process, True)
        self.process.wait.assert_called_once_with(timeout=5)
        self.assertNotIn(self.task_id, server.ACTIVE_PROCESSES)

    def test_active_registration_is_removed_even_when_killed_process_wait_fails(self) -> None:
        with self.assertRaisesRegex(server.WorkflowError, "用户已停止"):
            self.run_command(returncode=None, cancel=True, wait_error=subprocess.TimeoutExpired("lark-cli", 5))
        self.stop_process.assert_called_once_with(self.process, True)
        self.assertNotIn(self.task_id, server.ACTIVE_PROCESSES)

    def test_output_limit_stops_process_for_either_stream(self) -> None:
        oversized = b"x" * (4 * 1024 * 1024 + 1)
        for stream in ("output", "error"):
            with self.subTest(stream=stream):
                with self.assertRaisesRegex(server.source_reading.SourceReadError, "read_incomplete"):
                    self.run_command(returncode=None, **{stream: oversized})
                self.stop_process.assert_called_once_with(self.process, True)
                self.assertNotIn(self.task_id, server.ACTIVE_PROCESSES)


class LarkCliStatusTests(unittest.TestCase):
    def status(self, auth, *, returncode=0, error="", version_returncode=0):
        results = [
            subprocess.CompletedProcess([], version_returncode, "lark-cli 1.0", ""),
            subprocess.CompletedProcess([], returncode, json.dumps(auth), error),
        ]
        with mock.patch.object(server, "resolve_lark_cli_bin", return_value="/test/bin/lark-cli"), \
                mock.patch.object(server.Path, "is_file", return_value=True), \
                mock.patch.object(server, "run_command", side_effect=results) as run:
            status = server.lark_cli_status()
        self.assertEqual(run.call_args_list[1].args[0], ["/test/bin/lark-cli", "auth", "status", "--json"])
        return status

    def test_bot_ready_without_user_authorization_is_unavailable(self) -> None:
        status = self.status({"identities": {"bot": {"available": True}, "user": {"available": False}}})
        self.assertFalse(status["authenticated"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["errorCode"], "reader_unavailable")

    def test_user_available_with_needs_refresh_is_ready(self) -> None:
        status = self.status({"identities": {"user": {"available": True, "status": "needs_refresh"}}})
        self.assertTrue(status["authenticated"])
        self.assertTrue(status["ready"])
        self.assertEqual(status["errorCode"], "")

    def test_broken_cli_is_unavailable_even_when_user_auth_is_present(self) -> None:
        status = self.status({"identities": {"user": {"available": True}}}, version_returncode=1)
        self.assertTrue(status["authenticated"])
        self.assertFalse(status["ready"])
        self.assertEqual(status["errorCode"], "reader_unavailable")

    def test_keychain_failure_has_safe_lark_guidance(self) -> None:
        status = self.status({}, returncode=1, error="keychain Get failed: keychain not initialized; credential-secret-123")
        self.assertFalse(status["ready"])
        self.assertEqual(status["errorCode"], "lark_credentials_unavailable")
        self.assertIn("Lark CLI", status["message"])
        for forbidden in ("credential-secret-123", "Codex", "Chrome"):
            self.assertNotIn(forbidden, status["message"])


if __name__ == "__main__":
    unittest.main()
