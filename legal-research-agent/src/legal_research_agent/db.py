"""Async persistence layer (SQLModel + aiosqlite).

The schema is DB-agnostic: switching to Postgres for the real backend is a
connection-string change (`db_url = postgresql+asyncpg://...`). For the mock we
use SQLite so there is zero infrastructure and jobs still survive restarts
(needed to test the "user comes back later" deep-tier flow).

Tables are auto-created on startup; no Alembic — this is a disposable mock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlmodel import Field, SQLModel, select

from .config import settings


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobRow(SQLModel, table=True):
    __tablename__ = "jobs"

    job_id: str = Field(primary_key=True)
    query: str
    effort: str
    jurisdiction: str
    status: str = Field(default="pending", index=True)
    progress_pct: float = Field(default=0.0)
    phase: Optional[str] = Field(default=None)
    message: Optional[str] = Field(default=None)
    # Sampled (real) duration in seconds, unscaled. Stored only for diagnostics;
    # NOT exposed to clients as an ETA.
    sampled_duration_s: float = Field(default=0.0)
    error: Optional[str] = Field(default=None)
    report_json: Optional[str] = Field(default=None)
    created_at: str = Field(default_factory=_now_iso)
    started_at: Optional[str] = Field(default=None)
    completed_at: Optional[str] = Field(default=None)


engine: AsyncEngine = create_async_engine(settings.db_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    # For file-based SQLite, ensure the parent directory exists (fresh clone).
    if settings.db_url.startswith("sqlite"):
        from pathlib import Path

        from sqlalchemy.engine import make_url

        path = make_url(settings.db_url).database
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def create_job(row: JobRow) -> JobRow:
    async with AsyncSessionLocal() as session:
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row


async def get_job(job_id: str) -> Optional[JobRow]:
    async with AsyncSessionLocal() as session:
        return await session.get(JobRow, job_id)


async def update_job(job_id: str, **fields) -> Optional[JobRow]:
    async with AsyncSessionLocal() as session:
        row = await session.get(JobRow, job_id)
        if row is None:
            return None
        for k, v in fields.items():
            setattr(row, k, v)
        await session.commit()
        await session.refresh(row)
        return row


async def list_jobs(limit: int = 50) -> list[JobRow]:
    async with AsyncSessionLocal() as session:
        stmt = select(JobRow).order_by(desc(JobRow.created_at)).limit(limit)
        rows = (await session.execute(stmt)).scalars().all()
        return list(rows)


def dump_report(report) -> str:
    return report.model_dump_json()


def load_report(report_json: str):
    from .schemas import LegalReport
    return LegalReport.model_validate_json(report_json)
