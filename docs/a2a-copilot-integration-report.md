# A2A (Agent-to-Agent) Protocol + Microsoft 365 Copilot Integration Report

*Investigation conducted: June 2026*

---

## Table of Contents

1. [Executive Summary](#executive-summary)
2. [A2A vs MCP: High-Level Comparison](#a2a-vs-mcp-high-level-comparison)
3. [Microsoft 365 Copilot A2A Support Status](#microsoft-365-copilot-a2a-support-status)
4. [Amazon Quick / Amazon Q Note](#amazon-quick--amazon-q-note)
5. [A2A Core Concepts](#a2a-core-concepts)
   - Agent Cards
   - Tasks, Messages, and Artifacts
   - Parts and Multi-Modal Output
6. [Wrapping a Complex Legal Agent for A2A](#wrapping-a-complex-legal-agent-for-a2a)
   - Recommended Framework: `a2a-sdk`
   - Minimal Executor Pattern
   - Output Mapping for Legal Workflows
7. [Long-Running Tasks and Timeouts](#long-running-tasks-and-timeouts)
8. [State, Multi-Turn, and Task Continuation](#state-multi-turn-and-task-continuation)
9. [Authentication and Authorization](#authentication-and-authorization)
10. [Industry Consensus: Why MCP Has More Adoption](#industry-consensus-why-mcp-has-more-adoption)
11. [Recommended Architecture](#recommended-architecture)
12. [Official Resources and Links](#official-resources-and-links)

---

## Executive Summary

The Agent-to-Agent (A2A) protocol is an open standard originally developed by Google and now governed by the Linux Foundation's Agentic AI Foundation (AAIF). It standardizes how autonomous AI agents discover, delegate work to, and coordinate with other autonomous agents. It is intentionally **complementary** to the Model Context Protocol (MCP), which standardizes agent-to-tool communication.

For a complex legal agent that performs long-running reasoning, produces structured outputs (documents, markdown summaries, citations, risk data), and may need multi-turn clarification, **A2A is the correct protocol layer**. MCP is designed for tool calls, not agent delegation.

**Microsoft 365 Copilot has first-class, production A2A support via Copilot Studio (GA as of April 2026)** and the Work IQ API (public preview). This makes it a viable target for integrating the legal agent without rebuilding it inside the Microsoft stack.

**Amazon Quick** (AWS's "internal Copilot") does **not** support A2A natively; its external-agent integration path is MCP-based. A2A on AWS lives in Amazon Bedrock AgentCore Runtime, not the Quick product UI.

**Recommendation:** Build an A2A server around the existing legal agent using the official `a2a-sdk`, deploy it behind HTTPS with OAuth 2.0 / Microsoft Entra ID, and connect it to Copilot Studio as an external A2A agent. Use Agent Cards for capability advertisement, structured Artifacts for output, and the A2A task lifecycle (with SSE streaming or push notifications) for long-running work.

---

## A2A vs MCP: High-Level Comparison

| Dimension | MCP (Model Context Protocol) | A2A (Agent-to-Agent Protocol) |
|---|---|---|
| **Purpose** | Agent → Tools / Data / APIs | Agent → Agent (delegation & collaboration) |
| **Core unit** | Tool call (stateless, one-shot) | Task (stateful, lifecycle-managed) |
| **Discovery** | Manual config; `tools/list` at runtime | Agent Card at `/.well-known/agent-card.json` |
| **Interaction model** | Synchronous RPC | Sync, SSE streaming, async push notifications |
| **State** | Stateless per call | Stateful tasks with history & context |
| **Multi-turn** | Not native | Native via `input-required` state |
| **Long-running work** | Timeout-prone; requires polling hacks | First-class task lifecycle |
| **Return format** | Typed tool result | `Artifact` objects (text, data, files, URLs) |
| **Transport** | stdio, SSE, Streamable HTTP | JSON-RPC 2.0, HTTP+JSON, gRPC |
| **Auth** | Implementer-defined | Declared in Agent Card (OAuth 2.0, OIDC, API key, mTLS) |
| **Adoption (June 2026)** | 164M monthly SDK downloads, 10K+ servers | v1.0.1 stable, 150+ orgs, deep cloud integration |

**Key insight:** MCP is the right layer for an LLM calling a calculator, database, or API. A2A is the right layer when the callee is itself an autonomous agent that reasons, plans, takes time, and returns complex deliverables.

---

## Microsoft 365 Copilot A2A Support Status

Microsoft has committed to A2A across two surfaces:

### 1. Copilot Studio (Generally Available, April 2026)

Copilot Studio agents can natively connect to any external A2A-compliant agent. The admin flow is:

1. Open an agent in Copilot Studio.
2. Go to **Agents → Add an agent → Connect to an external agent → Agent2Agent**.
3. Enter the A2A message endpoint (e.g., `https://legal-agent.example.com/a2a/v1/message:stream`).
4. Choose authentication: **None**, **API Key**, or **OAuth 2.0**.
5. Copilot Studio resolves the Agent Card and routes matching user prompts to the external agent.

This is a proven integration path with official documentation and a Microsoft Learn training module.

### 2. Work IQ API (Public Preview)

Work IQ exposes the intelligence behind Microsoft 365 Copilot via A2A (as well as MCP and REST). This enables custom agents to call Copilot as a peer for grounded, enterprise-context-aware responses over Microsoft 365 data.

- **Base A2A endpoint:** `https://workiq.svc.cloud.microsoft/a2a/`
- **Agent Card:** `https://workiq.svc.cloud.microsoft/a2a/.well-known/agent-card.json`
- **Auth:** Microsoft Entra ID delegated authentication
- **Supported versions:** A2A v1.0 and v0.3 (v0.3 is the no-header default; send `A2A-Version: 1.0` for v1.0)
- **Note:** Word, Excel, and PowerPoint agents in the Copilot Chat UI are designed for in-product context and may not produce useful responses when invoked headlessly via A2A.

### Relevant Microsoft official statements

> "With A2A support, Copilot Studio agents can directly communicate with and delegate work to other agents—first-party, second-party, or third-party—using an open protocol that allows universal access." — Microsoft Copilot Blog, April 2026

> "Use MCP for tool and data access... Use A2A for cross-platform agent-to-agent messaging. Design for capability discovery and task contracts." — Microsoft Learn, Multi-Agent Patterns

---

## Amazon Quick / Amazon Q Note

**Amazon Quick** (launched April 28, 2026) is AWS's agentic AI workspace / "internal Copilot." It supports external integrations primarily through **MCP servers** and OpenAPI connectors, not A2A.

- Quick has a built-in MCP client and can discover MCP tools for chat agents and automations.
- There is **no first-class A2A connector** in the Amazon Quick product UI.
- A2A support on AWS lives in **Amazon Bedrock AgentCore Runtime** (Nov 2025), which can host A2A servers and act as a transparent JSON-RPC proxy.
- A legal agent deployed on Bedrock AgentCore with A2A could theoretically be bridged into Quick via MCP, but this is indirect.

**Conclusion:** For the Microsoft ecosystem, A2A is the native path. For Amazon Quick, the native path is MCP.

---

## A2A Core Concepts

### Agent Cards

An Agent Card is a JSON metadata document served at `/.well-known/agent-card.json` (per RFC 8615). It describes:

- Identity, description, version, provider
- Capabilities (streaming, push notifications, extended card)
- Skills (discrete capabilities with descriptions, examples, input/output modes)
- Endpoint URL(s) and supported protocol bindings
- Authentication schemes and requirements

It is the single source of truth for discovery and capability matching.

### Tasks, Messages, and Artifacts

- **Task:** The unit of work. Has a lifecycle (`submitted` → `working` → `completed`/`failed`/`canceled`/`rejected`, with `input-required` and `auth-required` as interrupt states).
- **Message:** A turn of communication between client and agent. Carries `Part` objects.
- **Artifact:** The actual deliverable of a task. An Artifact contains one or more `Part` objects and is returned on the completed Task. Results SHOULD be returned as Artifacts, not Messages.

### Parts and Multi-Modal Output

A `Part` is a union type containing exactly one of:

- `text` — plain or markdown text
- `data` — structured JSON
- `url` — reference to an external file or resource
- `raw` — inline binary data (base64-encoded in JSON)

This maps naturally to legal-agent outputs: markdown summaries, structured risk JSON, citation links, generated PDFs/DOCXs, and streaming progress text.

---

## Wrapping a Complex Legal Agent for A2A

### Recommended Framework: `a2a-sdk`

For an agent not built on LangChain, PydanticAI, or Google ADK, the **official `a2a-sdk`** is the best choice. It is framework-agnostic and provides:

- JSON-RPC and HTTP+JSON server bindings
- Agent Card auto-serving at `/.well-known/agent-card.json`
- Task lifecycle management
- SSE streaming (`message/stream`)
- Push notification support
- Pluggable `TaskStore` (in-memory, PostgreSQL, MySQL, SQLite)
- gRPC support (optional)

Install:

```bash
pip install "a2a-sdk[fastapi]"
```

### Minimal Executor Pattern

The only required integration point is `AgentExecutor`:

```python
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.server.apps import A2AFastAPIApplication
from a2a.types import (
    AgentCard, AgentCapabilities, AgentSkill,
    Task, TaskStatus, TaskState,
    TaskStatusUpdateEvent, TaskArtifactUpdateEvent,
)

from your_org.legal_agent import LegalAnalysisEngine


class LegalAgentExecutor(AgentExecutor):
    def __init__(self):
        self.engine = LegalAnalysisEngine()  # existing code

    async def execute(self, context: RequestContext, event_queue: EventQueue):
        user_input = context.get_user_input()

        await event_queue.enqueue_event(TaskStatusUpdateEvent(
            task_id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.working),
            final=False,
        ))

        result = await self.engine.analyze(user_input)

        artifacts = build_artifacts(result)
        for artifact in artifacts:
            await event_queue.enqueue_event(TaskArtifactUpdateEvent(
                task_id=context.task_id,
                context_id=context.context_id,
                artifact=artifact,
            ))

        await event_queue.enqueue_event(TaskStatusUpdateEvent(
            task_id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.completed),
            final=True,
        ))

    async def cancel(self, context: RequestContext, event_queue: EventQueue):
        await self.engine.cancel(context.task_id)
        await event_queue.enqueue_event(TaskStatusUpdateEvent(
            task_id=context.task_id,
            context_id=context.context_id,
            status=TaskStatus(state=TaskState.canceled),
            final=True,
        ))


agent_card = AgentCard(
    name="Legal Analysis Agent",
    description="Analyzes contracts, NDAs, and legal documents with risk assessment and citations.",
    url="https://legal-agent.example.com",
    version="1.0.0",
    capabilities=AgentCapabilities(streaming=True, pushNotifications=True),
    skills=[
        AgentSkill(
            id="contract-review",
            name="Contract Review",
            description="Reviews contracts for risks, missing clauses, and compliance issues.",
            tags=["legal", "contract", "risk"],
            examples=["Review this NDA for potential issues"],
            inputModes=["text/plain", "application/pdf"],
            outputModes=["text/markdown", "application/json"],
        ),
    ],
    defaultInputModes=["text/plain"],
    defaultOutputModes=["text/markdown", "application/json"],
)

handler = DefaultRequestHandler(
    agent_executor=LegalAgentExecutor(),
    task_store=InMemoryTaskStore(),
)

app = A2AFastAPIApplication(agent_card=agent_card, request_handler=handler).build()
```

### Output Mapping for Legal Workflows

| Legal Agent Output | A2A Mapping |
|---|---|
| Markdown summary | `TextPart` with `mediaType: "text/markdown"` |
| Structured risk scores / clause data | `DataPart` (arbitrary JSON) |
| Citations with links to internal UI | `DataPart` with URLs; or `Artifact.metadata` + `extensions` |
| Generated PDF / DOCX | `Part` with `url` or `raw` + `filename` + `mediaType` |
| Streaming progress | `TaskArtifactUpdateEvent` with `append: true` |
| Multiple deliverables | Multiple `Artifact` objects on one `Task` |

---

## Long-Running Tasks and Timeouts

This is the primary reason to prefer A2A over MCP for the legal agent. A2A supports three interaction modes:

1. **Synchronous (`message/send`, `return_immediately: false`)** — blocks until terminal or interrupted state. Suitable for sub-minute work.
2. **SSE Streaming (`message/stream`)** — holds a Server-Sent Events connection and pushes `TaskStatusUpdateEvent` and `TaskArtifactUpdateEvent` in real time. Suitable for multi-minute work with progress visibility.
3. **Push Notifications (`CreateTaskPushNotificationConfig`)** — client registers a webhook; agent POSTs updates when state changes. Suitable for minutes-to-hours work where the client cannot hold a connection.

A2A operations return a `Task` handle immediately when `return_immediately: true`, so the client never hits a network timeout waiting for the work to complete. This directly solves the MCP timeout problem (e.g., Claude Desktop's 4-minute hard limit, Claude Code's ~30-60 second socket timeout).

---

## State, Multi-Turn, and Task Continuation

A2A uses a two-level state model:

- **`contextId`** — the conversation / session. Groups related tasks and messages.
- **`taskId`** — a single unit of work with its own lifecycle.

### Multi-turn within a task

If the legal agent needs clarification, it emits `TaskState.input_required` and returns. The client sends a follow-up message with the same `taskId`, and the SDK calls `execute()` again with `context.current_task` populated.

### Continuing after a task completes

**Terminal tasks (`completed`, `failed`, `canceled`, `rejected`) cannot be restarted.** To refine or follow up, the client creates a **new task with the same `contextId`** and optionally references prior tasks via `reference_task_ids`. The agent can use the shared context and referred tasks to maintain continuity.

### Who stores what

| Data | Stored by `a2a-sdk` (`TaskStore`) | Stored by you |
|---|---|---|
| Task object, status, artifacts, history | Yes | No |
| Push notification configs | Yes | No |
| Conversation-level LLM memory across tasks | No | Yes (keyed by `contextId`) |
| Extracted domain state across turns | No | Yes (if needed) |

For production, replace `InMemoryTaskStore` with a SQL-backed store (PostgreSQL/MySQL/SQLite extras are available).

---

## Authentication and Authorization

A2A delegates authentication to standard HTTP mechanisms declared in the Agent Card using OpenAPI 3.x-style `securitySchemes` and `security` fields.

### Supported schemes

- API key (header/query/cookie)
- HTTP Bearer / Basic
- OAuth 2.0 (authorization code, client credentials, device code; PKCE support)
- OpenID Connect
- Mutual TLS

### Copilot Studio configuration

When adding the A2A connection, Copilot Studio supports:

- **None**
- **API Key**
- **OAuth 2.0** — client ID, client secret, authorization URL, token URL, refresh URL, scopes

For Entra ID / SSO, use OAuth 2.0 with the On-Behalf-Of (OBO) flow so the end user's identity propagates to the legal agent. The agent validates the JWT audience, issuer, and scopes, then enforces per-user authorization.

### Recommended Agent Card snippet

```json
{
  "securitySchemes": {
    "oauth2": {
      "oauth2SecurityScheme": {
        "flows": {
          "authorization_code": {
            "authorization_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/authorize",
            "token_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            "refresh_url": "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            "scopes": {
              "api://legal-agent/contracts:read": "Read contract analysis results"
            },
            "pkce_required": true
          }
        }
      }
    }
  },
  "securityRequirements": [
    { "oauth2": ["api://legal-agent/contracts:read"] }
  ]
}
```

### Agent Card signing

For tamper-proof discovery, sign the Agent Card with JSON Web Signatures (JWS). The `a2a-sdk` provides `create_agent_card_signer` and `create_signature_verifier` utilities.

---

## Industry Consensus: Why MCP Has More Adoption

Despite A2A being technically correct for agent-to-agent delegation, MCP is far more widely adopted. Reasons:

1. **Timing:** MCP launched November 2024; A2A launched April 2025. MCP captured developer mindshare first.
2. **Simplicity:** MCP is "wrap your API as a tool, any LLM can call it." A2A requires understanding Agent Cards, task lifecycles, and JSON-RPC.
3. **Distribution:** MCP ships in Windows 11 Copilot, Claude Desktop, Cursor, VSCode, ChatGPT. A2A has no consumer distribution; it is enterprise-first via Azure, AWS, and Google Cloud.
4. **Network effects:** 10,000+ public MCP servers create a self-reinforcing ecosystem.
5. **Use-case breadth:** Most agent systems are single-agent + tools. A2A's multi-agent coordination problem is real but smaller today.

**However, the protocols are complementary, not competitive.** The consensus architecture in 2026 is:

- **MCP** for agent-to-tool connections (APIs, databases, file systems).
- **A2A** for agent-to-agent delegation, long-running tasks, and cross-organizational collaboration.

### The Claude Desktop problem

Anthropic has not implemented A2A in Claude Desktop or Claude Code. The only path into Claude products is MCP. Teams that try to wrap complex agents as MCP tools hit well-documented issues:

- Hard timeouts (4 minutes in Claude Desktop, ~30-60 seconds in Claude Code)
- No standardized long-running task model in production clients
- Poor LLM behavior when splitting tools into `start` + `poll` patterns
- MCP Apps (interactive UIs) are Claude-specific and do not hand structured artifacts back to the orchestrator

For Claude Desktop reach, a thin MCP wrapper may still be necessary. For proper multi-agent orchestration, A2A is the right layer.

---

## Recommended Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Microsoft 365 Copilot / Copilot Studio                     │
│  (A2A client — reads Agent Card, delegates tasks)            │
│  Auth: OAuth 2.0 / Entra ID (OBO for user identity)         │
└─────────────────────┬───────────────────────────────────────┘
                      │ HTTPS + JSON-RPC / SSE
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Legal Agent A2A Server                                     │
│  ├─ `a2a-sdk` + FastAPI / Starlette                          │
│  ├─ Agent Card at `/.well-known/agent-card.json`             │
│  ├─ `AgentExecutor` wraps existing `LegalAnalysisEngine`     │
│  ├─ JWT validation middleware (Entra ID)                     │
│  ├─ PostgreSQL TaskStore for durability                      │
│  └─ Returns `Artifact` objects with markdown, data, files    │
└─────────────────────┬───────────────────────────────────────┘
                      │ internal calls
                      ▼
┌─────────────────────────────────────────────────────────────┐
│  Existing Legal Analysis Engine (unchanged)                 │
│  ├─ Document parsing                                        │
│  ├─ Risk analysis                                           │
│  ├─ Citation generation                                     │
│  └─ Report / PDF generation                                 │
└─────────────────────────────────────────────────────────────┘
```

### Optional: dual-protocol exposure

If Claude Desktop access is also required, expose a **thin MCP tool** that calls the same `LegalAnalysisEngine` but is scoped to fast, sub-timeout queries. Keep the full analysis path on A2A.

---

## Official Resources and Links

### Microsoft A2A + Copilot documentation

| Resource | URL |
|---|---|
| Connect an agent over A2A in Copilot Studio | `https://learn.microsoft.com/en-us/microsoft-copilot-studio/add-agent-agent-to-agent` |
| Add other agents overview | `https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-add-other-agents` |
| Multi-agent patterns guidance | `https://learn.microsoft.com/en-us/microsoft-copilot-studio/guidance/architecture/multi-agent-patterns` |
| Work IQ API overview | `https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/api-overview` |
| Work IQ A2A overview | `https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/a2a/overview` |
| Work IQ A2A quickstart | `https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/work-iq/a2a/quickstart` |
| Configure SSO with Microsoft Entra ID | `https://learn.microsoft.com/en-us/microsoft-copilot-studio/configure-sso` |
| Configure user authentication with Entra ID | `https://learn.microsoft.com/en-us/microsoft-copilot-studio/configuration-authentication-azure-ad` |
| Create and manage connections | `https://learn.microsoft.com/en-us/microsoft-copilot-studio/authoring-connections` |

### Training and announcements

| Resource | URL |
|---|---|
| Microsoft Learn: Build cross-platform multi-agent solutions with A2A in Copilot Studio | `https://learn.microsoft.com/en-us/training/modules/build-cross-platform-multi-agent-solutions-agent2agent-copilot-studio/` |
| Work IQ API public preview announcement | `https://techcommunity.microsoft.com/blog/copilot-studio-blog/work-iq-api-public-preview-build-copilot-powered-agents-with-a2a/4516286` |
| Copilot Studio multi-agent GA announcement | `https://www.microsoft.com/en-us/microsoft-copilot/blog/copilot-studio/new-and-improved-multi-agent-orchestration-connected-experiences-and-faster-prompt-iteration/` |
| Microsoft Agent Framework .NET A2A v1 announcement | `https://devblogs.microsoft.com/agent-framework/a2a-v1-is-here-cross-platform-agent-communication-in-microsoft-agent-framework-for-net/` |

### A2A protocol specification

| Resource | URL |
|---|---|
| A2A Protocol Specification (v1.0.0) | `https://a2a-protocol.org/v1.0.0/specification/` |
| A2A Protocol documentation home | `https://a2a-protocol.org/dev/` |
| A2A GitHub repository | `https://github.com/a2aproject/A2A` |
| A2A Python SDK (`a2a-sdk`) | `https://github.com/a2aproject/a2a-python` |
| A2A SDK Python API docs | `https://a2a-protocol.org/latest/sdk/python/api/` |
| Life of a Task | `https://a2a-protocol.org/v1.0.0/topics/life-of-a-task/` |
| Streaming & Async Operations | `https://a2a-protocol.org/dev/topics/streaming-and-async/` |
| Core Concepts (Agent Card, Task, Artifact, Part) | `https://a2a-protocol.org/dev/topics/key-concepts/` |

### AWS A2A resources (for comparison)

| Resource | URL |
|---|---|
| A2A support in Amazon Bedrock AgentCore Runtime | `https://aws.amazon.com/blogs/machine-learning/introducing-agent-to-agent-protocol-support-in-amazon-bedrock-agentcore-runtime/` |
| Bedrock AgentCore A2A protocol contract | `https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-a2a-protocol-contract.html` |
| Bedrock AgentCore A2A deployment guide | `https://aws.github.io/bedrock-agentcore-starter-toolkit/user-guide/runtime/a2a.html` |
| AWS A2A gateway sample | `https://github.com/aws-samples/sample-a2a-gateway` |
| AWS A2A agent registry | `https://github.com/awslabs/a2a-agent-registry-on-aws` |

### Community / sample implementations

| Resource | URL |
|---|---|
| Microsoft: Quickstart — connect an A2A agent to Copilot Studio | `https://microsoft.github.io/mcscatblog/posts/copilot-studio-a2a-multi-agents/` |
| Microsoft: Python agents with A2A + Copilot Studio | `https://microsoft.github.io/mcscatblog/posts/A2A-Dad-jokes-Building-Python-Agents-with-Microsoft-365-SDK-for-MCS/` |
| Legal & Compliance multi-agent hub (reference) | `https://github.com/bonaniibm/A2A_Agent_Framework` |
| Semantic Kernel A2A integration docs | `https://github.com/MicrosoftDocs/semantic-kernel-docs/blob/main/agent-framework/integrations/a2a.md` |

---

## Key Takeaways

1. **A2A is production-ready and natively supported by Microsoft 365 Copilot** through Copilot Studio (GA) and Work IQ (preview).
2. **A2A is the correct protocol for the legal agent** because it handles long-running work, multi-turn clarification, and structured deliverables natively — problems MCP only solves with workarounds.
3. **`a2a-sdk` is the best framework** for wrapping an existing, non-framework agent because it is official, framework-agnostic, and mature.
4. **Authentication is standard OAuth 2.0 / Entra ID** declared in the Agent Card; Copilot Studio consumes it directly.
5. **Terminal tasks cannot be resumed**, but new tasks in the same `contextId` can reference prior tasks for continuity.
6. **MCP remains more broadly adopted** due to timing, simplicity, and distribution, but it is the wrong layer for autonomous agent delegation. A dual-protocol approach (A2A for Copilot, MCP for Claude Desktop) may be necessary.

---

*Report prepared based on public documentation and industry sources as of June 2026.*
