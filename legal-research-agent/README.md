# Mock Legal Research Agent

A small, disposable FastAPI backend that simulates a **long-running,
non-deterministic** legal research agent. It exists to let us build and test the
MCP/A2A integration adapters under realistic timing and progress conditions
before the real backend is ready.

> **Not legal advice.** All output is simulated and fabricated. See the
> `disclaimer` field on every report.

## Why this exists

The real agent takes ~2 / ~5 / ~12 minutes per effort tier, cannot reliably
estimate its own completion time, and gives only noisy progress. This mock
reproduces that behavior (random durations, jittery/stalling progress, no ETA,
occasional simulated failures) so adapter UX (widgets, polling, the "honest
comeback" flow) can be exercised realistically.

## Effort tiers (configurable)

| Tier   | Mean | SD  | Clamp        |
|--------|------|-----|--------------|
| quick  | 2m   | 15s | [60s, 180s]  |
| standard | 5m | 1m  | [180s, 600s] |
| deep   | 12m  | 3m  | [300s, 1200s]|

`MOCK_TIME_SCALE` multiplies durations and progress intervals — set `0.01` to
make a 2-minute job finish in ~1.2s for local development.

## Quickstart

```bash
uv sync
cp .env.example .env          # optional; defaults are fine
uv run legal-research-agent   # starts uvicorn on 127.0.0.1:8000
```

Interactive docs at <http://127.0.0.1:8000/docs>.

### Fast dev mode

```bash
MOCK_TIME_SCALE=0.01 uv run legal-research-agent
```

## API

| Method | Path                     | Notes                                              |
|--------|--------------------------|----------------------------------------------------|
| POST   | `/jobs`                  | body `{query, effort}`; returns 202 + `job_id`     |
| GET    | `/jobs/{id}`             | status; **no ETA field** (progress is noisy)       |
| GET    | `/jobs/{id}/result`      | final report; 409 if not yet terminal              |
| GET    | `/jobs/{id}/stream`      | SSE: `progress` events, then a terminal `status`   |
| DELETE | `/jobs/{id}`             | cancel a running job                               |
| GET    | `/jobs`                  | list recent jobs (diagnostics)                     |
| GET    | `/health`                | liveness                                           |

### Example

```bash
# submit (California keyword → CA-specific output)
curl -sX POST localhost:8000/jobs -H 'content-type: application/json' \
  -d '{"query":"Are non-competes enforceable for software engineers in California?","effort":"quick"}'

# status
curl -s localhost:8000/jobs/<job_id>

# result (once completed)
curl -s localhost:8000/jobs/<job_id>/result

# live stream
curl -N localhost:8000/jobs/<job_id>/stream
```

## Progress model

Progress is deliberately unreliable, matching the real system:

- events at **random intervals** (exponential, mean `MOCK_PROGRESS_INTERVAL_MEAN_S`);
- percentage is a **noisy** function of elapsed/total with **stalls** (same pct
  repeated) and rare **small regressions**;
- **phase** labels (`researching`, `analyzing jurisdictions`, ...) at **jittery**
  thresholds;
- occasional **complication** messages (e.g. "encountered conflicting case law");
- **no ETA** is ever reported — a client cannot reliably predict completion;
- a small `MOCK_FAILURE_PROB` (default 5%) ends jobs in `failed` to exercise the
  failure UX.

## Storage

SQLite via SQLModel (`./data/jobs.db`). Jobs survive restarts (needed to test the
"user comes back later" deep-tier flow). The schema is DB-agnostic — switching
the real backend to Postgres is a connection-string change
(`MOCK_DB_URL=postgresql+asyncpg://...`).

## Layout

```
src/legal_research_agent/
  config.py    env-driven settings (durations, scale, failure prob, db url)
  schemas.py   pydantic API models (Effort, JobState, JobStatus, LegalReport, ...)
  db.py        SQLModel JobRow + async CRUD (aiosqlite)
  content.py   mock legal content (CA/NY/general × quick/standard/deep)
  progress.py  non-deterministic duration sampling + noisy progress model
  jobs.py      JobManager: worker tasks + SSE pub/sub
  main.py      FastAPI app + endpoints + SSE stream
```
