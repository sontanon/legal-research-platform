# Legal Research MCP Adapter

FastMCP server that wraps the [mock legal research backend](../legal-research-agent/)
into an MCP server with **per-client feature gating** and **MCP Apps widgets**.

## What this is

The legal research agent takes ~2/5/12 minutes (quick/standard/deep) per job —
far too long for a synchronous MCP tool call. This adapter implements the design
from [`../docs/integration-research-and-design.md`](../docs/integration-research-and-design.md):

- **UI-capable clients** (Claude Desktop, Microsoft Copilot, ChatGPT): a live
  progress **widget** (`ui://` MCP Apps) opens automatically. The widget polls
  `get_status` via `tools/call` (postMessage), renders noisy progress, and on
  completion pushes the structured report into the model context via
  `ui/update-model-context`. No orchestrator polling loop.
- **Non-UI clients** (Amazon Quick, CLI): the classic **three-tool pattern**
  (submit → get_status → get_result) where `get_status` holds open for ~25s
  streaming progress, then returns. Prompt-tuned to prevent the LLM from
  answering from its own knowledge or lying about "checking in the background."
- **Deep tier (15m)**: same UX; on close/control-return, an honest "job still
  running — ask me to check again" message. Job persists in the backend's DB.

## Quickstart

```bash
# 1. Start the mock backend (port 8000)
cd ../legal-research-agent
uv sync && uv run legal-research-agent          # or: MOCK_TIME_SCALE=0.01 uv run legal-research-agent

# 2. Start the MCP adapter (port 8001)
cd ../legal-research-mcp
uv sync && uv run legal-research-mcp
```

The adapter is now at `http://127.0.0.1:8001/mcp` (Streamable HTTP).

## Tools

| Tool | Purpose |
|---|---|
| `submit_research(query, effort="standard")` | Start a job; returns `{job_id, status, ...}` fast. On UI clients, also opens the progress widget. |
| `get_status(job_id)` | Check progress. Three-tool clients: blocks ~25s streaming progress, then returns. Widget clients: returns immediately. |
| `get_result(job_id)` | Fetch the final structured report (summary, risk score, citations, sections, disclaimer). |
| `cancel_research(job_id)` | Cancel a running job. |

## Widget

`ui://legal/progress.html` — a self-contained HTML widget with a hand-rolled
postMessage JSON-RPC client (no external assets, no `@modelcontextprotocol/ext-apps`
SDK). Works on both Copilot (which drops `connectDomains` from widget CSP) and
Claude Desktop (which allows it). Polls `get_status` every 1500ms, renders
progress, and on terminal status calls `get_result` + `ui/update-model-context`
+ `ui/message`.

## Per-client detection

The `ClientProfileResolver` in `profiles.py` classifies the client:
1. **Capability gate**: `ctx.client_supports_extension("io.modelcontextprotocol/ui")`
2. **Identity**: `clientInfo.name` + HTTP headers (`x-ms-agentic-protocol`, `User-Agent`)
3. **Safe default**: 25s hold-open, three-tool, no widget

| Detected client | Recipe | Notes |
|---|---|---|
| Claude Desktop / claude.ai | widget-poll | 240s cap on `tools/call` return only; widget polls freely |
| Microsoft Copilot | widget-poll | No widget SSE (CSP blocks); poll via `tools/call` (≤60/min) |
| Amazon Quick | three-tool | No UI/Tasks/Elicitation; 25s hold-open |
| Unknown (no UI) | three-tool | Safe default |
| Unknown (UI-capable) | widget-poll | Poll is the portable default |

## Testing (Linux/Fedora)

See [`../docs/integration-research-and-design.md` §20-22](../docs/integration-research-and-design.md)
for the full testing plan. Quick reference:

```bash
# 1. Protocol sanity (no client license needed)
npx @modelcontextprotocol/inspector
# → Streamable HTTP → http://127.0.0.1:8001/mcp → tools/list → tools/call

# 2. Claude Code (three-tool, no widget, no OAuth)
claude mcp add --transport http legal-mcp http://127.0.0.1:8001/mcp
# → /mcp → "research whether non-competes are enforceable in California"

# 3. Copilot Studio (three-tool in Test pane, no publish)
# → copilotstudio.microsoft.com → create agent → Tools → Add → MCP → URL → None auth

# 4. Expose to cloud clients (claude.ai web, Copilot Declarative Agent)
cloudflared tunnel --url http://127.0.0.1:8001
# → use the *.trycloudflare.com URL as the MCP server URL
```

## Configuration

All settings via env vars (prefix `MCP_`), see `.env.example`:

| Var | Default | Purpose |
|---|---|---|
| `MCP_BACKEND_URL` | `http://127.0.0.1:8000` | Mock backend URL |
| `MCP_HOST` | `127.0.0.1` | Adapter listen host |
| `MCP_PORT` | `8001` | Adapter listen port |
| `MCP_AUTH_TOKEN` | (empty) | Bearer token for simple auth |
| `MCP_WIDGET_POLL_MS` | `1500` | Widget poll interval |
| `MCP_THREE_TOOL_HOLD_MS` | `25000` | get_status hold-open for three-tool |
| `MCP_HOLD_POLL_INTERVAL_S` | `2` | Internal poll interval during hold-open |

## Layout

```
src/legal_research_mcp/
  __init__.py    entry point (mcp.run streamable-http)
  config.py      env-driven settings
  backend.py     httpx async client for the mock backend REST API
  profiles.py    ClientProfile + resolver (capability → identity → default)
  widget.py      server-rendered widget HTML + hand-rolled postMessage JS
  server.py      FastMCP server: tools (submit/status/result/cancel) + ui:// resource
```
