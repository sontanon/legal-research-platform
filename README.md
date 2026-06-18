# Legal Research Platform

Long-running legal research agent integration platform — MCP adapter with
per-client feature gating, MCP Apps widgets, and a mocked backend for
integration testing across Claude Desktop, Microsoft Copilot, and Amazon Quick.

> **Not legal advice.** All agent output is simulated and fabricated. This is
> an integration testing scaffold, not a production legal tool.

## What this is

A legal research agent that takes ~2 / ~5 / ~12 minutes per job (quick /
standard / deep tiers) — far too long for a synchronous MCP tool call. This
repo contains the mock backend and the MCP adapter that wraps it with
per-client feature gating, plus the full research and design documentation for
the integration strategy.

The core challenge: different LLM clients (Claude Desktop, Microsoft Copilot,
Amazon Quick) have wildly different MCP capabilities — some support MCP Apps
widgets, some don't; some have hard tool-call timeouts, some don't; some
support A2A, most don't. The adapter detects which client is calling and
selects the right recipe per client.

## Repo structure

```
legal-research-platform/
├── README.md                   this file
├── .gitignore
├── docs/
│   ├── integration-research-and-design.md   main living design doc (MCP + A2A strategy)
│   └── a2a-copilot-integration-report.md    A2A protocol + Copilot integration reference
├── legal-research-agent/       mock backend (FastAPI, non-deterministic timings)
└── legal-research-mcp/         MCP adapter (FastMCP, per-client gating, widgets)
```

## Quickstart

```bash
# 1. Start the mock backend (port 8000)
cd legal-research-agent
uv sync
uv run legal-research-agent                       # real timings (~2/5/12 min)
# or: MOCK_TIME_SCALE=0.01 uv run legal-research-agent   # ~100x faster for dev

# 2. Start the MCP adapter (port 8001, Streamable HTTP)
cd ../legal-research-mcp
uv sync
uv run legal-research-mcp
```

The adapter is now at `http://127.0.0.1:8001/mcp` (Streamable HTTP).

For Claude Desktop widget testing (stdio, no tunnel needed):
```bash
uv run legal-research-mcp-stdio    # runs the same server in stdio mode
```
Point `claude_desktop_config.json` at this command — see
[docs/integration-research-and-design.md §22](docs/integration-research-and-design.md).

## Tools

| Tool | Purpose |
|---|---|
| `submit_research(query, effort)` | Start a job; returns `{job_id, status}` fast. On UI clients, opens a progress widget. |
| `get_status(job_id)` | Check progress. Three-tool clients: blocks ~25s streaming progress. Widget clients: returns immediately. |
| `get_result(job_id)` | Fetch the final structured report. |
| `cancel_research(job_id)` | Cancel a running job. |

## Per-client recipes

The adapter's `ClientProfileResolver` detects the client and selects a recipe:

| Detected client | Recipe | Notes |
|---|---|---|
| Claude Desktop | widget-poll | Widget polls `get_status` via `callServerTool`; 240s cap on `tools/call` return only |
| Microsoft Copilot | widget-poll | No widget SSE (CSP blocks `connectDomains`); poll via `tools/call` (≤60/min) |
| Amazon Quick | three-tool | No UI/Tasks/Elicitation; 25s hold-open (60s actual timeout) |
| Unknown (no UI) | three-tool | Safe default |
| Unknown (UI-capable) | widget-poll | Poll is the portable default |

See [docs/integration-research-and-design.md](docs/integration-research-and-design.md)
for the full design: the per-client fork (§11), the three recipes (§12), the
profile resolver (§13), the deep-tier policy (§14), FastMCP implementation
notes (§15), and the testing plan for Linux (§20) and Windows (§21).

## Testing

**Fastest widget validation (any OS):** VS Code Copilot Chat + `.vscode/mcp.json`
pointing at `http://127.0.0.1:8001/mcp` — no tunnel, no publish. See §21.

**Protocol sanity:** `npx @modelcontextprotocol/inspector` → Streamable HTTP →
`http://127.0.0.1:8001/mcp`.

Full testing matrix and recommended order in
[docs/integration-research-and-design.md §20-22](docs/integration-research-and-design.md).

## Documentation

- **[docs/integration-research-and-design.md](docs/integration-research-and-design.md)** —
  the main design document: MCP/A2A landscape research (June 2026), blind spots,
  per-client recipes, ClientProfileResolver design, FastMCP implementation notes,
  testing plans for Linux and Windows.
- **[docs/a2a-copilot-integration-report.md](docs/a2a-copilot-integration-report.md)** —
  focused reference on the A2A protocol and Microsoft Copilot integration (Agent
  Cards, task lifecycle, `a2a-sdk`, auth). The post-MVP A2A adapter will build on
  this.
