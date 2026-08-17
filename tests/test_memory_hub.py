from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from memory_client import MemoryClientError, normalize_repository_url
from memory_hub import MemoryStore


TOOL_DIR = Path(__file__).resolve().parents[1]
PLUGIN_MCP = TOOL_DIR / "plugins" / "devconductor-memory" / "scripts" / "memory_mcp.py"


class RepositoryIdentityTests(unittest.TestCase):
    def test_ssh_https_and_scp_remotes_share_one_project_key(self) -> None:
        values = [
            normalize_repository_url("git@github.com:CandyAlla/project-flow-console.git"),
            normalize_repository_url("ssh://git@github.com/CandyAlla/project-flow-console.git"),
            normalize_repository_url("https://github.com/candyalla/project-flow-console.git"),
        ]
        self.assertEqual({item["projectKey"] for item in values}, {"github.com/candyalla/project-flow-console"})

    def test_local_paths_are_never_shared_identity(self) -> None:
        for value in ("/Users/alice/project", "../project", "file:///tmp/project", "C:\\project"):
            with self.subTest(value=value), self.assertRaises(MemoryClientError):
                normalize_repository_url(value)


class MemoryStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="devconductor-memory-")
        self.store = MemoryStore(Path(self.temp.name) / "memory.db")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def create(self, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "teamId": "studio",
            "projectKey": "github.com/example/project-a",
            "repositoryUrl": "https://github.com/example/project-a.git",
            "scope": "project",
            "kind": "decision",
            "title": "Use one state owner",
            "content": "The controller owns workflow state.",
            "status": "active",
            "sourceKey": "test:decision:1",
        }
        payload.update(overrides)
        return self.store.create(payload)

    def test_search_respects_project_team_and_candidate_boundaries(self) -> None:
        own = self.create()
        shared = self.create(
            scope="team", title="Shared release rule", content="Always review release notes.",
            sourceKey="test:team:1",
        )
        other = self.create(
            projectKey="github.com/example/project-b", repositoryUrl="https://github.com/example/project-b.git",
            title="Other project detail", sourceKey="test:other:1",
        )
        candidate = self.create(title="Unreviewed idea", status="candidate", sourceKey="test:candidate:1")
        values = self.store.search({
            "teamId": "studio", "projectKey": "github.com/example/project-a", "query": "state release idea detail",
            "scopes": ["project", "team"], "limit": 10, "maxChars": 10000,
        })
        ids = {item["id"] for item in values}
        self.assertIn(own["id"], ids)
        self.assertIn(shared["id"], ids)
        self.assertNotIn(other["id"], ids)
        self.assertNotIn(candidate["id"], ids)

    def test_source_key_makes_publication_idempotent(self) -> None:
        first = self.create()
        second = self.create(content="Updated reviewed content")
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["content"], "Updated reviewed content")

    def test_deprecated_memory_is_not_recalled_and_same_source_can_reactivate(self) -> None:
        memory = self.create()
        query = {
            "teamId": "studio",
            "projectKey": "github.com/example/project-a",
            "query": "state owner",
            "scopes": ["project"],
            "limit": 10,
            "maxChars": 10000,
        }
        self.assertEqual({item["id"] for item in self.store.search(query)}, {memory["id"]})

        deprecated = self.store.set_status(str(memory["id"]), "deprecated")
        self.assertEqual(deprecated["status"], "deprecated")
        self.assertEqual(self.store.search(query), [])

        reactivated = self.create(content="The controller still owns workflow state.")
        self.assertEqual(reactivated["id"], memory["id"])
        self.assertEqual(reactivated["status"], "active")
        self.assertEqual({item["id"] for item in self.store.search(query)}, {memory["id"]})


class PluginMcpTests(unittest.TestCase):
    def test_mcp_initializes_and_lists_memory_tools_without_network(self) -> None:
        requests = "\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26"}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        ]) + "\n"
        result = subprocess.run(["python3", str(PLUGIN_MCP)], input=requests, text=True, capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        names = {item["name"] for item in responses[1]["result"]["tools"]}
        self.assertEqual(
            names,
            {"memory_search", "knowledge_search", "memory_read", "memory_capture", "memory_publish_candidate"},
        )


if __name__ == "__main__":
    unittest.main()
