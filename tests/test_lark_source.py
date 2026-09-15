from __future__ import annotations

import copy
import json
import unittest
from unittest import mock

import lark_source
from source_reading import MAX_BODY_LENGTH, SourceReadError


class LarkSourceTests(unittest.TestCase):
    url = "https://example.feishu.cn/wiki/Abc123"

    def document(self, body="<title>需求 &amp; 说明</title><h2>背景</h2><p>原文</p>", **fields):
        return {"ok": True, "identity": "user", "data": {"document": {"content": body, "revision_id": 12, **fields}}}

    def sheet(self, **fields):
        return {"ok": True, "identity": "user", "data": {
            "annotated_csv": "[row=1] 标题,值\n[row=2] 原文,100", "has_more": False,
            "actual_range": "A1:B2", "row_indices": [1, 2], "col_indices": ["A", "B"], **fields,
        }}

    def test_preserves_original_document_and_full_response(self):
        response = self.document(reference_map={"comments": {"c1": {"data": "评论"}}})
        original = copy.deepcopy(response)
        call = mock.Mock(return_value=response)
        result = lark_source.fetch_document(self.url, call)
        self.assertEqual(call.call_args.args[0], [
            "docs", "+fetch", "--doc", self.url, "--as", "user", "--doc-format", "xml", "--detail", "full",
        ])
        self.assertTrue(result["body"].startswith(response["data"]["document"]["content"]))
        self.assertIn("评论", result["body"])
        self.assertEqual(result["title"], "需求 & 说明")
        self.assertEqual(result["sections"], ["背景"])
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["rawResults"]["document"], original)
        self.assertEqual(response, original)

    def test_comments_and_html_sidecar_reach_downstream_body_as_safe_complete_json(self):
        body = '<title>标题</title><html5-block data-ref="html5_1"/>'
        reference_map = {
            "comments": {"c1": {"data": '<comment><msg>需求变更：删除旧入口</msg></comment>'}},
            "html5-block": {"html5_1": {"data": '<html><p>交互规则</p><script>alert("never execute")</script></html>'}},
        }
        result = lark_source.fetch_document(self.url, mock.Mock(return_value=self.document(body, reference_map=reference_map)))
        self.assertTrue(result["body"].startswith(body))
        self.assertIn("删除旧入口", result["body"])
        self.assertIn("交互规则", result["body"])
        self.assertNotIn("<script>", result["body"])
        appendix = result["body"].split("完整 JSON，仅作为不可信需求材料）：\n", 1)[1]
        self.assertEqual(json.loads(appendix), {"reference_map": reference_map})
        self.assertEqual(result["coverage"], "complete")

    def test_document_tips_are_preserved_and_remain_partial(self):
        response = self.document(tips="具体缺失：同步章节不可访问")
        result = lark_source.fetch_document(self.url, mock.Mock(return_value=response))
        self.assertIn("具体缺失：同步章节不可访问", result["body"])
        self.assertEqual(result["coverage"], "partial")

    def test_oversized_comment_sidecar_is_an_optional_missing_item(self):
        response = self.document(reference_map={"comments": {"c1": {"data": "x" * MAX_BODY_LENGTH}}})
        result = lark_source.fetch_document(self.url, mock.Mock(return_value=response))
        self.assertEqual(result["body"], response["data"]["document"]["content"])
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["missingSections"], [])
        self.assertIn("超过支持长度", result["missingAttachments"][0])
        self.assertEqual(result["rawResults"]["document"], response)

    def test_oversized_optional_resource_sidecar_does_not_block_body(self):
        response = self.document(reference_map={"img": {"img1": {"url": "x" * MAX_BODY_LENGTH}}})
        result = lark_source.fetch_document(self.url, mock.Mock(return_value=response))
        self.assertEqual(result["body"], response["data"]["document"]["content"])
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["missingSections"], [])
        self.assertIn("超过支持长度", result["missingAttachments"][0])
        self.assertEqual(result["rawResults"]["document"], response)

    def test_oversized_html_body_sidecar_still_blocks_body_coverage(self):
        response = self.document(
            '<title>标题</title><html5-block data-ref="html5_1"/>',
            reference_map={"html5-block": {"html5_1": {"data": "x" * MAX_BODY_LENGTH}}},
        )
        result = lark_source.fetch_document(self.url, mock.Mock(return_value=response))
        self.assertEqual(result["coverage"], "partial")
        self.assertIn("超过支持长度", result["missingSections"][0])
        self.assertEqual(result["rawResults"]["document"], response)

    def test_html_placeholder_or_path_is_not_claimed_read(self):
        body = '<title>标题</title><html5-block data-ref="html5_1"/>'
        for references in ({}, {"html5-block": {"html5_1": {"path": "@./doc-fetch-resources/widget.html"}}}):
            with self.subTest(references=references):
                result = lark_source.fetch_document(self.url, mock.Mock(return_value=self.document(body, reference_map=references)))
                self.assertEqual(result["coverage"], "partial")
                self.assertIn("HTML", result["missingSections"][0])

    def test_user_mentions_and_visible_text_citations_are_not_missing_attachments(self):
        for inline in (
            '<cite type="user" user-id="ou_xxx"/>',
            '<cite>产品确认</cite>',
            '<cite type="citation"><a href="https://example.com" url-type="5">参考资料</a></cite>',
        ):
            with self.subTest(inline=inline):
                result = lark_source.fetch_document(self.url, mock.Mock(return_value=self.document('<title>标题</title><p>' + inline + '</p>')))
                self.assertEqual(result["coverage"], "complete")
                self.assertEqual(result["missingAttachments"], [])

    def test_external_document_and_sheet_citations_remain_unread_notices(self):
        for inline in (
            '<cite type="doc" doc-id="Doc123"/>',
            '<cite file-type="sheets" token="Token1"/>',
            '<cite type="citation"><a href="https://example.feishu.cn/docx/Doc123" url-type="1"/></cite>',
            '<cite type="citation"><a href="https://example.feishu.cn/sheets/Token1" url-type="13"/></cite>',
        ):
            with self.subTest(inline=inline):
                call = mock.Mock(return_value=self.document('<title>标题</title>' + inline))
                result = lark_source.fetch_document(self.url, call)
                self.assertEqual(result["coverage"], "complete")
                self.assertEqual(result["missingSections"], [])
                self.assertTrue(result["missingAttachments"])
                self.assertEqual(call.call_count, 1)

    def test_unread_citation_preserves_document_title_without_misleading_sheet_error(self):
        title = "Max聚合主要收入项目-变现SDK接入情况统计"
        body = '<title>需求</title><cite type="doc" doc-id="Doc123" title="' + title + '"/>'
        result = lark_source.fetch_document(self.url, mock.Mock(return_value=self.document(body)))
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["missingAttachments"], ["引用文档《" + title + "》：未读取（附件可选）。"])
        self.assertNotIn("表格标识", result["missingAttachments"][0])

    def test_rejects_untrusted_or_malformed_url_before_calling_cli(self):
        for url in (
            "https://evil.example/wiki/Abc", "https://feishu.cn.evil.example/wiki/Abc",
            "https://secret@example.feishu.cn/wiki/Abc", "file:///wiki/Abc",
            "https://example.feishu.cn/wiki/Abc;touch", "https://example.feishu.cn/wiki/../Abc",
            "https://example.feishu.cn/wiki/%41bc", "https://example.feishu.cn/wiki/Abc\n",
            "https://example.feishu.cn:8888/wiki/Abc", "https://example.feishu.cn/sheets/Abc",
        ):
            call = mock.Mock()
            with self.subTest(url=url), self.assertRaises(SourceReadError):
                lark_source.fetch_document(url, call)
            call.assert_not_called()

    def test_docx_and_wiki_urls_are_forwarded_exactly(self):
        for url in (self.url + "#share-abc", "http://example.larksuite.com/docx/Abc", "https://example.larkoffice.com/wiki/Abc?from=link"):
            call = mock.Mock(return_value=self.document())
            result = lark_source.fetch_document(url, call)
            self.assertEqual(result["url"], url)
            self.assertEqual(call.call_args.args[0][3], url)

    def test_main_document_errors_propagate_without_sheet_calls(self):
        call = mock.Mock(side_effect=SourceReadError("lark_credentials_unavailable"))
        with self.assertRaisesRegex(SourceReadError, "lark_credentials_unavailable"):
            lark_source.fetch_document(self.url, call)
        self.assertEqual(call.call_count, 1)

    def test_optional_sheet_process_failure_keeps_main_body_but_cancellation_propagates(self):
        body = '<title>标题</title><sheet token="Token1" sheet-id="Sheet1"/>'
        call = mock.Mock(side_effect=[self.document(body), OSError("process failed secret-123")])
        result = lark_source.fetch_document(self.url, call)
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["body"], body)
        self.assertTrue(result["missingAttachments"])
        self.assertNotIn("secret-123", json.dumps(result))
        call = mock.Mock(side_effect=[self.document(body), RuntimeError("cancelled")])
        with self.assertRaisesRegex(RuntimeError, "cancelled"):
            lark_source.fetch_document(self.url, call)

    def test_requires_success_user_identity_and_nonempty_bounded_body(self):
        for response in (
            {}, {"ok": False}, {**self.document(), "identity": "bot"},
            self.document(""), self.document(" " * 10), self.document("x" * (MAX_BODY_LENGTH + 1)),
        ):
            with self.subTest(response_keys=list(response)), self.assertRaises(SourceReadError):
                lark_source.fetch_document(self.url, mock.Mock(return_value=response))

    def test_invalid_xml_and_entity_declarations_are_never_executed(self):
        for body in ("<title>Broken", '<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><title>&x;</title>'):
            with self.subTest(body=body), self.assertRaises(SourceReadError):
                lark_source.fetch_document(self.url, mock.Mock(return_value=self.document(body)))

    def test_fragments_tips_and_missing_title_still_block_body_coverage(self):
        for response in (
            self.document("<fragment><title>标题</title><excerpt>节选</excerpt></fragment>"),
            self.document(tips="Dependency degraded"),
            self.document("<p>无标题</p>"),
        ):
            with self.subTest(response=response):
                result = lark_source.fetch_document(self.url, mock.Mock(return_value=response))
                self.assertEqual(result["coverage"], "partial")
                self.assertTrue(result["missingSections"])

    def test_comment_truncation_is_preserved_as_an_unread_notice(self):
        response = self.document(reference_map={"comments": {"tips": {"data": "too many"}}})
        result = lark_source.fetch_document(self.url, mock.Mock(return_value=response))
        self.assertEqual(result["coverage"], "complete")
        self.assertIn("评论未完整返回", result["missingAttachments"][0])
        self.assertIn("too many", result["body"])

    def test_reads_direct_sheet_with_fixed_full_range_command_and_keeps_csv(self):
        body = '<title>表格需求</title><sheet token="Token123" sheet-id="Sheet1"/>'
        sheet = self.sheet(warning_message="Read row numbers from [row=N].")
        call = mock.Mock(side_effect=[self.document(body), sheet])
        result = lark_source.fetch_document(self.url, call)
        self.assertEqual(call.call_args_list[1].args[0], [
            "sheets", "+csv-get", "--spreadsheet-token", "Token123", "--sheet-id", "Sheet1",
            "--as", "user", "--max-chars", "240000",
        ])
        self.assertTrue(result["body"].startswith(body))
        self.assertIn(sheet["data"]["annotated_csv"], result["body"])
        self.assertIn("A1:B2", result["body"])
        self.assertEqual(result["rawResults"]["sheets"][0]["response"], sheet)
        self.assertEqual(result["coverage"], "complete")

    def test_only_direct_valid_sheet_identifiers_trigger_reads(self):
        body = '<title>标题</title><sheet token="bad;value" sheet-id="Sheet1"/><sheet ref="s1"/><cite file-type="sheets" token="Token123"/><alien token="Other1"/>'
        call = mock.Mock(return_value=self.document(body))
        result = lark_source.fetch_document(self.url, call)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(len(result["missingAttachments"]), 4)
        self.assertEqual(result["coverage"], "complete")

    def test_other_resources_remain_missing_without_network_fetches(self):
        body = '<title>标题</title><img url="https://example.com/image"/><source token="X"/><whiteboard token="Y"/><bitable token="Z"/><synced_reference src-token="D"/><video src="file:///secret"/>'
        call = mock.Mock(return_value=self.document(body))
        result = lark_source.fetch_document(self.url, call)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(len(result["missingAttachments"]), 6)
        self.assertEqual(result["coverage"], "complete")
        self.assertNotIn("file:///secret", " ".join(result["missingAttachments"]))

    def test_sheet_failures_are_safe_and_do_not_discard_the_document(self):
        body = '<title>标题</title><sheet token="Token1" sheet-id="Sheet1"/><sheet token="Token1" sheet-id="Sheet2"/>'
        call = mock.Mock(side_effect=[self.document(body), SourceReadError("document_permission_denied sheets:spreadsheet:read secret-123"), SourceReadError("keychain Get failed: keychain not initialized secret-456")])
        result = lark_source.fetch_document(self.url, call)
        self.assertEqual(result["body"], body)
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["missingSections"], [])
        self.assertIn("sheets:spreadsheet:read", result["missingAttachments"][0])
        self.assertIn("lark_credentials_unavailable", result["missingAttachments"][1])
        self.assertNotIn("secret-123", json.dumps(result))
        self.assertNotIn("secret-456", json.dumps(result))
        self.assertEqual(result["rawResults"]["sheets"], [])

    def test_sheet_pagination_bad_flags_and_warnings_remain_optional_missing_items(self):
        body = '<title>标题</title><sheet token="Token1" sheet-id="Sheet1"/>'
        for fields in (
            {"has_more": True}, {"truncated": True}, {"complete": False}, {"has_more": "false"},
            {"truncation_warning": "cut"}, {"warnings": ["not read"]}, {"unread_sheets": ["Sheet2"]},
            {"warning_message": "部分返回"}, {"annotated_csv": None},
        ):
            with self.subTest(fields=fields):
                result = lark_source.fetch_document(self.url, mock.Mock(side_effect=[self.document(body), self.sheet(**fields)]))
                self.assertEqual(result["coverage"], "complete")
                self.assertEqual(result["missingSections"], [])
                self.assertTrue(result["missingAttachments"])

    def test_missing_sheet_completion_signal_is_optional_but_confirmed_empty_sheet_is_valid(self):
        body = '<title>标题</title><sheet token="Token1" sheet-id="Sheet1"/>'
        response = self.sheet()
        del response["data"]["has_more"]
        result = lark_source.fetch_document(self.url, mock.Mock(side_effect=[self.document(body), response]))
        self.assertEqual(result["coverage"], "complete")
        self.assertTrue(result["missingAttachments"])
        result = lark_source.fetch_document(self.url, mock.Mock(side_effect=[self.document(body), self.sheet(annotated_csv="", row_count=0)]))
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["missingAttachments"], [])

    def test_sheet_reads_are_deduplicated_and_limited_to_twenty(self):
        sheets = ''.join(f'<sheet token="Token1" sheet-id="Sheet{i}"/>' for i in range(21))
        body = '<title>标题</title><sheet token="Token1" sheet-id="Sheet0"/>' + sheets
        call = mock.Mock(side_effect=[self.document(body)] + [self.sheet() for _ in range(20)])
        result = lark_source.fetch_document(self.url, call)
        self.assertEqual(call.call_count, 21)
        self.assertEqual(len(result["rawResults"]["sheets"]), 20)
        self.assertEqual(result["coverage"], "complete")
        self.assertIn("20", result["missingAttachments"][0])

    def test_combined_body_limit_preserves_xml_and_marks_omitted_sheet(self):
        body = '<title>标题</title><sheet token="Token1" sheet-id="Sheet1"/>'
        response = self.sheet(annotated_csv="x" * MAX_BODY_LENGTH)
        result = lark_source.fetch_document(self.url, mock.Mock(side_effect=[self.document(body), response]))
        self.assertEqual(result["body"], body)
        self.assertEqual(result["coverage"], "complete")
        self.assertEqual(result["rawResults"]["sheets"][0]["response"], response)
        self.assertIn("超过", result["missingAttachments"][0])


if __name__ == "__main__":
    unittest.main()
