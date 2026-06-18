"""Stdio entry point for Claude Desktop widget testing.

Claude Desktop's local stdio path is the only way to test MCP Apps widgets
without a public HTTPS tunnel. The remote connector requires public HTTPS
(Anthropic's cloud connects, not your device), and `mcp-remote` bridges leave
widgets `visibility: hidden` (handshake bug). Native stdio works because the
widget HTML is delivered via `resources/read` (injected as iframe srcdoc) and
the widget polls via `callServerTool` → postMessage → host → `tools/call` over
stdio — all in-process, no network needed for the widget itself.

Usage in `%APPDATA%\\Claude\\claude_desktop_config.json`:
{
  "mcpServers": {
    "legal-research": {
      "command": "uv",
      "args": ["run", "--directory", "C:\\\\path\\\\to\\\\legal-research-mcp",
               "legal-research-mcp-stdio"],
      "env": {
        "MCP_BACKEND_URL": "http://127.0.0.1:8000"
      }
    }
  }
}

The mock backend must be running separately in HTTP mode on port 8000.
"""

from __future__ import annotations

from .server import mcp


def main() -> None:
    """Run the MCP adapter in stdio mode (for Claude Desktop local config)."""
    mcp.run(transport="stdio")
