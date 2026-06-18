"""Async HTTP client for the mock legal research backend.

Wraps the backend's REST API (submit / status / result / cancel) so the MCP
adapter tools can call it without knowing the wire format.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import settings


class BackendClient:
    def __init__(self, base_url: str | None = None) -> None:
        self._base = (base_url or settings.backend_url).rstrip("/")
        self._client: httpx.AsyncClient | None = None

    async def _cx(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self._base, timeout=30.0)
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def submit(self, query: str, effort: str) -> dict[str, Any]:
        cx = await self._cx()
        r = await cx.post("/jobs", json={"query": query, "effort": effort})
        r.raise_for_status()
        return r.json()

    async def status(self, job_id: str) -> dict[str, Any] | None:
        cx = await self._cx()
        r = await cx.get(f"/jobs/{job_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()

    async def result(self, job_id: str) -> dict[str, Any] | None:
        cx = await self._cx()
        r = await cx.get(f"/jobs/{job_id}/result")
        if r.status_code == 404:
            return None
        if r.status_code == 409:
            return r.json()
        r.raise_for_status()
        return r.json()

    async def cancel(self, job_id: str) -> dict[str, Any] | None:
        cx = await self._cx()
        r = await cx.delete(f"/jobs/{job_id}")
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.json()


backend = BackendClient()
