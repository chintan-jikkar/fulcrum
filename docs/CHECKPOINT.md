# Checkpoint

Overwritten at each checkpoint. History lives in git tags. Last updated: 2026-10-14.

## Where we are

**Phase P0 (Foundation): code complete, exit criterion only partly verified.**

Done and verified locally:
- `backend/`: FastAPI app with `/health`, env-based config (`app/config.py`), SQLAlchemy engine and `Base` (`app/db.py`), Alembic wired to the same settings (no migrations yet; offline `upgrade head` runs clean).
- `ruff check`, `ruff format --check`, `mypy --strict` and `pytest` (1 test) all pass.
- `docker-compose.yml` (Postgres 16 + API), `backend/Dockerfile`, `.github/workflows/ci.yml` (lint/types/tests job and a compose smoke job), `.gitignore`, `README.md`.

**Not verified:**
- `docker compose up` has never run: Docker is not installed on this Mac.
- CI has never run: there is no GitHub remote yet.
- Alembic against a live Postgres (only the offline mode was run).

## Next steps

1. Install Docker (Docker Desktop or OrbStack), then `docker compose up --build` and open `http://127.0.0.1:8000/health`.
2. Create the GitHub repo (the free Pages plan means public; no real data goes in), push, and confirm both CI jobs go green.
3. Tag `p0-done`. P0's exit criterion is met only after steps 1 and 2.
4. Start P1.

## Model guidance

| Next work | Bigger model? | Why |
|---|---|---|
| Finish P0 (steps above) | No | Mechanical |
| P1 ledger core | **Yes** | Deferred constraint triggers (I1, I2, I5), composite-FK tenancy (I6), append-only trigger (I7), Hypothesis property tests. A subtle mistake here silently corrupts money. |
| P2 UI screens | No | Clear spec |
| P2 auth, CORS, deploy | **Yes** | Security configuration |
| P3 | No | |
| Friend gate | **Yes** | Privacy, deletion, backup restore |
| P4 wage engine | Maybe | Arithmetic is settled against a real stub (O-5); the rest is routine |
| P5 statement import | **Yes** | Parsing is messy and judgment-heavy |
| P6 mobile | No | |

## Resume prompt

```
FULCRUM. Read docs/CLAUDE.md and docs/CHECKPOINT.md. Phase: P1. Today: <task>.
```

## Still open

See `docs/DECISIONS.md`, Open items O-1 to O-5. None block P1.
