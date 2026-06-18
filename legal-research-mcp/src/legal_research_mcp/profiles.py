"""Per-client profile resolution for feature gating.

Resolution order (per the design doc §13):
  1. Capability/extension negotiation (io.modelcontextprotocol/ui)
  2. Identity (clientInfo.name + HTTP headers)
  3. Safe default (30s, three-tool, no widget)

MVP simplification (§19): single widget-poll recipe for all UI-capable clients.
No visibility=["app"] tools; no widget-owned SSE. The profile controls:
  - Whether get_status holds open (three-tool) or returns immediately (widget).
  - The hold_open_ms for three-tool profiles.
  - The submit_research return message (widget guidance vs polling guidance).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from fastmcp import Context
from fastmcp.apps import UI_EXTENSION_ID
from fastmcp.server.dependencies import get_http_headers

from .config import settings

Recipe = Literal["widget-poll", "three-tool"]

_TERMINAL = {"completed", "failed", "canceled"}


@dataclass(frozen=True)
class ClientProfile:
    name: str
    recipe: Recipe
    has_ui: bool
    hold_open_ms: int
    poll_interval_ms: int
    cap_note: str = ""


_DEFAULT = ClientProfile(
    name="unknown",
    recipe="three-tool",
    has_ui=False,
    hold_open_ms=settings.three_tool_hold_ms,
    poll_interval_ms=2000,
    cap_note="no UI capability; three-tool pattern",
)


def resolve_profile(ctx: Context) -> ClientProfile:
    has_ui = False
    try:
        has_ui = ctx.client_supports_extension(UI_EXTENSION_ID)
    except Exception:
        pass

    headers: dict[str, str] = {}
    try:
        headers = get_http_headers() or {}
    except Exception:
        pass

    ua = (headers.get("user-agent") or "").lower()
    xms = (headers.get("x-ms-agentic-protocol") or "").lower()
    client_id = (ctx.client_id or "").lower()

    if has_ui:
        if "mcp-streamable" in xms or "copilot" in client_id or "github-copilot" in client_id:
            return ClientProfile("copilot", "widget-poll", True, 5000, settings.widget_poll_ms,
                                 "no widget SSE (CSP blocks); poll via tools/call")
        if "claude" in client_id or "claude" in ua or "anthropic" in client_id:
            return ClientProfile("claude", "widget-poll", True, 5000, settings.widget_poll_ms,
                                 "240s cap on tools/call return only; widget polls via callServerTool")
        return ClientProfile("unknown-rich", "widget-poll", True, 5000, settings.widget_poll_ms,
                             "UI-capable but unidentified; poll is the portable default")

    if "quick" in client_id or "amazon" in client_id or "aws" in client_id:
        return ClientProfile("amazon-quick", "three-tool", False, settings.three_tool_hold_ms, 2000,
                             "tools-only MCP; no UI/Tasks/Elicitation")
    return _DEFAULT


def is_terminal(status: str) -> bool:
    return status in _TERMINAL
