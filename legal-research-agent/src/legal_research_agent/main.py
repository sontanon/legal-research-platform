"""FastAPI app for the mock legal research backend.

Endpoints:
  POST   /jobs                  submit a research job {query, effort}
  GET    /jobs/{id}             get status (no ETA exposed)
  GET    /jobs/{id}/result      get the final report (409 if not done)
  GET    /jobs/{id}/stream      SSE stream of progress events until terminal
  DELETE /jobs/{id}             cancel a running job
  GET    /jobs                  list recent jobs (diagnostics)
  GET    /health                liveness
  GET    /                      service info
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from . import db
from .config import settings
from .jobs import manager
from .schemas import Effort, Health, JobCreate, JobState


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield


app = FastAPI(
    title="Mock Legal Research Agent",
    description="Long-running, non-deterministic mock backend for integration testing. Not legal advice.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/", tags=["meta"])
def root():
    return {
        "service": "mock-legal-research-agent",
        "docs": "/docs",
        "endpoints": ["/jobs", "/jobs/{id}", "/jobs/{id}/result", "/jobs/{id}/stream"],
        "note": "Output is simulated and is NOT legal advice.",
    }


@app.get("/health", response_model=Health, tags=["meta"])
def health():
    return Health(status="ok")


@app.post("/jobs", status_code=202, tags=["jobs"])
async def create_job(body: JobCreate):
    created = await manager.submit(body.query, body.effort)
    return created


@app.get("/jobs/{job_id}", tags=["jobs"])
async def get_status(job_id: str):
    status = await manager.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="job not found")
    return status


@app.get("/jobs/{job_id}/result", tags=["jobs"])
async def get_result(job_id: str):
    result = await manager.result(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="job not found")
    if result.status not in {JobState.completed, JobState.failed, JobState.canceled}:
        return JSONResponse(status_code=409, content=result.model_dump())
    return result


@app.delete("/jobs/{job_id}", tags=["jobs"])
async def cancel_job(job_id: str):
    status = await manager.cancel(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="job not found")
    return status


@app.get("/jobs", tags=["jobs"])
async def list_jobs(limit: int = 50):
    rows = await db.list_jobs(limit=limit)
    return [
        {
            "job_id": r.job_id,
            "status": r.status,
            "effort": r.effort,
            "jurisdiction": r.jurisdiction,
            "progress_pct": r.progress_pct,
            "phase": r.phase,
            "created_at": r.created_at,
            "completed_at": r.completed_at,
        }
        for r in rows
    ]


@app.get("/jobs/{job_id}/stream", tags=["jobs"])
async def stream_job(job_id: str):
    queue = await manager.subscribe(job_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="job not found")

    async def event_generator():
        try:
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=120.0)
                terminal = event.pop("_terminal", False)
                # Always include job_id for client convenience.
                event["job_id"] = job_id
                yield {"event": "status" if terminal else "progress", "data": json.dumps(event)}
                if terminal:
                    break
        except asyncio.TimeoutError:
            # No events for 120s (e.g., a very long stall): send a keep-alive
            # comment and let the client reconnect. The job is still running.
            yield {"comment": "keep-alive"}
        finally:
            manager.unsubscribe(job_id, queue)

    return EventSourceResponse(event_generator())


def main() -> None:
    """Entry point for the `legal-research-agent` console script."""
    import uvicorn

    uvicorn.run(
        "legal_research_agent.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
