# Build/lint/test commands for this project (managed with uv).

- Install/sync deps: `uv sync`
- Run the dev server: `uv run legal-research-agent` (or `MOCK_TIME_SCALE=0.01 uv run legal-research-agent` for fast mode)
- Typecheck: `uv run python -c "import legal_research_agent"` (smoke import) — no dedicated typechecker configured yet
- No test suite yet; smoke test with curl against /docs or the endpoints in README.md
