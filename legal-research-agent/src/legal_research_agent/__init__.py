"""Mock legal research agent backend.

A small, disposable FastAPI service that simulates a long-running,
non-deterministic legal research agent. See README.md and the package modules
for details.
"""

from .main import app, main

__all__ = ["app", "main"]
