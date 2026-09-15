from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest

import source_reading as reading


class SourceReadingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.source = {"type": "link", "reader": "chrome_mcp", "url": "https://example.feishu.cn/wiki/original#part"}
        self.payload = {
            "title": "需求文档",
            "url": self.source["url"],
            "body": "功能入口\n点击活动按钮后打开原始需求指定的页面。\n\n失败处理\n显示重试入口。",
            "sections": ["功能入口", "失败处理"],
            "missingSections": [],
            "missingAttachments": [],
            "coverage": "complete",
        }

    def validate(self, payload=None, **kwargs):
        return reading.validate_snapshot(
            self.source, self.payload if payload is None else payload,
            read_at=kwargs.get("read_at", "2026-09-09T12:00:00Z"),
            method=kwargs.get("method", "desktop_import"),
        )

    def test_default_states_do_not_share_mutable_values(self) -> None:
        state = reading.default_state()
        self.assertEqual(state, {"status": "idle", "errorCode": "", "error": "", "logs": [], "snapshot": None})
        state["logs"].append("one task")
        self.assertEqual(reading.default_state()["logs"], [])

    def test_missing_settings_preserve_compatible_defaults(self) -> None:
        expected = {"defaultReader": "auto", "attachmentPolicy": "optional"}
        for value in (None, {}):
            with self.subTest(value=value):
                self.assertEqual(reading.normalize_settings(value), expected)
        settings = reading.normalize_settings()
        settings["defaultReader"] = "manual_import"
        self.assertEqual(reading.normalize_settings(), expected)

    def test_supported_settings_are_normalized_without_mutating_input(self) -> None:
        for reader in ("auto", "manual_import", "lark_cli", "codex_read_only"):
            for policy in ("optional", "required"):
                with self.subTest(reader=reader, policy=policy):
                    source = {"defaultReader": reader, "attachmentPolicy": policy}
                    normalized = reading.normalize_settings(source)
                    self.assertEqual(normalized, source)
                    self.assertIsNot(normalized, source)
        self.assertEqual(reading.normalize_settings({"attachmentPolicy": "required"}), {
            "defaultReader": "auto", "attachmentPolicy": "required",
        })
        self.assertEqual(reading.normalize_settings({"defaultReader": "manual_import"}), {
            "defaultReader": "manual_import", "attachmentPolicy": "optional",
        })

    def test_invalid_settings_and_executable_configuration_are_rejected(self) -> None:
        variants = [False, 1, [], "manual_import", {"command": "credential-secret"}, {"path": "/private/credential-secret"}, {"attachmentPolcy": "required"}]
        for field in ("defaultReader", "attachmentPolicy"):
            for value in (None, True, 1, [], {}, "", "unknown", "credential-secret", " OPTIONAL "):
                variants.append({field: value})
        variants.append({"defaultReader": "chrome_mcp"})
        for value in variants:
            with self.subTest(value=value), self.assertRaises(reading.SourceReadError) as caught:
                reading.normalize_settings(value)
            self.assertNotIn("credential-secret", str(caught.exception))

    def test_attachment_policy_validation_is_strict(self) -> None:
        for value in ("optional", "required"):
            self.assertEqual(reading.normalize_attachment_policy(value), value)
        for value in (None, True, False, [], {}, 1, "", "REQUIRED", " required", "unknown"):
            with self.subTest(value=value), self.assertRaises(reading.SourceReadError):
                reading.normalize_attachment_policy(value)

    def test_only_supported_link_readers_require_reading(self) -> None:
        for reader in ("manual_import", "chrome_mcp", "lark_cli"):
            self.assertTrue(reading.requires_read({**self.source, "reader": reader}))
        for source in (None, [], "link", {}, {**self.source, "type": "text"}, {**self.source, "reader": "codex_read_only"}, {**self.source, "reader": []}):
            with self.subTest(source=source):
                self.assertFalse(reading.requires_read(source))

    def test_valid_snapshot_binds_metadata_and_digest(self) -> None:
        original = dict(self.payload)
        snapshot = self.validate(method="automated")
        self.assertEqual(snapshot["url"], self.source["url"])
        self.assertEqual(snapshot["reader"], "chrome_mcp")
        self.assertEqual(snapshot["readAt"], "2026-09-09T12:00:00Z")
        self.assertEqual(snapshot["method"], "automated")
        self.assertEqual(snapshot["digest"], hashlib.sha256(self.payload["body"].encode("utf-8")).hexdigest())
        self.assertTrue(reading.snapshot_ready(snapshot))
        snapshot["sections"].append("another section")
        self.assertEqual(self.payload, original)

    def test_manual_import_accepts_content_from_any_supported_link_source(self) -> None:
        for reader in ("manual_import", "chrome_mcp", "lark_cli"):
            with self.subTest(reader=reader):
                self.source["reader"] = reader
                snapshot = self.validate(method="manual_import")
                self.assertEqual(snapshot["reader"], reader)
                self.assertEqual(snapshot["method"], "manual_import")
                self.assertTrue(reading.snapshot_ready(snapshot))

    def test_content_is_trimmed_without_rewriting_body(self) -> None:
        snapshot = self.validate({**self.payload, "title": "  标题  ", "body": " \n实际正文\n  保留缩进\n ", "sections": ["  章节  "]})
        self.assertEqual(snapshot["title"], "标题")
        self.assertEqual(snapshot["body"], "实际正文\n  保留缩进")
        self.assertEqual(snapshot["sections"], ["章节"])
        self.assertEqual(snapshot["digest"], hashlib.sha256(snapshot["body"].encode("utf-8")).hexdigest())

    def test_forged_url_and_fragment_changes_are_rejected(self) -> None:
        for url in (
            "https://example.feishu.cn/wiki/other#part", "https://evil.example/wiki/original#part",
            self.source["url"].replace("#part", "#other"), self.source["url"] + " ",
            "https://example.feishu.cn.evil.example/wiki/original#part",
        ):
            with self.subTest(url=url), self.assertRaises(reading.SourceReadError):
                self.validate({**self.payload, "url": url})

    def test_invalid_and_credential_urls_are_rejected_without_echoing(self) -> None:
        for url in ("file:///private/secret", "javascript:alert(1)", "https:///missing-host", "https://user:credential-secret@example.com/doc", "https://example.com:99999/doc", "https://exa\nmple.com/doc"):
            self.source["url"] = url
            with self.subTest(url=url), self.assertRaises(reading.SourceReadError) as caught:
                self.validate({**self.payload, "url": url})
            self.assertNotIn(url, str(caught.exception))
            self.assertNotIn("credential-secret", str(caught.exception))

    def test_empty_or_missing_body_and_summary_only_are_rejected(self) -> None:
        variants = [{**self.payload, "body": body} for body in (None, "", " \n\t", [], 123)]
        variants.append({key: value for key, value in self.payload.items() if key != "body"})
        variants.append({"title": "摘要", "summary": "summary is not a document", "url": self.source["url"]})
        for payload in variants:
            with self.subTest(payload=payload), self.assertRaises(reading.SourceReadError):
                self.validate(payload)

    def test_invalid_shapes_fields_and_limits_are_rejected(self) -> None:
        variants = [[], "document", {**self.payload, "title": " "}, {**self.payload, "title": "t" * 501}, {**self.payload, "body": "b" * 240001}, {**self.payload, "summary": "untrusted extra"}, {**self.payload, "digest": "forged"}, {**self.payload, "reader": "forged"}, {**self.payload, "coverage": []}, {**self.payload, "coverage": "unknown"}]
        for field in ("sections", "missingSections", "missingAttachments"):
            for invalid in (None, "not an array", ["item"] * 201, ["x" * 501], [" "], [1]):
                variants.append({**self.payload, field: invalid})
            variants.append({key: value for key, value in self.payload.items() if key != field})
        for index, payload in enumerate(variants):
            with self.subTest(index=index), self.assertRaises(reading.SourceReadError):
                self.validate(payload)

    def test_exact_size_limits_are_accepted(self) -> None:
        snapshot = self.validate({**self.payload, "title": "t" * 500, "body": "b" * 240000, "sections": ["s" * 500] * 200})
        self.assertTrue(reading.snapshot_ready(snapshot))

    def test_partial_or_missing_content_is_saved_but_never_ready(self) -> None:
        for changes in (
            {"coverage": "partial"}, {"missingSections": ["埋点"]},
            {"coverage": "partial", "missingAttachments": ["平台差异截图"]},
            {"missingSections": ["埋点"], "missingAttachments": ["截图"]},
        ):
            with self.subTest(changes=changes):
                snapshot = self.validate({**self.payload, **changes})
                self.assertEqual(snapshot["coverage"], "partial")
                self.assertEqual(snapshot["body"], self.payload["body"])
                self.assertFalse(reading.snapshot_ready(snapshot))

    def test_malformed_snapshot_never_passes_the_ready_gate(self) -> None:
        valid = self.validate()
        for snapshot in (None, [], "complete", {}, {**valid, "coverage": "unknown"}, {**valid, "body": " "}, {**valid, "body": 42}, {**valid, "body": "b" * 240001}, {**valid, "missingSections": ["missing"]}, {**valid, "missingSections": None}, {**valid, "missingAttachments": ""}):
            with self.subTest(snapshot_type=type(snapshot).__name__):
                self.assertFalse(reading.snapshot_ready(snapshot))
        for field in ("missingSections", "missingAttachments"):
            self.assertFalse(reading.snapshot_ready({key: value for key, value in valid.items() if key != field}))

    def test_complete_body_is_ready_with_unread_attachments_preserved(self) -> None:
        snapshot = self.validate({**self.payload, "missingAttachments": ["参考文档", "截图"]})
        self.assertEqual(snapshot["coverage"], "complete")
        self.assertEqual(snapshot["missingAttachments"], ["参考文档", "截图"])
        self.assertTrue(reading.snapshot_ready(snapshot))

    def test_required_attachments_block_readiness_without_changing_body_coverage(self) -> None:
        snapshot = self.validate({**self.payload, "missingAttachments": ["功能流程截图"]})
        self.assertEqual(snapshot["coverage"], "complete")
        self.assertTrue(reading.snapshot_ready(snapshot, attachment_policy="optional"))
        self.assertFalse(reading.snapshot_ready(snapshot, attachment_policy="required"))
        self.assertEqual(snapshot["missingAttachments"], ["功能流程截图"])
        complete = self.validate()
        self.assertTrue(reading.snapshot_ready(complete, attachment_policy="required"))

    def test_required_attachments_never_relax_body_requirements(self) -> None:
        valid = self.validate()
        for changes in ({"body": ""}, {"coverage": "partial"}, {"missingSections": ["埋点"]}, {"missingAttachments": None}):
            with self.subTest(changes=changes):
                self.assertFalse(reading.snapshot_ready({**valid, **changes}, attachment_policy="required"))

    def test_readiness_rejects_invalid_policy_even_without_a_snapshot(self) -> None:
        for snapshot in (None, self.validate()):
            for policy in (None, [], "requred"):
                with self.subTest(policy=policy), self.assertRaises(reading.SourceReadError):
                    reading.snapshot_ready(snapshot, attachment_policy=policy)

    def test_metadata_cannot_be_spoofed_or_missing(self) -> None:
        for method in ("clipboard", [], None, ""):
            with self.subTest(method=method), self.assertRaises(reading.SourceReadError):
                self.validate(method=method)
        for read_at in (None, [], "", " "):
            with self.subTest(read_at=read_at), self.assertRaises(reading.SourceReadError):
                self.validate(read_at=read_at)
        self.source["reader"] = "codex_read_only"
        with self.assertRaises(reading.SourceReadError):
            self.validate()

    def test_error_categories_do_not_confuse_codex_auth_with_site_login(self) -> None:
        cases = (
            ("Codex auth token is unavailable. Please sign in.", "codex_auth_missing"),
            ("Trusted RPC dependency must resolve within a configured trusted code path; permission denied", "plugin_load_failed"),
            ("Chrome 未连接", "chrome_not_connected"),
            ("Chrome extension not connected", "chrome_not_connected"),
            ("reader_unavailable", "reader_unavailable"),
            ("Please signin to view document", "document_login_required"),
            ("请登录飞书", "document_login_required"),
            ("Permission denied", "document_permission_denied"),
            ("当前账号无权访问", "document_permission_denied"),
            ("Only partial content was loaded", "read_incomplete"),
            ("文档正文为空或缺失，只有摘要不能完成读取。", "read_incomplete"),
            ("Unknown timeout", "read_failed"),
        )
        for raw, expected in cases:
            with self.subTest(expected=expected):
                code, message = reading.classify_error(raw + " credential-secret-123")
                self.assertEqual(code, expected)
                self.assertNotIn("credential-secret-123", message)
                if code == "codex_auth_missing":
                    self.assertNotIn("飞书", message)
                    self.assertNotIn("Chrome", message)
        for raw in (None, [], {}):
            self.assertEqual(reading.classify_error(raw)[0], "read_failed")

    def test_lark_keychain_failure_overrides_incorrect_codex_auth_code(self) -> None:
        raw = (
            "codex_auth_missing lark-cli 只读节点解析及 auth status 失败："
            "keychain Get failed: keychain not initialized; credential-secret-123"
        )
        for reader in (None, "lark_cli"):
            with self.subTest(reader=reader):
                code, message = reading.classify_error(raw, reader=reader)
                self.assertEqual(code, "lark_credentials_unavailable")
                self.assertIn("Lark CLI", message)
                self.assertIn("钥匙串", message)
                for forbidden in ("credential-secret-123", "keychain Get failed", "Codex", "Chrome"):
                    self.assertNotIn(forbidden, message)

    def test_keychain_failure_requires_lark_context(self) -> None:
        for raw in ("keychain Get failed", "keychain not initialized"):
            with self.subTest(raw=raw):
                self.assertEqual(reading.classify_error(raw, reader="lark_cli")[0], "lark_credentials_unavailable")
                self.assertEqual(reading.classify_error(raw, reader="chrome_mcp")[0], "read_failed")
                self.assertEqual(reading.classify_error(raw)[0], "read_failed")

    def test_reader_context_preserves_real_codex_and_chrome_errors(self) -> None:
        cases = (
            ("Codex auth token is unavailable. Please sign in.", "codex_auth_missing"),
            ("Chrome extension not connected", "chrome_not_connected"),
            ("Trusted RPC dependency must resolve within a configured trusted code path", "plugin_load_failed"),
        )
        for reader in ("lark_cli", "chrome_mcp"):
            for raw, expected in cases:
                with self.subTest(reader=reader, raw=raw):
                    self.assertEqual(reading.classify_error(raw, reader=reader)[0], expected)

    def test_explicit_lark_error_code_uses_safe_guidance(self) -> None:
        code, message = reading.classify_error("lark_credentials_unavailable credential-secret-123")
        self.assertEqual(code, "lark_credentials_unavailable")
        self.assertNotIn("credential-secret-123", message)

    def test_generic_error_guidance_does_not_require_a_specific_import_provider(self) -> None:
        for code in ("reader_unavailable", "read_incomplete", "read_failed"):
            with self.subTest(code=code):
                _, message = reading.classify_error(code)
                for forbidden in ("Chrome", "桌面", "未读附件不影响"):
                    self.assertNotIn(forbidden, message)
        self.assertIn("必读的附件", reading.classify_error("read_incomplete")[1])

    def test_schema_has_a_strict_document_contract_and_all_categories(self) -> None:
        schema = json.loads((Path(__file__).resolve().parents[1] / "schemas" / "source-read.schema.json").read_text(encoding="utf-8"))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        self.assertEqual(schema["properties"]["status"]["enum"], ["ready", "blocked"])
        alternatives = schema["properties"]["document"]["anyOf"]
        document = next(item for item in alternatives if item["type"] == "object")
        self.assertIn({"type": "null"}, alternatives)
        self.assertFalse(document["additionalProperties"])
        self.assertEqual(set(document["required"]), reading.PAYLOAD_FIELDS)
        self.assertEqual(set(document["properties"]), reading.PAYLOAD_FIELDS)
        codes = schema["properties"]["errorCode"]["enum"]
        self.assertIn("lark_credentials_unavailable", codes)
        for code in codes:
            if code:
                self.assertEqual(reading.classify_error(code)[0], code)


if __name__ == "__main__":
    unittest.main()
