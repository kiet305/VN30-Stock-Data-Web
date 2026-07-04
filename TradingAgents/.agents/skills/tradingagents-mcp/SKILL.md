---
name: tradingagents-mcp
description: Use when inspecting or using the local TradingAgents MCP server, its report-reading tools, project context tools, `.codex/config.toml` MCP configuration, or Codex MCP troubleshooting in this repository.
---

# TradingAgents MCP

This repository provides a local read-only MCP server configured in `.codex/config.toml`.

## Server

```toml
[mcp_servers.tradingagents]
command = "python"
args = ["scripts/codex_mcp_server.py"]
cwd = "."
```

## Tools

- `get_project_context`: summarize the active research flow and key files.
- `list_reports`: list generated markdown reports under `reports/`.
- `read_report`: read a report by filename from `reports/`.
- `check_flow`: check import health, SDK availability, and config presence.

## Rules

- Tools are read-only.
- Do not expose secrets or `.env` values.
- Use MCP tools for local report discovery before scanning large directories manually.

