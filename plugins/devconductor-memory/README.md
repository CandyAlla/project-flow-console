# DevConductor Memory Codex Plugin

This plugin connects Codex to the same Memory Hub used by DevConductor. It identifies a project from Git `origin`, so different local checkout paths still share the same project memory.

Set these variables before starting Codex:

```bash
export DEVCONDUCTOR_MEMORY_ENDPOINT="https://memory.example.com"
export DEVCONDUCTOR_MEMORY_API_KEY="replace-with-your-team-key"
export DEVCONDUCTOR_MEMORY_TEAM_ID="your-team"
export DEVCONDUCTOR_MEMORY_USER_ID="your-stable-user-id"
```

For the local DevConductor Hub, the endpoint defaults to `http://127.0.0.1:4328`; a local API-key file is discovered automatically when the plugin is used directly from this repository.

The hooks perform bounded best-effort recall. MCP tools provide explicit search, read, capture, and candidate publication. Real memories and credentials are stored by the Memory Hub and are not part of this plugin directory.
