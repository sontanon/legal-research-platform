# Build/lint/test commands for this project (managed with uv).

- Install/sync deps: `uv sync`
- Run the MCP adapter (HTTP): `uv run legal-research-mcp` (Streamable HTTP on 127.0.0.1:8001)
- Run the MCP adapter (stdio): `uv run legal-research-mcp-stdio` (for Claude Desktop local config)
- The mock backend must be running first: `cd ../legal-research-agent && uv run legal-research-agent`
- Fast dev mode (backend): `MOCK_TIME_SCALE=0.01 uv run legal-research-agent` (in the backend dir)
- Typecheck: `uv run python -c "import legal_research_mcp"` (smoke import)
- No test suite yet; smoke test with MCP Inspector: `npx @modelcontextprotocol/inspector` → Streamable HTTP → http://127.0.0.1:8001/mcp
