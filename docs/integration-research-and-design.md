# Long-Running Legal Agent — Integration Landscape & Design (June 2026)

*Research synthesis conducted June 17, 2026. Companion to `a2a-copilot-integration-report.md`.*

---

## 1. Executive summary

The "hot mess" you described is real, but two findings materially change the calculus:

1. **MCP Apps (SEP-1865) went Stable on 2026-01-26 and includes `app.updateModelContext()` / `ui/update-model-context`** — a widget can hand structured JSON *back into the LLM context* on close. This directly solves the context-boundary problem you believed was unsolvable. For maturity-rich clients (Claude Desktop, M365 Copilot, ChatGPT) the long-running problem is largely solvable *without* the poll-loop: submit → widget streams live progress via in-widget SSE → widget closes → structured result lands in model context. The poll-hack is only needed for maturity-poor clients (Amazon Quick, and as a fallback).
2. **Google Gemini is reachable via A2A today** through the **Gemini Enterprise web app** (formerly Agentspace) — admin registers your Agent Card; feature is Preview/Pre-GA and speaks A2A **v0.3 streaming** (v1.0 needs the `a2a.compat.v0_3` shim). So A2A is not just "Copilot + Bedrock" — it covers Copilot (GA), Gemini (Preview), Salesforce Agentforce (GA June 15 2026), ServiceNow, SAP Joule, Atlassian Rovo, and Gemini CLI.

Net protocol split for your targets:
- **A2A** → Microsoft Copilot, Google Gemini, plus enterprise surfaces. One server, many clients.
- **MCP** → Claude Desktop, Amazon Quick, plus long-tail MCP clients. One server, feature-gated per client.

There is no silver bullet, but there is a clean **two-adapter + client-profile-resolver** architecture (§7) that lets one core engine serve all of them.

---

## 2. What changed vs. your current mental model (the blind spots)

| # | You believed / assumed | Reality (mid-2026) | Impact |
|---|---|---|---|
| 1 | MCP widgets can't hand data back to the LLM; the orchestrator is blind to widget content | **MCP Apps `updateModelContext()`** lets a widget inject structured JSON into model context on close. Stable since 2026-01-26. Shipping in Claude Desktop, VS Code Copilot, ChatGPT (OpenAI Apps SDK), M365 Copilot, Goose, Postman. | High — eliminates the poll loop for rich clients |
| 2 | Google Gemini integration is unresearched / unclear | **Gemini Enterprise web app is an A2A client** (Preview). Register Agent Card via console or Discovery Engine `agents.create`. Gemini CLI is also an A2A client (v0.33.0). ADK has `RemoteA2aAgent`. | High — Gemini falls under the A2A adapter, not MCP |
| 3 | Claude Desktop timeout ~4 min, configurable | 4-min (240s) hard cap is **non-configurable** for remote + stdio tool calls; `MCP_TOOL_TIMEOUT`/per-server `timeout` ignored on Desktop. Claude **Code** (CLI) is the configurable one (per-server `timeout` up to ~28h). | Medium — separate Claude Desktop vs Claude Code strategies |
| 4 | Detect client by inspecting a header | The right gate is **capability/extension negotiation**, not name-sniffing. `initialize.capabilities.extensions["io.modelcontextprotocol/ui"]` etc. `clientInfo.name` is unreliable (Claude Desktop sends `"claude-ai"`, version `"0.1.0"`). | Medium — drives the profile resolver design |
| 5 | MCP "Tasks" spec might be the answer | Tasks is **experimental → graduating to extension** (`io.modelcontextprotocol/tasks`, SEP-2663). Blocking `tasks/result` was **removed**. **No mainstream LLM client drives the Tasks loop autonomously yet.** | Medium — don't bet on Tasks for v1; future-proof only |
| 6 | A2A is just Copilot + Bedrock | Also Gemini Enterprise, Gemini CLI, Salesforce Agentforce (GA Jun 15 2026), ServiceNow Now Assist, SAP Joule/Agent Gateway, Atlassian Rovo. A2A v1.0.1 (May 28 2026) adds **gRPC binding, Agent Card signing (JWS+JCS), Extended Agent Card, webhook push notifications**. | Medium — broader reach, one server covers many |
| 7 | ACP / AGNTCY are separate competing protocols to track | **ACP merged into A2A** (Linux Foundation, Aug 2025). AGNTCY is built on (the old) ACP. **AG-UI** (CoplotKit) is the *user-facing event* protocol that complements A2A (agent↔agent) and MCP (agent↔tools). | Low — reduces protocol sprawl |
| 8 | Holding the connection open = nobody resets timeout | Confirmed: "not all clients reset their timeout when they receive progress." 15 min through real LBs/proxies is risky even with SSE. | Medium — need push/webhook for deep tier |
| 9 | (possible gap) Claude Code as a distinct, *better* surface | Claude Code supports Elicitation (form+URL) since v2.1.76 and per-server timeouts — it's the most long-run-friendly Anthropic client. | Low-Medium — consider a Claude Code-specific recipe |
| 10 | (possible gap) Durable job fabric | In-memory task stores have **no fault tolerance** (per C# SDK docs). For 15-min jobs that outlive the connection, you need a durable store (Postgres-backed A2A `TaskStore`; MCP Mesh MeshJob pattern). | Medium — required for deep tier |

---

## 3. MCP landscape (mid-2026)

### Spec & transports
- **Current stable:** `2025-11-25`. **Release candidate:** `2026-07-28` (locked 2026-05-21).
- **Official transports:** stdio + **Streamable HTTP** only. **HTTP+SSE (2024-11-05) is Deprecated** since `2025-03-26` (SEP-2596).
- **`2026-07-28` RC makes Streamable HTTP stateless:** removes GET-stream endpoint, protocol-level sessions, `Mcp-Session-Id`; adds mandatory `Mcp-Method`/`Mcp-Name` headers. The `initialize` handshake is **removed** — protocol version, clientInfo, capabilities move into `_meta` on **every** request. (Detection code must handle both eras.)

### Tasks (the "experimental tasks spec" you mentioned)
- Experimental core in `2025-11-25`; graduating to extension **`io.modelcontextprotocol/tasks`** (SEP-2663).
- Lifecycle: `tools/call` returns `resultType:"task"` + `taskId`, `ttlMs`, `pollIntervalMs`; states `working` → `input_required` → terminal. Client polls `tasks/get`; `tasks/update`/`tasks/cancel`. **Blocking `tasks/result` removed.**
- **Adoption:** reference impls (Everything Server, Python `server.experimental.enable_tasks()`, C# `IMcpTaskStore`, FastMCP `task=True`). **No mainstream LLM client orchestrates Tasks autonomously yet.** → Future-proof, don't depend on for v1.

### Elicitation
- **Stable since `2025-06-18`** (form mode); URL mode added `2025-11-25`. Server sends `elicitation/create` mid-tool; `accept`/`decline`/`cancel`. Useful for mid-execution clarification (pairs with Tasks `input_required`).
- Supported by Claude Code (v2.1.76+), **not** Claude Desktop.

### Progress + holding the connection open
- Client sets `_meta.progressToken`; server pushes `notifications/progress` (`progress`, `total`, `message`) on the same Streamable HTTP SSE response; final `CallToolResult` ends it.
- Works for minutes, but **not all clients reset their timeout on progress** — risky for 15 min through proxies.

### Structured output
- `Tool.outputSchema` + `CallToolResult.structuredContent` (stable since `2025-06-18`).

### **MCP Apps (SEP-1865) — the key enabler**
- **Stable 2026-01-26** (first official extension). Tool declares `_meta.ui.resourceUri` → `ui://` HTML resource → host renders in sandboxed iframe; JSON-RPC over `postMessage`.
- **The context bridge:** views call `app.updateModelContext()` / `ui/update-model-context` to inject structured JSON into the model context. App-only tools (`visibility:["app"]`) stay *out* of context. Result splits model-facing `content` vs UI-facing `structuredContent`.
- **Shipping clients:** Claude Desktop, VS Code Copilot, ChatGPT (OpenAI Apps SDK), M365 Copilot, Goose, Postman, MCPJam, Archestra.
- **Implication:** for these clients, the long-running flow can be: `submit_research` returns a `ui://` widget → widget holds an SSE stream and shows live progress → on completion the widget calls `updateModelContext()` with the structured report and closes → orchestrator sees the result in context. **No `get_status` polling loop, no LLM "lying about checking in the background."**

### Async / durable patterns
- **FastMCP** `task=True` decorator → task handle + embedded worker; `forbidden`/`optional`/`required` modes; degrades to sync if unsupported. `ctx.report_progress` + `EventStore` for **resumable SSE**.
- **MCP Mesh MeshJob:** durable `task=true` + registry-held state, `submit`/`wait`/`cancel` polling the registry — designed so the connection can close and work outlives the request. Good pattern reference for the deep tier.

---

## 4. Client support matrix (long-running view)

| Client | MCP transports | Tool-call timeout | MCP Apps (UI) | Tasks / Elicitation | A2A | Identifying signal |
|---|---|---|---|---|---|---|
| **Claude Desktop** | stdio, SSE, Streamable HTTP | **240s hard, non-configurable** | Yes (`io.modelcontextprotocol/ui`) | Tasks: no. Elicitation: **no** | No | `clientInfo.name="claude-ai"` (unreliable); `User-Agent: Claude-User` |
| **Claude Code (CLI)** | stdio, SSE, Streamable HTTP, WS | per-server `timeout` up to ~28h (`.mcp.json`); ~60s HTTP first-byte floor | No (terminal) | Tasks: no. Elicitation: **yes** (v2.1.76+) | No | `user-agent: claude-code/<ver> ...`; `clientInfo.name="claude-code"` |
| **MS Copilot / Copilot Studio** | Streamable HTTP (GA) | ~120s (Power Platform connector ceiling; undocumented) | Yes (MCP Apps, most mature) | Not documented | **GA Apr 2026** | OpenAPI/connector; `X-` headers broken; identify via OAuth JWT `azp` |
| **Amazon Quick** (Apr 28 2026) | SSE + Streamable HTTP (remote) | Undocumented (~30s safe) | **No** | **No** | **No native** (only via Bedrock AgentCore Gateway hop) | Standard system headers only; OAuth DCR `client_id`/audience |
| **Google Gemini CLI** | stdio, SSE, Streamable HTTP, OAuth | per-`McpToolset` `timeout` (configurable) | No MCP widgets (separate A2UI for A2A) | No | **Yes** (v0.33.0, Mar 2026) | Not documented |
| **Google Gemini Enterprise web app** | — (A2A client, not MCP) | n/a | n/a | n/a | **Yes — Preview/Pre-GA**, v0.3 streaming | OAuth JWT `iss`/`aud` (Google) |
| **ChatGPT** | MCP connector | **~60s → 500** | Yes (OpenAI Apps SDK) | No | No | — |
| **Cursor** | Streamable HTTP | was 30s, now disabled; UI hangs on long | — | No | No | — |
| **Windsurf / Cline / Codex** | MCP | Codex: minutes, no timeout/progress | — | No | No | — |

**Maturity ranking for long-running integration (worst → best):**
1. Amazon Quick (tools-only, no UI, no Tasks/Elicitation, A2A only via Gateway hop)
2. Claude Desktop (240s non-configurable cap; but MCP Apps rescues it)
3. ChatGPT (~60s cap; but Apps SDK rescues it)
4. MS Copilot (~120s; MCP Apps + A2A GA)
5. Gemini Enterprise (A2A Preview; cleanest long-running model when GA)
6. Claude Code (configurable timeout, Elicitation — best Anthropic surface for long runs)

---

## 5. A2A landscape (mid-2026)

### Spec
- **v1.0.1 (May 28 2026)** — latest stable; v1.0.0 was first production release.
- New in v1.0: three normative bindings (JSON-RPC 2.0/HTTPS, **gRPC**, HTTP+JSON/REST; `.proto` is source of truth); **Agent Card signing (JWS RFC 7515 + JCS RFC 8785)** → `AgentCardSignature`; **Extended Agent Card** (`GetExtendedAgentCard`); `supportedInterfaces[]`; multi-tenancy; mTLS; OAuth 2.0 Device Code + PKCE; cursor pagination; **webhook push notifications** (from v0.3).
- SDKs: Python `a2a-sdk` v1.1.0, JS, Go, Java, .NET.

### A2A *clients* (can delegate to your external agent)
- **Microsoft Copilot Studio** — GA Apr 2026 (endpoint URL + None/API key/OAuth 2.0). **Work IQ** A2A public preview Apr 30 2026 (GA summer 2026).
- **Google Gemini Enterprise web app** — Preview; admin registers your Agent Card (console: *Gemini Enterprise → Agents → Add → Custom agent via A2A*, or Discovery Engine `agents.create` REST). Speaks **v0.3 streaming** — v1.0 agents use `a2a.compat.v0_3`.
- **Google Gemini CLI** — A2A client v0.33.0; remote subagents as `.md` files in `.gemini/agents/`; native gRPC.
- **Google ADK** — `RemoteA2aAgent` (Python/Java) — framework, not end-user surface.
- **Amazon Bedrock AgentCore Runtime** — hosts A2A *servers* serverless (containers, port 9000, SigV4/OAuth 2.0); agents deployed there can be clients. (Note: **not** Amazon Quick.)
- **Salesforce Agentforce** — A2A client; Multi-Agent Orchestration **GA June 15 2026**.
- **ServiceNow Now Assist 6.0.x** — both client and server; v0.3.
- **SAP Joule** — A2A client; SAP Agent Gateway exposes Joule agents as server (v0.3.0).
- **Atlassian Jira Rovo Agent Connector** — A2A client, EAP.
- **ChatGPT / OpenAI** — **No** A2A (issue #472; "no immediate plans").
- **Claude / Anthropic** — **No** native A2A (internal Managed Agents Beta May 2026).

### Competing / complementing protocols
- **ACP** (IBM/Bee) — **merged into A2A** (Linux Foundation, Aug 2025); repo archived; BeeAI is primary impl. Don't track separately.
- **AGNTCY** (Cisco/Google, Linux Foundation) — open MAS infra (Agent Directory, Workflow Server) built on the old ACP.
- **AG-UI** (CopilotKit) — agent↔user event protocol; **complements** A2A (agent↔agent) and MCP (agent↔tools). On Bedrock AgentCore. Relevant only if you want a richer frontend embedding story beyond MCP Apps.
- **LangGraph / LangChain Platform** — framework + internal orchestration; A2A via `a2a-sdk` adapters wrapping nodes. Not a competing wire protocol.
- **OpenAI Agents SDK** — internal handoffs; no A2A.

---

## 6. Client identification & feature detection

### MCP
- **`initialize.clientInfo` = `{name, title, version, description, icons, websiteUrl}`** (spec). Unreliable in practice: Claude Desktop sends `name="claude-ai"`, `version="0.1.0"`.
- **`2026-07-28` RC removes the handshake** — clientInfo/capabilities/protocolVersion move into `_meta` on every request. Detection must read `_meta["io.modelcontextprotocol/clientInfo"]` (new) or `params.clientInfo` (legacy).
- **HTTP headers (Streamable HTTP):** `MCP-Protocol-Version` (must match `_meta`), `Mcp-Method`, `Mcp-Name` (new), legacy `Mcp-Session-Id`. **No standardized client-ID header.** `x-mcp-header` is for tool-parameter mirroring, *not* identity.
- **`capabilities` object — the right feature gate.** Keys: `roots`, `sampling`, `elicitation` (`form`,`url`), `tasks`, and `extensions` map: `io.modelcontextprotocol/ui` (MCP Apps), `io.modelcontextprotocol/tasks`. Task streaming adds `streaming.partial`.
  - Gate dynamic widgets on `extensions["io.modelcontextprotocol/ui"]`
  - Gate SSE/long-running on `extensions["io.modelcontextprotocol/tasks"]` + `streaming.partial`
  - Gate mid-exec clarification on `elicitation`

### A2A
- Identity is **NOT** in JSON-RPC payloads — handled at the **HTTP transport layer**. Agent Card describes the *server*, not the caller.
- Headers clients send: `A2A-Version` (MUST), `A2A-Extensions` (opt-in), `Authorization`.
- Distinguish Copilot vs Vertex vs Bedrock via **OAuth JWT `iss`/`aud`/`azp`** or **SigV4 signer ARN** (`X-Amzn-Bedrock-AgentCore-Runtime-Session-Id`). No protocol-level caller-identity field yet (issue #1672).

### Recommended tiered detection strategy
1. **Capability/extension negotiation first** (most robust, spec-blessed, survives the stateless shift).
2. **`clientInfo.name` allowlist second** — for per-client timeouts. Normalize: `claude-ai`→Claude Desktop (60s hold), `claude-code`→Claude Code (long), `github-copilot-chat`/`mcp-client`→Copilot (45s), `amazon-quick`→Quick (30s).
3. **Header heuristics third** — `User-Agent` substring, `MCP-Protocol-Version`/`A2A-Version` era, OAuth JWT `azp`/`aud`/`iss`, SigV4 caller ARN, `X-Amzn-Bedrock-*`. Never trust alone (WAFs/proxies strip UA; OAuth flows make calls look like the connector).
4. **Safe default fallback** — no positive ID → most restrictive timeout (30s), features off.

### SDK exposure
- **FastMCP (Python):** `InitializationMiddleware.on_initialize` reads `clientInfo`; per-request `ctx.client_id`, `ctx.client_supports_extension(id)`, `ctx.request_context.session.client_capabilities`; HTTP via `get_http_headers()`.
- **Official python-sdk (lowlevel):** `ServerRequestContext.session` exposes negotiated capabilities; `meta` carries per-request `_meta`.
- **TS SDK:** server session exposes `clientCapabilities` + `clientInfo` after initialize.

---

## 7. Proposed architecture: centralized entry point + adapters + profile resolver

```
                         ┌──────────────────────────────────────────────┐
   A2A clients           │  /a2a  (A2A adapter — a2a-sdk + FastAPI)       │
   - Copilot Studio (GA) │  - Agent Card at /.well-known/agent-card.json  │
   - Gemini Enterprise   │  - Task lifecycle + SSE stream + push webhook  │
     (Preview, v0.3)     │  - Artifacts (markdown, data, files)           │
   - Gemini CLI          │  - v1.0 + a2a.compat.v0_3 shim                 │
   - Salesforce/SAP/...  │  - OAuth JWT → caller profile                  │
                         └───────────────┬──────────────────────────────┘
                                         │
   MCP clients           ┌───────────────▼──────────────────────────────┐
   - Claude Desktop      │  /mcp  (MCP adapter — FastMCP, Streamable HTTP)│
   - Claude Code         │  - ClientProfileResolver (capabilities →       │
   - Amazon Quick        │    clientInfo → headers → default)             │
   - ChatGPT/Cursor/...  │  - Feature gates per profile (see §8 recipes)  │
                         └───────────────┬──────────────────────────────┘
                                         │  (internal async API)
                         ┌───────────────▼──────────────────────────────┐
                         │  Core: LegalResearchEngine                     │
                         │  - submit(query, effort) → job_id              │
                         │  - get_status(job_id) → state + progress       │
                         │  - get_result(job_id) → structured report      │
                         │  - effort: quick(~2m) / standard(~5m) /         │
                         │    deep(~12m, cfg; 1σ→15m), randomized duration │
                         │  - Durable JobStore (Postgres) — required for  │
                         │    deep tier; work outlives any connection      │
                         └───────────────────────────────────────────────┘
```

**Single process, two HTTP endpoints, one engine, one job store.** Both adapters are thin; all intelligence lives in the core and the profile resolver.

### ClientProfileResolver (shared by both adapters)
```
resolve(request) → ClientProfile{
  name,                    # best-guess client identity
  capabilities,            # negotiated (MCP) or inferred (A2A)
  hold_open_ms,            # how long get_status may block before returning
  features: {
    mcp_apps,              # render ui:// widget with in-widget SSE
    sse_progress,          # stream notifications/progress on held-open call
    tasks_extension,       # use io.modelcontextprotocol/tasks
    elicitation,           # mid-exec clarification
    push_webhook,          # A2A push notifications
    three_tool_pattern,    # fall back to submit/status/result polling
  },
  a2a_version_compat,      # v1.0 vs v0.3 shim
}
```
Resolution order: capabilities/extensions → clientInfo.name allowlist → header/JWT heuristics → safe default (30s hold, only three-tool-pattern + sse_progress).

---

## 8. Per-client integration recipes (what each adapter does)

### A2A adapter (one server, all A2A clients)
- Expose Agent Card (signed v1.0) + a v0.3 compatibility shim for Gemini Enterprise.
- `message/send` `return_immediately:true` → return Task handle immediately (no timeout risk).
- `message/stream` (SSE) for quick/standard tiers — push `TaskStatusUpdateEvent` + `TaskArtifactUpdateEvent` with progress.
- **Push notifications (webhook)** for the deep (~15m) tier — client registers a webhook; you POST on state change. This avoids 15-min SSE-through-proxy risk entirely.
- Map outputs to Artifacts: markdown summary → `TextPart(text/markdown)`; risk JSON → `DataPart`; PDF/DOCX → `Part` with `url`/`raw` + `filename`; streaming progress → `TaskArtifactUpdateEvent(append=true)`.
- Identify caller via OAuth JWT `iss`/`aud`/`azp` (Copilot=Entra, Gemini=Google IAM, Bedrock=SigV4 ARN) → set per-caller pacing/auth.

### MCP adapter (FastMCP, feature-gated per profile)
Four behavioral modes, chosen by `ClientProfile`:

**Mode A — MCP Apps + in-widget SSE (rich clients: Claude Desktop, M365 Copilot, ChatGPT).**
- `submit_research` returns a `ui://` widget resource.
- Widget holds its own SSE stream to the server, renders live progress, and on completion calls `app.updateModelContext()` with the structured report, then closes.
- Orchestrator receives structured result in context — **no `get_status` polling, no LLM lying.** This is the preferred path wherever supported.
- Caveat to verify: whether Claude Desktop's 240s cap applies to the tool-call return only (widget SSE can run longer) or to the whole interaction. If the cap gates the tool return, Mode A works for all tiers; if it gates widget SSE too, deep tier must fall back to Mode C/D.

**Mode B — Held-open Streamable HTTP + progress (Claude Code, configurable-timeout clients).**
- `submit_research` blocks, streaming `notifications/progress` every few seconds; final `CallToolResult` carries the structured report.
- `hold_open_ms` from profile (Claude Code: up to 15 min via per-server `timeout`). Good for quick + standard; deep only if client timeout allows.

**Mode C — Three-tool pattern + server-side paced polling (Amazon Quick, ChatGPT w/o Apps, Copilot w/o Apps).**
- `submit_research` → `job_id`. `get_status(job_id)` **holds open** for `hold_open_ms` (profile: Quick 30s, ChatGPT ~55s, Copilot ~110s) emitting progress, then returns `working` + ETA + a strong instruction message: *"Do not answer from your own knowledge. If you return control to the user, tell them to type 'check status' or 'get results' to resume. You are not checking in the background."* `get_result(job_id)` returns the structured report (only valid when done).
- Tool descriptions are prompt-tuned to discourage abandonment and training-data fallback.

**Mode D — Tasks extension (future-proof, no mainstream client yet).**
- `submit_research` returns `resultType:"task"` + `pollIntervalMs`; client uses `tasks/get`. Implement behind the `io.modelcontextprotocol/tasks` capability gate so it activates automatically when clients ship support.

**Elicitation** (Claude Code, future others): used for mid-execution clarification (e.g., "found 3 jurisdictions — which?") via `ctx.elicit`, paired with the core's `input_required` state.

---

## 9. Open design questions (see also the interactive questions)

1. **MCP Apps investment** — building the `ui://` widget (HTML/JS + postMessage + in-widget SSE + `updateModelContext`) is the highest-leverage move but is real frontend work. In scope for v1?
2. **Adapter build order** — A2A first (covers Copilot GA + Gemini Preview + enterprise) or MCP first (covers Claude + Quick)?
3. **Claude Desktop deep tier** — if the 240s cap gates widget SSE too, the 15-min case on Claude Desktop must be async-handle + user re-prompt. Acceptable, or push Claude Desktop users to Claude Code for deep research?
4. **Deep tier transport** — A2A push notifications (webhook) for 15-min, or accept SSE risk, or require user-comeback?
5. **Single process vs separate deployments** for `/a2a` + `/mcp`?
6. **Job store** — Postgres-backed from day 1 (required for deep tier durability)?
7. **Auth unification** — one OAuth 2.0 / Entra ID for A2A (Copilot), Google IAM for Gemini, API key/DCR for Quick. Unified identity layer or per-adapter?
8. **Effort-tier routing** — allow quick (~2m) over held-open MCP (fits 240s with margin), force 5/15m always async? Or always-async for consistency?
9. **MVP client scope** — which clients are must-have for v1?
10. **AG-UI** — also expose an AG-UI endpoint for richer frontend embedding, or MCP Apps + A2A enough?
11. **v0.3 compat** — ship A2A v1.0 + `a2a.compat.v0_3` now (Gemini Enterprise needs it), or wait for Gemini GA?
12. **Detection default strictness** — when we can't identify the client, do we default to "most restrictive (30s, features off)" or "assume rich (MCP Apps on)"? Former is safer; latter is better UX.

---

## 10. Key takeaways

1. **No silver bullet**, but MCP Apps `updateModelContext()` removes the poll-loop for rich clients and A2A covers Copilot + Gemini + enterprise natively. The "hot mess" is smaller than it looked.
2. **Two adapters + a profile resolver over one durable core** is the right shape. Gate on **capabilities/extensions first**, client name second, headers third.
3. **A2A = Copilot + Gemini + Salesforce/ServiceNow/SAP/Atlassian + Gemini CLI.** MCP = Claude Desktop + Amazon Quick + long tail. Build A2A first if Copilot/Gemini are priority; MCP first if Claude/Quick are.
4. **MCP Tasks is not v1-ready** (no autonomous client orchestration). Use Mode A (MCP Apps) or Mode C (three-tool + paced hold-open) for now; implement Mode D behind a capability gate for the future.
5. **Deep tier (15m) needs durability + push/webhook**, not held-open SSE. Plan for Postgres JobStore + A2A push notifications from the start.
6. **Gemini is reachable today via A2A (Preview, v0.3)** — your biggest unresearched blind spot is largely closed.

---

# Part 2 — Refined MCP-Adapter Design (MVP)

*Decisions locked with the user (June 17):*
- *Adapter order: **MCP first** (Anthropic > Amazon > Microsoft priority). A2A is post-MVP; MS Copilot is the proving ground that later opens the A2A path to Google.*
- *MVP client scope: **Microsoft Copilot (Studio/M365), Claude Desktop, Amazon Quick**.*
- *Build the **MCP Apps widget (Mode A)** for rich clients **+ three-tool fallback (Mode C)**.*
- *Widget progress strategy: **server-render per-client widget HTML** (SSE consumer for Claude, app-only-poll for Copilot) at `resources/read` time, using the resolved profile. Self-contained inline HTML (Copilot requires it).*
- *Deep-tier (12±3m, configurable; 1σ→15m) on MCP: **attempt the same widget/poll UX; on close or control-return before completion, deliver an honest "job still running — ask me to check again" message** (no "checking in the background" lies). Result persists in Postgres (mock uses SQLite, DB-agnostic); user re-invokes to resume. A2A push notifications remain the clean deep-tier solution post-MVP. The mock models non-deterministic timing and deliberately poor progress reporting (no reliable ETA, noisy pct, stalls) to match the real system.*
- *JobStore: **Postgres-backed from day 1** (JobStore + A2A TaskStore share it).*
- *Model-visible `get_status`/`get_result`: **registered only for `three-tool` profiles** (Quick/default). Widget profiles expose only app-only `get_progress`/`get_result_app`; the orchestrator receives the result via `updateModelContext`.*
- *Defaulted (correct if wrong): **`submit_research` always returns fast** (uniform async-handle shape; progress logic lives in the widget or `get_status`); **single process, one `/mcp` Streamable HTTP endpoint** for all three MVP clients (Claude Desktop via remote connector to avoid the 60s stdio-macOS trap); **per-adapter auth for MVP** (Claude remote connector OAuth, Copilot Power Platform API key/OAuth 2.0, Quick OAuth DCR/API key) — unified identity deferred to the A2A phase.*

---

## 11. The critical per-client fork: widget SSE behavior is *opposite* on Copilot vs Claude Desktop

Your POC symptom ("SSE queue immediately closed" in Copilot) has a concrete root cause, and it is **not** a bug in your code — it is a documented Copilot limitation that makes the widget strategy diverge per client.

### Claude Desktop — widget *can* hold its own SSE
- MCP Apps supported (`io.modelcontextprotocol/ui`). Widget runs in a sandboxed iframe; `connectDomains` in `_meta.ui.csp` maps to `connect-src` and **does allow `EventSource`/`fetch`/WebSocket** to declared origins (default is `connect-src 'none'`, so you **must** declare `connectDomains`).
- **The 240s cap applies only to the `tools/call` RPC return.** If `submit_research` returns *quickly* with `{jobId, status:"running"}` + the `ui://` reference, the widget's own SSE to your server runs **freely past 240s**. `ui/update-model-context` is an independent View→Host postMessage RPC, also not gated by the 240s cap.
- Caveat (path-dependent ceiling): ~240s for remote/hosted connectors (macOS) and **all transports on Windows**; ~60s for **local stdio on macOS desktop**. Prefer the remote/Streamable HTTP connector for Claude Desktop to get the 240s ceiling and avoid the 60s stdio trap.
- Open question (untested): whether Claude Desktop tears down the widget iframe if the originating `tools/call` is cancelled at 240s. Mitigation: **submit must return fast** so the cap never bites.

### Microsoft Copilot (Cowork) — widget *cannot* hold SSE; must poll via app-only tools/call
- **Root cause of your POC failure:** Cowork renders the widget iframe but **drops `connectDomains`, `resourceDomains`, and `baseUriDomains`** from `_meta.ui.csp` — it honors only `csp.frameDomains`. So the browser kills any `EventSource`/`fetch` from the iframe on a `connect-src` CSP violation **before it opens**. (The sibling extensibility doc table marks `connectDomains` "✅ supported," but the newer, more specific Cowork doc overrides it — treat Cowork as `connectDomains`-blind.)
- The spec-intended pattern is **postMessage JSON-RPC to the host, which proxies `tools/call`/`resources/read` to your server** — never direct SSE from the iframe. Cowork only forwards `resources/read`, `tools/call`, and `ui/message`; it rejects `initialize`, `notifications/*`, `sampling/*`, `elicitation/*`.
- **No server-pushed streaming to the widget:** Cowork does not deliver the spec's `ui/notifications/tool-input-partial`. The postMessage channel is effectively **request/response**, capped at **60 `tools/call`/min/conversation** and **64 KiB per inlined result**.
- Copilot Studio **dropped legacy SSE transport after Aug 2025** — only Streamable HTTP is accepted (legacy `/sse` GET returns 405 / "stream disconnected" immediately, a second plausible POC failure if you hit that endpoint). Streamable HTTP SSE (POST response upgraded to `text/event-stream`) **is** supported between Copilot↔your server for `notifications/progress`, but the **widget never sees that stream** — only the final `CallToolResult`.
- Other Copilot risks: undici ~300s headers/body timeout in Node-based hosts; Power Platform connector ~500 KB response limit; MCP Apps handshake races (`ui/initialize` lost → widget stays `visibility:hidden`).

### Amazon Quick — no MCP Apps at all
- Tools + data access only. No `io.modelcontextprotocol/ui`, no Tasks, no Elicitation, no native A2A (only via Bedrock AgentCore Gateway hop, out of MVP scope). → Pure three-tool pattern.

**Implication:** "Mode A" is not one mode — it is two sub-modes. The profile resolver must pick the widget's progress mechanism per client.

---

## 12. Three MVP recipes (selected per ClientProfile)

### Recipe 1 — Claude Desktop: **Widget + widget-owned SSE** (`mode: widget-sse`)
1. Orchestrator calls `submit_research(query, effort)` → server returns **immediately** with `{job_id, status:"running"}` + `_meta.ui.resourceUri = "ui://legal/progress.html"`. (Must beat the 240s/60s cap — return in <5s.)
2. Host renders widget. Widget opens **its own** `EventSource` to `https://legal-agent.example.com/streams/{job_id}` (origin declared in `connectDomains`; CORS via `_meta.ui.domain`).
3. Widget streams live progress (past 240s, up to the standard ~5m tier comfortably; deep tier = open question, §14).
4. On completion: widget calls `app.updateModelContext({structuredContent: report})` then `app.sendMessage({role:"user", content:[...]})` to resume the agent, then `app.requestTeardown()`.
5. **No `get_status`/`get_result` orchestrator polling.** The orchestrator gets the structured report in context on widget close. This is the clean UX you wanted.

### Recipe 2 — Copilot: **Widget + app-only tools/call polling** (`mode: widget-poll`)
1. `submit_research(query, effort)` returns **immediately** with `{job_id, status:"running"}` + `ui://legal/progress.html`. Do **not** hold the call open.
2. Host renders widget. Widget **polls** an app-only `get_progress(job_id)` tool via `app.callServerTool(...)` → postMessage → host → your server. Poll interval **≥1.2s** to stay under 60/min (adaptive: 1.2s early, 3s later). No `EventSource` from the iframe — it will be CSP-killed.
3. Separately, your server emits `notifications/progress` on the `submit_research` Streamable HTTP SSE for the **agent/trace** side (not the widget). Each `tools/call` (submit and each poll) must return **fast** (<60s, ideally <5s) to dodge the undici 300s / connector ceilings.
4. On completion: widget calls app-only `get_result(job_id)` (final report is >64 KiB likely → must be a separate `tools/call`, not inlined), then `app.updateModelContext({structuredContent: report})` + `app.sendMessage(...)` + `app.requestTeardown()`.
5. Mark `get_progress`/`get_result` `visibility:["app"]` so the orchestrator never sees them (avoids context clutter / premature abandonment).

### Recipe 3 — Amazon Quick: **Three-tool + server-side paced hold-open** (`mode: three-tool`)
1. `submit_research(query, effort)` → `{job_id, status:"running", eta_ms, poll_hint}`.
2. `get_status(job_id)` **holds open** for `hold_open_ms ≈ 25s` (Quick's timeout is undocumented; 25s is the safe margin), streaming `notifications/progress` if the transport permits, then returns `{status:"working", pct, eta_ms, message}`. The `message` is prompt-tuned: *"Job still running. Do NOT answer from your own knowledge. If you return control to the user, tell them to type 'check status' to resume — you are NOT checking in the background."*
3. `get_result(job_id)` → structured report (only valid when `status:"completed"`; else returns `{status:"working", error:"not_ready"}`).
4. No widget. Tool descriptions heavily prompt-tuned to discourage abandonment and training-data fallback.
5. For a 15-min job at 25s hold-open → ~36 orchestrator polls. High abandonment risk (§14).

### (Non-MVP, for completeness)
- **Recipe 4 — Claude Code: held-open + `notifications/progress`** (`mode: held-open`). `submit_research` blocks, `ctx.report_progress` every few seconds, `EventStore` for resumable SSE. Configurable per-server `timeout` up to ~28h. Elicitation for mid-exec clarification. Easy to add since the core is the same.
- **Recipe 5 — Tasks extension** (`mode: tasks`). `@mcp.tool(task=True)` + `pollIntervalMs`. Implement behind the `io.modelcontextprotocol/tasks` capability gate; auto-activates when a client ships support. Not active for any MVP client.

---

## 13. ClientProfileResolver — MVP mapping

Resolution order: **capabilities/extensions → identity → safe default.**

```
resolve(mcp_request) → ClientProfile:
  # Step 1: capability gate (spec-blessed, survives 2026-07-28 stateless shift)
  has_ui = ctx.client_supports_extension("io.modelcontextprotocol/ui")
  has_tasks = ctx.client_supports_extension("io.modelcontextprotocol/tasks")
  has_elicitation = "elicitation" in client_capabilities

  # Step 2: identity (clientInfo.name allowlist + header/JWT heuristics)
  name = ctx.client_id  # normalized
  ua = get_http_headers().get("user-agent","")
  xms = get_http_headers().get("x-ms-agentic-protocol","")  # Copilot/Power Platform

  if has_ui and name == "claude-ai" or "Claude-User" in ua:
      → profile(claude-desktop):  mode=widget-sse,   hold_open_ms=5000 (submit fast),
                                   widget_stream=True, cap_ms=240000, cap_note="stdio-macos=60s; use remote connector"
  elif has_ui and ("mcp-streamable" in xms or name in {"copilot","github-copilot-chat","mcp-client"}):
      → profile(copilot):         mode=widget-poll,  hold_open_ms=5000 (submit/poll fast),
                                   widget_stream=False, poll_min_interval_ms=1200,
                                   inline_limit_bytes=65536, transport="streamable-http-only"
  elif name == "amazon-quick" or oauth_audience_matches("amazon-quick") or dcr_probe_seen:
      → profile(amazon-quick):    mode=three-tool,   hold_open_ms=25000,
                                   widget_stream=False, has_ui=False
  elif has_ui:  # unknown but UI-capable
      → profile(unknown-rich):    mode=widget-poll,  hold_open_ms=5000  # poll is the portable default
  else:         # unknown, no UI
      → profile(default-restrictive): mode=three-tool, hold_open_ms=30000, widget_stream=False
```

**Note on Copilot detection:** `clientInfo`/UA for Copilot is under-documented and `X-` headers were broken (Oct 2025). The most reliable signal is the **`x-ms-agentic-protocol: mcp-streamable-1.0`** header injected by the Power Platform connector, plus the OAuth JWT `azp` for the Power Platform app. Treat any UI-capable client you can't positively identify as `unknown-rich → widget-poll` (polling is the portable subset that works on both Copilot and Claude Desktop).

**Note on Claude Desktop detection:** `clientInfo.name` is `"claude-ai"` (not `claude-desktop`), version `"0.1.0"` (static, unreliable). `User-Agent: Claude-User` is the better signal. Confirm the remote-connector transport is used to avoid the 60s stdio-macOS trap.

---

## 14. Deep-tier (~12m, configurable; 1σ→15m) gap — DEFERRED, documented here

The user asked to design MCP first and measure how long SSE stays open per client before committing to a deep-tier transport. (Mock durations: quick 2m±15s, standard 5m±1m, deep 12m±3m — all clamped and configurable via env; `MOCK_TIME_SCALE` accelerates for dev.) Current viability per MVP client:

| Client | Deep-tier (~12m) viability on MCP | Risk |
|---|---|---|
| **Claude Desktop** (widget-sse) | Plausible but **unverified** — widget's own SSE runs past 240s architecturally, but real-world max socket lifetime, idle timeouts, and user navigation away from the chat are unknown. If the user closes the chat, the widget is torn down and the report is lost unless already persisted. | Medium-High |
| **Copilot** (widget-poll) | Works **if the widget stays mounted 15 min**; 60 polls/min × 15 min = 900 calls max (OK at ≥1.2s interval). But a 15-min mounted widget is a fragile UX assumption, and each poll is a Power Platform connector round-trip. | Medium-High |
| **Amazon Quick** (three-tool) | **Poor.** ~36 orchestrator polls at 25s hold-open; high probability the LLM abandons, lies ("checking in the background"), or answers from training data. | High |

**Policy (locked): attempt + honest comeback on close.**
- The deep tier uses the **same widget/poll UX** as the standard tier — it is not gated off MCP. The widget (Claude) keeps streaming via its own SSE; the widget (Copilot) keeps polling; `get_status` (Quick) keeps paced hold-open.
- **The honest-comeback contract:** if the widget is closed, the conversation turn returns, or a `get_status` call returns `working` and the orchestrator is about to yield control to the user, the tool/widget emits an **explicit, non-deceptive message**: *"The legal research job (ID …) is still running and will take ~N more minutes. I am not monitoring it in the background. To get the results, ask me to 'check job …' or 'get the results for job …' later."* This directly kills the "I'll keep checking in the background" lie you described. The persisted job in Postgres makes resume trivial.
- Result is **persisted in Postgres**; on comeback the user re-invokes `get_result(job_id)` (three-tool) or reopens the widget / the widget re-attaches and calls `get_result_app` then `updateModelContext` (widget profiles).
- **A2A push notifications (webhook) remain the clean deep-tier solution** — client registers a webhook, you POST on completion, no held-open connection, no comeback needed. This lives in the post-MVP A2A adapter (§7) and is the proving-ground path to Gemini.
- **Durable JobStore (Postgres) is required regardless** — the job must outlive any client connection. The C# SDK explicitly warns in-memory task stores have no fault tolerance. Confirmed for day 1.

**Empirical tests to run during MVP build (per client):**
1. Claude Desktop (remote connector): max wall-clock a widget-owned `EventSource` stays open before idle close; behavior when user navigates away / starts a new chat.
2. Copilot: confirm `connectDomains` is dropped (DevTools CSP violation); confirm `get_progress` app-only `tools/call` round-trips and the 60/min ceiling; measure widget teardown on conversation end.
3. Amazon Quick: discover the actual tool-call timeout (hold-open sweep) and whether `notifications/progress` resets it.

---

## 15. FastMCP implementation notes (MVP)

- **Declare widget:** `@mcp.tool(app=AppConfig(resource_uri="ui://legal/progress.html"))` + `@mcp.resource("ui://legal/progress.html", app=AppConfig(csp=ResourceCSP(connect_domains=["https://legal-agent.example.com"])))`. FastMCP auto-applies `text/html;profile=mcp-app`.
- **`updateModelContext` is called by the widget JS (View→Host), not emitted by the server.** Method `ui/update-model-context`, params `{content?, structuredContent?}`. Use the JS SDK `app.updateModelContext(...)` + `app.sendMessage(...)` + `app.requestTeardown()`.
- **App-only tools** (`get_progress`, `get_result`): `visibility=["app"]`. ⚠ **Known caveat (FastMCP 3.2.x, issue #4088):** on a plain `FastMCP`, `visibility=["app"]` tools are unreachable because FastMCP's filter strips them and hashed-name dispatch only exists for `FastMCPApp`. **Use `FastMCPApp` with `@app.tool()` for app-only tools** (backend tools default to `visibility=["app"]` there). Verify before relying on it.
- **Capability gating:** `ctx.client_supports_extension(UI_EXTENSION_ID)` where `UI_EXTENSION_ID="io.modelcontextprotocol/ui"`; `InitializationMiddleware.on_initialize` to capture `clientInfo`/`capabilities` into session state; `get_http_headers()` for `x-ms-agentic-protocol` / `User-Agent` (works pre-handshake).
- **Server-rendered per-client widget HTML:** the `ui://` resource is fetched by the host via `resources/read`, which runs in session context — so the resource handler can read `ctx.client_id`/profile and render widget HTML with the right progress strategy baked in (SSE endpoint for Claude; polling loop for Copilot). This is cleaner than client-side feature-detection and keeps the widget self-contained (no external assets → inline everything as `data:` URLs; Copilot requires self-contained HTML).
- **Held-open progress (Recipe 4, non-MVP):** `ctx.report_progress(progress, total)` + `mcp.http_app(event_store=EventStore())` for resumable SSE; `ctx.close_sse_stream()` + `Last-Event-ID` reconnect.
- **Tasks (Recipe 5, future):** `@mcp.tool(task=True)`, modes `forbidden`/`optional`/`required`; requires `fastmcp[tasks]`. No MVP client drives it — plumb it behind the capability gate only.
- **Transport:** Streamable HTTP only (Copilot requires it; legacy SSE is deprecated and Copilot rejects it). `mcp.run(transport="streamable-http")`.

---

## 16. Tool surface (MVP)

| Tool | Visibility | Purpose | Behavior per profile |
|---|---|---|---|
| `submit_research(query, effort)` | model | Start a job | All profiles: returns `{job_id, status:"running", eta_ms}` fast (+ `ui://` ref if `has_ui`) |
| `get_status(job_id)` | model | Poll status (non-widget clients) | `three-tool` only: holds open `hold_open_ms`, then returns working/done |
| `get_result(job_id)` | model | Fetch final report (non-widget clients) | `three-tool` only: structured report when done |
| `get_progress(job_id)` | app | Widget poll (widget clients) | `widget-poll` (Copilot) and as a fallback: returns `{pct, eta_ms, phase}` fast |
| `get_result_app(job_id)` | app | Widget fetches final report | `widget-*`: returns structured report (called by widget before `updateModelContext`) |
| (widget HTML) | app resource | `ui://legal/progress.html` | Server-rendered per profile: SSE consumer (Claude) or poller (Copilot) |

`get_status`/`get_result` (model-visible) are registered **only for `three-tool` profiles** (Quick/default). Widget profiles expose only the app-only `get_progress`/`get_result_app`; the orchestrator receives the result via `updateModelContext` on widget close — no context clutter, no premature-abandonment path. Locked (see §11).

---

## 17. Design status — all pivotal forks resolved

All four interactive forks + the three prose defaults are locked in the §11 "Decisions locked" block. No outstanding design questions block the MVP build. The empirical tests in §14 (max widget SSE lifetime on Claude; Copilot CSP/rate-limit confirmation; Quick timeout sweep) are **build-time verification tasks**, not design gates — run them during implementation and adjust `hold_open_ms` / poll intervals / deep-tier fallback accordingly.

Next step: scaffold the core `LegalResearchEngine` (mocked, effort-tiered random duration, Postgres JobStore, async submit/status/result) + the FastMCP MCP adapter with `ClientProfileResolver` and the three recipes, behind a feature flag so recipes can be tuned without redeploy. The A2A adapter is a post-MVP add-on at `/a2a` on the same process.

---

# Part 3 — Build Verification & Testing Strategy

*Added June 17 after FastMCP API verification + Linux testing-path research.*

## 18. FastMCP API verification (verified against 3.4.2, Jun 6 2026)

**Safe to use verbatim:**
- `from fastmcp import FastMCP, Context`; `FastMCP(name)`; `@mcp.tool(...)`; `@mcp.resource(...)`; `mcp.run(transport="streamable-http", host=, port=)`
- `from fastmcp.apps import AppConfig, ResourceCSP, ResourcePermissions, UI_EXTENSION_ID, FastMCPApp`
- `AppConfig(resource_uri=, visibility=["app"|"model"], csp=ResourceCSP(connect_domains=, resource_domains=, frame_domains=, base_uri_domains=), permissions=, domain=, prefers_border=)`
- `@mcp.resource("ui://...")` → auto-applies `text/html;profile=mcp-app`
- `ctx.client_supports_extension(UI_EXTENSION_ID)`; `ctx.client_id`; `ctx.request_id`; `ctx.session_id`; `ctx.request_context`; `await ctx.report_progress(progress, total)`
- `from fastmcp.server.dependencies import get_http_request, get_http_headers, get_context`
- `from fastmcp.server.event_store import EventStore`; `mcp.http_app(event_store=, retry_interval=, transport="streamable-http")`
- `from fastmcp.server.tasks import TaskConfig`; `@mcp.tool(task=True)` / `TaskConfig(mode="forbidden"|"optional"|"required")`; extra `fastmcp[tasks]`
- JS SDK `@modelcontextprotocol/ext-apps@1.7.4`: `import { App } from "@modelcontextprotocol/ext-apps/app-with-deps"`; `new App({name,version})`, `app.connect()`, `app.ontoolresult`, `app.callServerTool({name,arguments})` confirmed.

**Changed / does not exist:**
- **`InitializationMiddleware` does NOT exist.** Implement `on_initialize` as a hook on a custom `Middleware` subclass: `from fastmcp.server.middleware import Middleware, MiddlewareContext`. For the MVP we resolve the profile per-request inside each tool via `ctx` + `get_http_headers()` (no middleware needed).

**Verify at install time (smoke-test before relying on):**
- `FastMCPApp` + `@app.tool()` app-only reachability from a real host UI (issue #4119 still open) — **MVP avoids this entirely by NOT using `visibility=["app"]`** (see §19).
- JS `app.updateModelContext` / `app.sendMessage` / `app.requestTeardown` SDK wrappers — **MVP hand-rolls the raw JSON-RPC `ui/update-model-context`, `ui/message`, `ui/request-teardown` methods** (spec-defined, SDK-agnostic).
- `ctx.request_context.session.client_capabilities` low-level shape.

Smoke test: `python -c "import fastmcp; print(fastmcp.__version__); from fastmcp.apps import AppConfig, ResourceCSP, ResourcePermissions, UI_EXTENSION_ID, FastMCPApp; from fastmcp.server.event_store import EventStore; from fastmcp.server.tasks import TaskConfig; from fastmcp.server.middleware import Middleware, MiddlewareContext; from fastmcp.server.dependencies import get_http_request, get_http_headers; print('ok', UI_EXTENSION_ID)"`

## 19. MVP simplification: single `widget-poll` recipe (no app-only tools, no widget-owned SSE)

Two simplifications locked during build verification, both reducing risk without losing MVP value:

1. **No `visibility=["app"]` tools.** FastMCP 3.4.2 has open issues (#4088/#4119) on app-only tool reachability. Instead, **four model-visible tools** (`submit_research`, `get_status`, `get_result`, `cancel_research`) serve both the orchestrator (three-tool clients) and the widget (the widget calls `get_status`/`get_result` via `callServerTool` — same tools). No app-only tools → no caveat. The model *could* call `get_status`/`get_result` on widget clients, but prompt-tuning in `submit_research`'s return steers it away ("a progress widget is open; do not call get_status/get_result — the widget delivers the result automatically").

2. **Widget polls `get_status` on a timer for ALL UI-capable clients (Claude + Copilot).** One widget HTML, one code path. Each `callServerTool("get_status")` returns in <1s (well under any client's tool-call cap), so the 240s/Copilot ceilings never bite the widget. `widget_stream`/widget-owned SSE is deferred (it's a UX optimization for very long deep-tier jobs; the SSE-proxy endpoint on the adapter is extra complexity not needed for MVP). Poll interval 1500ms (40/min, under Copilot's 60/min).

**`get_status` is profile-aware:** `three-tool` profile → holds open `hold_open_ms` streaming `notifications/progress` via `ctx.report_progress`, then returns; `widget-poll` profile → returns current status immediately (the widget drives its own poll timer). One tool, two behaviors by profile.

**Final MVP tool surface (all model-visible):**
| Tool | Behavior |
|---|---|
| `submit_research(query, effort="standard")` | Always: backend `POST /jobs`, return `{job_id, status:"working", ...}` fast + `_meta.ui.resourceUri` (host renders widget only if UI-capable; ignored otherwise) |
| `get_status(job_id)` | `three-tool`: hold-open `hold_open_ms` + `report_progress`, then return `JobStatus`. `widget-poll`: return `JobStatus` immediately |
| `get_result(job_id)` | Backend `GET /jobs/{id}/result`; returns `JobResult` (report or error; "not_ready" if not terminal) |
| `cancel_research(job_id)` | Backend `DELETE /jobs/{id}` |
| `ui://legal/progress.html` (resource) | Server-rendered HTML; hand-rolled JS polls `get_status` via `callServerTool`, renders progress, on terminal calls `get_result` then `ui/update-model-context` + `ui/message` + `ui/request-teardown` |

## 20. Linux testing plan (Fedora, no Claude Desktop)

| Client | Testable on Linux? | Recipe | Fastest loop |
|---|---|---|---|
| **MCP Inspector** | Yes (`npx`) | three-tool + progress | `npx @modelcontextprotocol/inspector` → Streamable HTTP → tunnel URL → tools/list + tools/call. Run FIRST for protocol sanity. Tools-only (no widget). |
| **Claude Code** | Yes (native dnf) | three-tool (no widget) | `claude mcp add --transport http mvp https://<tunnel>/mcp --header "Authorization: Bearer <token>"` → `/mcp` → prompt. No OAuth needed. |
| **claude.ai web** | Yes (browser, Pro plan) | three-tool + widget | cloudflared named tunnel + OAuth 2.1/DCR server (~200-300 lines) → Settings → Connectors → Add custom connector → new chat. Content-version `ui://` URIs (claude.ai caches them). |
| **Copilot Studio (browser)** | Yes (trial license) | three-tool (Test pane) | copilotstudio.microsoft.com → create agent → Tools → Add tool → MCP → tunnel URL → None auth → **Test pane immediately**. No publish. |
| **Copilot Declarative Agent** | Yes (VS Code + Agents Toolkit) | three-tool + widget | Agents Toolkit → Declarative Agent → Add Action → MCP Server → Provision + sideload → test at `m365.cloud.microsoft/chat`. **Only way to test MCP Apps widgets on MS.** |
| **Amazon Quick** | Yes (public AWS service, needs AWS account + Quick access) | three-tool | AWS console → Quick → Connectors → Create MCP integration → URL → Test action APIs. Substitute if no AWS: MCP Inspector / Claude Code. |

**Tunnel:** `cloudflared tunnel --url http://localhost:8001` (ephemeral `*.trycloudflare.com`) for quick tests; `cloudflared tunnel create mvp && cloudflared tunnel route dns mvp dev.<yourdomain>.com` for stable OAuth redirect URIs. ngrok free tier has a 2h session limit — avoid for OAuth.

**Anthropic remote connector requirements (for claude.ai web):** public HTTPS; OAuth 2.0 (DCR `oauth_dcr` or CIMD `oauth_cimd`) or `none`; 401 + `WWW-Authenticate: resource_metadata=<URL>` (RFC 9728) + RFC 8414 discovery; **no query-string tokens**; no registry needed (custom URL connector). claude.ai web has **no bearer-token option** → OAuth 2.1/DCR + PKCE server required for the widget recipe there (~200-300 lines FastAPI). Claude Code CLI accepts `--header` bearer tokens (no OAuth needed) — use it for the fastest Anthropic loop.

**Recommended test order on Linux:**
1. MCP Inspector (protocol sanity, all 4 tools, progress notifications) — no client license needed.
2. Claude Code (three-tool recipe end-to-end) — `dnf install claude-code`, bearer header, no OAuth.
3. Copilot Studio browser (three-tool in Test pane) — trial license, None auth, no publish.
4. claude.ai web (widget recipe) — needs OAuth 2.1/DCR server + cloudflared named tunnel + Pro plan.
5. Copilot Declarative Agent (widget recipe on M365) — VS Code + Agents Toolkit + sideload.
6. Amazon Quick (three-tool) — if AWS account available.

---

## 21. Windows testing plan (the better path for widget testing)

*Added June 18 after Windows-specific research. The Windows path is significantly better for testing MCP Apps widgets because two surfaces render widgets over localhost with no tunnel and no publish.*

### Key findings that reshape the plan

1. **Claude Desktop remote connector requires public HTTPS** — Anthropic's *cloud* connects to your server, not your device. `http://127.0.0.1:8001/mcp` will NOT work via the connector UI. Auth options: `oauth_dcr`, `oauth_cimd`, `oauth_anthropic_creds`, `custom_connection`, `none` — but all still need public HTTPS.
2. **Claude Desktop local stdio DOES render widgets**, and is the reliable widget path. Critical: **`mcp-remote` stdio bridge leaves the widget `visibility: hidden`** (a host handshake bug, anthropics/claude-ai-mcp#149). To test the widget, run FastMCP in **native stdio** mode and point `claude_desktop_config.json` directly at the Python command — no bridge, no tunnel.
3. **VS Code Copilot Chat is the first editor with full MCP Apps support** (Jan 2026). It renders `ui://` widgets inline, accepts `http://127.0.0.1:8001/mcp` directly via `.vscode/mcp.json`, no tunnel, no publish. This is the **fastest Copilot widget test loop on any OS.**
4. **Copilot Studio Test pane is text-only** — widgets render only after publish, in M365 Copilot (`m365.cloud.microsoft/chat`). The Test pane is "design-time validation and doesn't fully replicate all published channel behaviors."
5. **M365 Copilot (Cowork) renders widgets (GA March 2026)** but requires public HTTPS + Power Platform custom connector + publish. Use `devtunnel` (Microsoft's free tunnel) to expose localhost.
6. **Windows Copilot (built into Win 11) does not support MCP Apps widgets** — it has an OS-level MCP server registry, not widget rendering in chat.
7. **Amazon Quick has a desktop app** that can connect to `http://localhost:PORT/mcp` directly (Remote connection) — no public HTTPS needed. The web/Suite integration requires public HTTPS (Quick's servers connect). **Tool-call timeout is 60s (not 30s as assumed)** — 25s hold-open is safe. Enterprise subscription or 30-day trial required; Pro supports ≤5 MCP servers.
8. **Amazon Quick validates JSON Schema Draft 7 at publish time** — `required` must be an array at root level, not `required: true`. Tool list is static after registration (must delete/recreate to change tools).
9. **240s cap confirmed on Windows for ALL transports** (stdio + remote) — unlike macOS where stdio gets ~60s. This is actually better for testing: stdio on Windows gives you the full 240s ceiling.

### Windows testing matrix

| Client | Widget? | Transport | Localhost? | Setup needed | What it validates |
|---|---|---|---|---|---|
| **MCP Inspector** | No (Apps panel only) | Streamable HTTP | Yes | `npx @modelcontextprotocol/inspector` | Protocol sanity, all 4 tools, progress notifications |
| **Claude Desktop (stdio)** | **Yes** | stdio (native) | Yes (local process) | `claude_desktop_config.json` → Python stdio command | Widget rendering, `updateModelContext`, `ui/message`, 240s cap |
| **Claude Desktop (remote)** | Yes | Streamable HTTP | **No** (public HTTPS) | cloudflared/devtunnel + OAuth DCR or `none` | Remote connector path, real production flow |
| **VS Code Copilot Chat** | **Yes** | Streamable HTTP | **Yes** | `.vscode/mcp.json` → `http://127.0.0.1:8001/mcp` | **Fastest widget loop.** Copilot widget rendering, `callServerTool` polling, `updateModelContext` |
| **Copilot Studio (Test pane)** | No (text only) | Streamable HTTP | No (public HTTPS) | tunnel + trial license | Three-tool only; tools/list, tools/call, tool descriptions |
| **M365 Copilot (Cowork)** | **Yes** | Streamable HTTP | No (public HTTPS) | devtunnel + Power Platform connector + publish | Full production Copilot widget flow, `connectDomains` CSP drop, 60/min poll ceiling |
| **Amazon Quick (desktop app)** | No | Streamable HTTP | **Yes** | Quick desktop app → Remote connection → localhost URL | Three-tool pattern, 60s timeout, Quick's LLM orchestrator |
| **Amazon Quick (web/Suite)** | No | Streamable HTTP | No (public HTTPS) | tunnel + Enterprise/trial | Three-tool + RFC 9728/DCR discovery, Draft 7 validation, static tool list |

### Recommended test order on Windows

**Phase 0 — Protocol sanity (5 min, no client install):**
1. Start backend (`uv run legal-research-agent`) + adapter (`uv run legal-research-mcp`) on Windows.
2. `npx @modelcontextprotocol/inspector` → Streamable HTTP → `http://127.0.0.1:8001/mcp` → tools/list + tools/call. Verify all 4 tools, `submit_research` returns `_meta.ui.resourceUri`, `get_status` holds open and streams progress, `get_result` returns structured report.

**Phase 1 — Widget validation (the critical path, ~30 min):**
3. **VS Code Copilot Chat** (fastest widget loop): install VS Code + Copilot Chat extension → `.vscode/mcp.json` with `{"servers":{"legal-mcp":{"type":"http","url":"http://127.0.0.1:8001/mcp"}}}` → new chat → "research whether non-competes are enforceable in California" → widget renders inline, polls `get_status`, on completion calls `get_result` + `updateModelContext` + `ui/message`. **This validates the entire widget recipe on a Copilot surface with zero tunnel/publish.**
4. **Claude Desktop (native stdio)**: see §22 for the stdio setup → `claude_desktop_config.json` → restart Claude Desktop → same prompt → widget renders, polls, completes. **This validates the widget on Claude Desktop.** If the widget stays `visibility: hidden`, you hit the handshake bug — confirm you're using native stdio (not `mcp-remote`).

**Phase 2 — Three-tool validation (~20 min):**
5. **Amazon Quick desktop app**: install Quick desktop app → Settings → Capabilities → MCP → + Add → Remote → `http://127.0.0.1:8001/mcp` → no token → test actions. Verify `submit_research` → `get_status` (holds ~25s, streams progress, returns `next_step` message) → `get_result`. **This validates the three-tool pattern and Quick's 60s timeout boundary.**
6. **Claude Desktop (remote connector, optional)**: cloudflared/devtunnel + `none` auth → Settings → Connectors → Add custom connector → tunnel URL → new chat. Validates the production remote-connector path (not just stdio).

**Phase 3 — Production fidelity (optional, ~1-2 hr):**
7. **M365 Copilot (Cowork)**: devtunnel + Power Platform custom connector (`x-ms-agentic-protocol: mcp-streamable-1.0`) + publish → `m365.cloud.microsoft/chat`. Validates the full Copilot production flow including the `connectDomains` CSP drop and 60/min widget poll ceiling. This is where you'd reproduce your original SSE-closing bug — except now the widget polls via `callServerTool` instead, so it should work.
8. **Amazon Quick (web/Suite)**: tunnel + Enterprise/trial → Connectors → Create MCP → URL → None auth → Test action APIs. Validates RFC 9728/DCR, Draft 7 schema validation, static tool list, Quick's LLM orchestrator.

### What each surface uniquely validates (can't be substituted)

| Test | Only works in | Why |
|---|---|---|
| Widget rendering on Claude | Claude Desktop (stdio or remote) | Only Anthropic host that renders `ui://` |
| Widget rendering on Copilot | VS Code Copilot Chat or M365 Copilot | Only MS hosts that render `ui://` |
| `connectDomains` CSP drop (your original bug) | M365 Copilot (Cowork) only | VS Code doesn't drop `connectDomains` |
| 60/min widget poll ceiling | M365 Copilot (Cowork) only | VS Code has no such ceiling |
| 60s → HTTP 424 timeout | Amazon Quick only | Unique timeout enforcement |
| Quick's LLM tool-selection orchestrator | Amazon Quick only | Unique orchestration layer |
| JSON Schema Draft 7 validation at publish | Amazon Quick only | Unique publish-time validation |
| 240s cap on ALL transports | Claude Desktop Windows | macOS stdio gets only 60s |

### Practical notes for the Windows move

- **Both projects are uv-based Python projects** — they run on Windows. Install `uv` on Windows (`powershell -c "irm https://astral.sh/uv/install.ps1 | iex"`), then `uv sync && uv run legal-research-agent` and `uv sync && uv run legal-research-mcp` in each directory. Copy the two project directories over (or `git clone` from your repos).
- **Use `MOCK_TIME_SCALE=0.01`** for fast iteration during testing — jobs complete in ~1-8 seconds instead of minutes. Switch to real timings only for timeout-boundary tests.
- **For the stdio setup on Claude Desktop**, the adapter needs a stdio entry point — see §22.
- **`claude_desktop_config.json` path on Windows**: `%APPDATA%\Claude\claude_desktop_config.json` (documented) — but if Claude Desktop was installed from the Microsoft Store (MSIX), the real path is `%LOCALAPPDATA%\Packages\Claude_<hash>\LocalCache\Roaming\Claude\claude_desktop_config.json`. Check both.
- **devtunnel** (Microsoft's free tunnel, alternative to cloudflared): `devtunnel host -p 8001` → get a `*.devtunnels.ms` URL. Better than cloudflared for M365 Copilot testing because it's a Microsoft domain (no CORS issues with Power Platform).

---

## 22. Claude Desktop stdio setup for widget testing

Claude Desktop's local stdio path is the **only way to test widgets on Claude Desktop without a public HTTPS tunnel**. The adapter currently runs in Streamable HTTP mode; for stdio testing, add a stdio entry point.

### What's needed

The FastMCP adapter (`legal-research-mcp`) runs in Streamable HTTP mode (`mcp.run(transport="streamable-http")`). For Claude Desktop stdio, FastMCP supports `transport="stdio"` natively — but the adapter needs a **synchronous entry point** that Claude Desktop can spawn as a subprocess. Two options:

**Option A — separate stdio entry point (recommended, no change to existing HTTP server):**
Add a `__main__.py` or a console script that runs the same FastMCP server in stdio mode. The `claude_desktop_config.json` points at this script. The HTTP server stays available for other clients (Copilot, Quick) simultaneously.

**Option B — `mcp-remote` bridge (NOT recommended for widgets):**
`npx -y mcp-remote http://127.0.0.1:8001/mcp --transport http-only` in the config. Works for tools-only testing but **leaves widgets `visibility: hidden`** (handshake bug). Use only if you can't add the stdio entry point.

### `claude_desktop_config.json` format (Option A)

```json
{
  "mcpServers": {
    "legal-research": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\path\\to\\legal-research-mcp", "python", "-m", "legal_research_mcp.stdio"],
      "env": {
        "MCP_BACKEND_URL": "http://127.0.0.1:8000"
      }
    }
  }
}
```

(The backend must be running separately in HTTP mode on port 8000 — stdio only wraps the MCP adapter, not the backend.)

### Why stdio works for widgets on Windows

- The widget HTML is delivered via `resources/read` of a `ui://` resource → injected into the iframe as `srcdoc` — **the iframe never fetches a URL from your server**, so localhost/public-HTTPS is irrelevant for the widget's own connections.
- The widget polls via `callServerTool` → `postMessage` → Claude Desktop host → `tools/call` over stdio → your server. All in-process, no network.
- The 240s cap applies to `tools/call` return only — since `submit_research` returns fast and the widget drives its own polling, the cap never bites.
- On Windows, stdio gets the full 240s ceiling (unlike macOS stdio which gets only ~60s).
