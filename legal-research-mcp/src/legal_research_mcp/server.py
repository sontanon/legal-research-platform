"""FastMCP server: MCP adapter for the long-running legal research agent.

Tools (all model-visible — no visibility=["app"] to avoid FastMCP #4088/#4119):
  - submit_research(query, effort)  → returns job handle fast (+ ui:// widget ref if UI-capable)
  - get_status(job_id)              → profile-aware: held-open (three-tool) or immediate (widget-poll)
  - get_result(job_id)              → final report (or "not_ready" if not terminal)
  - cancel_research(job_id)         → cancel a running job

Resource:
  - ui://legal/progress.html        → server-rendered widget HTML (polled by the widget JS)

Per-client behavior is gated by ClientProfileResolver (capabilities → identity → default).
See integration-research-and-design.md §12-§19 for the full design.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.apps import AppConfig, ResourceCSP

from . import widget
from .backend import backend
from .config import settings
from .profiles import is_terminal, resolve_profile

mcp = FastMCP(
    "legal-research-mcp",
    instructions=(
        "Legal research agent with long-running, non-deterministic jobs (~2/5/12 min "
        "for quick/standard/deep). Progress is noisy and no ETA is available. "
        "Use submit_research to start a job. If a progress widget appears, do NOT call "
        "get_status or get_result — the widget delivers the final result automatically. "
        "If no widget appears (e.g., Amazon Quick), poll get_status (it blocks for ~25s "
        "then returns the current state) and call get_result once the job is completed. "
        "Never answer the user's legal question from your own knowledge while a job is running."
    ),
)

_WIDGET_URI = "ui://legal/progress.html"


@mcp.tool(
    app=AppConfig(resource_uri=_WIDGET_URI),
    description=(
        "Submit a legal research question for deep analysis. Returns immediately with a "
        "job_id. On UI-capable clients (Claude Desktop, Microsoft Copilot, ChatGPT), a "
        "live progress widget opens automatically — do NOT call get_status or get_result "
        "when a widget is visible; the widget delivers the final structured report into "
        "context on completion. On non-UI clients (Amazon Quick, CLI), poll get_status "
        "with the job_id until the job completes, then call get_result.\n\n"
        "Effort tiers: 'quick' (~2 min), 'standard' (~5 min), 'deep' (~12 min). "
        "Durations are non-deterministic. Output is NOT legal advice."
    ),
)
async def submit_research(
    query: str,
    effort: str = "standard",
    ctx: Context = None,
) -> dict[str, Any]:
    """Start a long-running legal research job.

    Args:
        query: The legal question to research.
        effort: One of 'quick', 'standard', 'deep' (default 'standard').
        ctx: FastMCP request context (injected).

    Returns:
        dict with job_id, status, effort, query, created_at.
        On UI-capable clients, a progress widget is also rendered.
    """
    if effort not in ("quick", "standard", "deep"):
        return {"error": f"Invalid effort '{effort}'. Must be one of: quick, standard, deep."}

    try:
        result = await backend.submit(query, effort)
    except Exception as e:
        return {"error": f"Failed to submit job to backend: {e!r}"}

    profile = resolve_profile(ctx) if ctx else None

    if profile and profile.has_ui:
        result["widget_note"] = (
            "A progress widget has been opened. Do NOT call get_status or get_result — "
            "the widget will deliver the final results automatically when the job completes."
        )
    else:
        result["polling_note"] = (
            "No progress widget is available on this client. Poll get_status with this "
            "job_id to check progress (it blocks for ~25s then returns). When status is "
            "'completed', call get_result to retrieve the report. Do NOT answer the user's "
            "legal question from your own knowledge while the job is running."
        )

    return result


@mcp.tool(
    description=(
        "Check the status of a legal research job. On non-UI clients (Amazon Quick, CLI), "
        "this tool blocks for up to ~25 seconds, streaming progress, then returns the "
        "current state — call it repeatedly until the job reaches a terminal state "
        "(completed/failed/canceled), then call get_result. On UI-capable clients where a "
        "progress widget is open, this returns the current status immediately (the widget "
        "handles polling). Do NOT answer the user's legal question from your own knowledge "
        "while the job is running. If you stop polling, tell the user to ask you to 'check "
        "the job' or 'get the results' later — you are NOT monitoring in the background."
    ),
)
async def get_status(job_id: str, ctx: Context = None) -> dict[str, Any]:
    """Get the current status of a legal research job.

    Args:
        job_id: The job ID returned by submit_research.
        ctx: FastMCP request context (injected).

    Returns:
        dict with job_id, status, effort, progress_pct, phase, message, created_at.
        On three-tool profiles, this blocks for up to hold_open_ms streaming progress.
    """
    status = await backend.status(job_id)
    if status is None:
        return {"error": f"Job '{job_id}' not found."}

    profile = resolve_profile(ctx) if ctx else None
    recipe = profile.recipe if profile else "three-tool"

    if recipe == "three-tool" and not is_terminal(status.get("status", "")):
        return await _held_open_status(job_id, status, ctx)

    return status


async def _held_open_status(
    job_id: str, initial: dict[str, Any], ctx: Context | None
) -> dict[str, Any]:
    """Hold the tool call open for hold_open_ms, streaming progress, then return."""
    hold_ms = settings.three_tool_hold_ms
    interval = settings.hold_poll_interval_s
    deadline = time.monotonic() + hold_ms / 1000.0
    current = initial

    while time.monotonic() < deadline:
        pct = current.get("progress_pct", 0.0)
        if ctx:
            try:
                await ctx.report_progress(progress=pct, total=100.0)
            except Exception:
                pass

        await asyncio.sleep(interval)
        status = await backend.status(job_id)
        if status is None:
            return {"error": f"Job '{job_id}' disappeared during polling."}
        current = status
        if is_terminal(current.get("status", "")):
            break

    if is_terminal(current.get("status", "")):
        if current["status"] == "completed":
            current["next_step"] = "Job completed. Call get_result to retrieve the report."
        elif current["status"] == "failed":
            current["next_step"] = f"Job failed: {current.get('message', 'unknown error')}. Call get_result for details."
        else:
            current["next_step"] = f"Job was {current['status']}."
    else:
        current["next_step"] = (
            f"Job is still running ({current.get('progress_pct', 0):.1f}% complete, "
            f"phase: {current.get('phase', 'unknown')}). I am NOT monitoring it in the "
            f"background. To check again, call get_status with job_id '{job_id}'. "
            f"To get results once complete, call get_result. Do NOT answer the user's "
            f"legal question from your own knowledge."
        )

    return current


@mcp.tool(
    description=(
        "Retrieve the final report for a completed legal research job. Returns the "
        "structured legal report (summary, risk score, citations, sections, disclaimer) "
        "if the job is completed, or an error description if it failed. If the job is "
        "still running, returns status='working' and error='not_ready' — call get_status "
        "first to check if the job is done. Output is NOT legal advice."
    ),
)
async def get_result(job_id: str) -> dict[str, Any]:
    """Retrieve the final report for a legal research job.

    Args:
        job_id: The job ID returned by submit_research.

    Returns:
        dict with job_id, status, report (if completed), error (if failed or not ready).
    """
    result = await backend.result(job_id)
    if result is None:
        return {"error": f"Job '{job_id}' not found."}
    return result


@mcp.tool(
    description=(
        "Cancel a running legal research job. Returns the final (canceled) status. "
        "If the job is already terminal (completed/failed/canceled), returns its "
        "current status without doing anything."
    ),
)
async def cancel_research(job_id: str) -> dict[str, Any]:
    """Cancel a running legal research job.

    Args:
        job_id: The job ID returned by submit_research.

    Returns:
        dict with the job's (now canceled) status.
    """
    result = await backend.cancel(job_id)
    if result is None:
        return {"error": f"Job '{job_id}' not found."}
    return result


@mcp.resource(
    _WIDGET_URI,
    name="Legal Research Progress Widget",
    description="Live progress widget for legal research jobs. Polls get_status and delivers the final report into model context on completion.",
    app=AppConfig(
        csp=ResourceCSP(),
        prefers_border=True,
    ),
)
async def progress_widget() -> str:
    """Server-render the widget HTML.

    The widget is the same for all UI-capable clients (hand-rolled postMessage client,
    polls get_status via tools/call). No external assets — fully self-contained.
    """
    from .profiles import _DEFAULT

    return widget.render_widget(_DEFAULT)
