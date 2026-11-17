# Parity (codename FULCRUM)

Personal finance built on double-entry bookkeeping. Read `docs/CLAUDE.md` first; it is the contract.

## Run

```bash
docker compose up --build        # Postgres + API at http://127.0.0.1:8000/health
```

## Try the web app locally

Three terminals. The data is fictional demo data; `DEV_AUTH_SUB` signs every request in as one
local user and must never be set on a deployed API.

```bash
docker compose up -d --wait db
```

```bash
cd backend && uv sync && uv run alembic upgrade head && DEV_AUTH_SUB=dev-owner uv run python -m app.seed && DEV_AUTH_SUB=dev-owner uv run uvicorn app.main:app --port 8000
```

```bash
cd web && npm install && npm run dev      # then open http://localhost:5173
```

After changing an API route or schema, run `npm run gen:api` in `web/` and commit the result.

**Brand logos (optional).** Without a key, banks and shops show as brand-colour tiles. To show
real logos, create a free [Logo.dev](https://www.logo.dev) account, copy the **secret** key
(`sk_...`, not the publishable `pk_` one) and start the API with it set:

```bash
export LOGO_DEV_SECRET_KEY=sk_your_key_here
```

The API downloads each logo once into `backend/.logos/` (git-ignored) and serves it itself, so
browsers never contact Logo.dev. Delete that folder to fetch fresh copies (D-067).

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
