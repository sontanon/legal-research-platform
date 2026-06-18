"""Entry point for the legal-research-mcp adapter."""

from __future__ import annotations

from .config import settings
from .server import mcp


def main() -> None:
    """Run the MCP adapter (Streamable HTTP)."""
    mcp.run(
        transport="streamable-http",
        host=settings.host,
        port=settings.port,
    )
