# Parity (codename FULCRUM)

Personal finance built on double-entry bookkeeping. Read `docs/CLAUDE.md` first; it is the contract.

## Run

```bash
docker compose up --build        # Postgres + API at http://127.0.0.1:8000/health
```

## Backend development

```bash
cd backend
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check . && uv run mypy
```

## Docs

- `docs/CLAUDE.md` — the spec and working agreement
- `docs/SCENARIOS.md` — hand-calculated test scenarios
- `docs/DECISIONS.md` — decision log and open items
- `docs/CHECKPOINT.md` — where the project stands, for resuming a session
