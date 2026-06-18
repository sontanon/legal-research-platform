"""Job manager: in-process worker tasks + SSE pub/sub, backed by the DB.

The worker simulates a long-running, non-deterministic legal research job:
  - samples a duration (clamped normal, scaled by MOCK_TIME_SCALE);
  - emits noisy progress events at random intervals to subscriber queues;
  - persists progress to the DB (so `get_status` works without a stream);
  - on completion, builds the mock report and stores it; or fails with a
    small configurable probability.

Subscribe to a job's live events via `subscribe(job_id)`; the SSE endpoint
drains the returned queue. Late subscribers also receive the current status
first, and a terminal event immediately if the job is already done.
"""

from __future__ import annotations

import asyncio
import json
import random
import uuid
from typing import Optional

from . import content, db
from .config import settings
from .progress import next_interval_s, noisy_progress, sample_duration
from .schemas import Effort, JobCreated, JobState, JobStatus, Jurisdiction


class JobManager:
    def __init__(self) -> None:
        # job_id -> asyncio task
        self._tasks: dict[str, asyncio.Task] = {}
        # job_id -> list of subscriber queues
        self._subs: dict[str, list[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    # ---- submission ----

    async def submit(self, query: str, effort: Effort) -> JobCreated:
        job_id = uuid.uuid4().hex
        jurisdiction = content.detect_jurisdiction(query)
        duration = sample_duration(effort)

        row = db.JobRow(
            job_id=job_id,
            query=query,
            effort=effort.value,
            jurisdiction=jurisdiction.value,
            status=JobState.working.value,
            progress_pct=0.0,
            phase="researching",
            sampled_duration_s=duration,
            started_at=db._now_iso(),
        )
        await db.create_job(row)

        task = asyncio.create_task(self._run(job_id, duration, effort, query, jurisdiction))
        async with self._lock:
            self._tasks[job_id] = task

        return JobCreated(
            job_id=job_id,
            status=JobState.working,
            effort=effort,
            query=query,
            created_at=row.created_at,
        )

    # ---- status / result / cancel ----

    async def status(self, job_id: str) -> Optional[JobStatus]:
        row = await db.get_job(job_id)
        if row is None:
            return None
        return JobStatus(
            job_id=row.job_id,
            status=JobState(row.status),
            effort=Effort(row.effort),
            progress_pct=row.progress_pct,
            phase=row.phase,
            message=row.message,
            created_at=row.created_at,
        )

    async def result(self, job_id: str):
        row = await db.get_job(job_id)
        if row is None:
            return None
        from .schemas import JobResult
        if row.status == JobState.completed.value and row.report_json:
            return JobResult(job_id=job_id, status=JobState.completed, report=db.load_report(row.report_json))
        if row.status == JobState.failed.value:
            return JobResult(job_id=job_id, status=JobState.failed, error=row.error or "unknown error")
        if row.status == JobState.canceled.value:
            return JobResult(job_id=job_id, status=JobState.canceled, error="canceled")
        return JobResult(job_id=job_id, status=JobState(row.status), error="not_ready")

    async def cancel(self, job_id: str) -> Optional[JobStatus]:
        row = await db.get_job(job_id)
        if row is None:
            return None
        if row.status in {
            JobState.completed.value,
            JobState.failed.value,
            JobState.canceled.value,
        }:
            return await self.status(job_id)
        async with self._lock:
            task = self._tasks.pop(job_id, None)
        if task and not task.done():
            task.cancel()
        await db.update_job(job_id, status=JobState.canceled.value, completed_at=db._now_iso())
        await self._broadcast(job_id, {"status": JobState.canceled.value, "progress_pct": row.progress_pct})
        return await self.status(job_id)

    # ---- streaming ----

    async def subscribe(self, job_id: str) -> Optional[asyncio.Queue]:
        row = await db.get_job(job_id)
        if row is None:
            return None
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        async with self._lock:
            self._subs.setdefault(job_id, []).append(q)
        # Send current state first, and a terminal event immediately if done.
        await q.put({
            "status": row.status,
            "progress_pct": row.progress_pct,
            "phase": row.phase,
            "message": row.message,
        })
        if row.status in {JobState.completed.value, JobState.failed.value, JobState.canceled.value}:
            await q.put({"_terminal": True, "status": row.status, "error": row.error})
        return q

    def unsubscribe(self, job_id: str, q: asyncio.Queue) -> None:
        subs = self._subs.get(job_id)
        if subs and q in subs:
            subs.remove(q)

    # ---- worker ----

    async def _run(
        self,
        job_id: str,
        duration_s: float,
        effort: Effort,
        query: str,
        jurisdiction: Jurisdiction,
    ) -> None:
        total = duration_s * settings.time_scale
        loop = asyncio.get_running_loop()
        start = loop.time()
        elapsed = 0.0
        last_pct = 0.0
        try:
            while elapsed < total:
                await asyncio.sleep(next_interval_s())
                elapsed = loop.time() - start
                if elapsed >= total:
                    break
                pct, phase, complication = noisy_progress(elapsed, total, last_pct)
                last_pct = pct
                msg = complication if random.random() < 0.25 else None
                await db.update_job(job_id, progress_pct=pct, phase=phase, message=msg)
                await self._broadcast(job_id, {
                    "status": JobState.working.value,
                    "progress_pct": round(pct, 1),
                    "phase": phase,
                    "message": msg,
                })

            # Terminal state.
            if random.random() < settings.failure_prob:
                err = "research pipeline exceeded retrieval budget (simulated failure)"
                await db.update_job(
                    job_id,
                    status=JobState.failed.value,
                    progress_pct=last_pct,
                    error=err,
                    completed_at=db._now_iso(),
                )
                await self._broadcast(job_id, {"_terminal": True, "status": JobState.failed.value, "error": err})
            else:
                report = content.build_report(job_id, query, effort, jurisdiction)
                await db.update_job(
                    job_id,
                    status=JobState.completed.value,
                    progress_pct=100.0,
                    phase="finalizing report",
                    message=None,
                    report_json=db.dump_report(report),
                    completed_at=db._now_iso(),
                )
                await self._broadcast(job_id, {
                    "_terminal": True,
                    "status": JobState.completed.value,
                    "progress_pct": 100.0,
                })
        except asyncio.CancelledError:
            # Cancellation is handled by `cancel()`; just stop the worker.
            raise
        except Exception as exc:  # pragma: no cover - defensive
            await db.update_job(
                job_id,
                status=JobState.failed.value,
                error=f"worker crashed: {exc!r}",
                completed_at=db._now_iso(),
            )
            await self._broadcast(job_id, {"_terminal": True, "status": JobState.failed.value, "error": repr(exc)})
        finally:
            async with self._lock:
                self._tasks.pop(job_id, None)

    async def _broadcast(self, job_id: str, event: dict) -> None:
        async with self._lock:
            subs = list(self._subs.get(job_id, []))
        for q in subs:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Drop slow subscribers rather than blocking the worker.
                pass


manager = JobManager()
