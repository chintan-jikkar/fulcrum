# Checkpoint

Overwritten at each checkpoint. History lives in git tags (`checkpoint-p0-scaffold`, `p0-done`). Last updated: 2026-10-14.

## Where we are

**Phase P0 (Foundation): done and verified.** Tag `p0-done`, commit `5bc446b`. Repo: https://github.com/chintan-jikkar/fulcrum (public, so no real data goes in).

Verified:
- `docker compose up --build` works locally (OrbStack) and `/health` returns 200.
- CI is green on `5bc446b`: the `backend` job (ruff, ruff format, mypy --strict, pytest) and the `compose` job (`docker compose up --build --wait` plus a `/health` check).
- Alembic connects to the live Postgres 16 and creates `alembic_version`. There are no migrations yet.

Things to know:
- `api` has no healthcheck, so `--wait` returns before uvicorn listens. The CI curl uses `--retry-all-errors` for that reason. Add a real healthcheck if the race ever comes back.
- The test suite is one test with no database. P1 tests hit Postgres, so the CI `backend` job needs a Postgres service container the moment the first DB test lands.

## Next steps

1. Start P1 (ledger core and tenancy, backend only). First task is in the resume prompt below.
2. Resolve O-1 (auth provider) and O-2 (API and DB hosting) before P2. Neither blocks P1.

## Model guidance

**Start P1 on a bigger model.** Switch in the app before opening the session.

| Next work | Bigger model? | Why |
|---|---|---|
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
FULCRUM. Read docs/CLAUDE.md and docs/CHECKPOINT.md. Phase: P1. Today: write failing tests, then the first Alembic migration, for users, counterparties, accounts, categories, transactions and postings with invariants I1, I2, I3, I5, I6 and I7 enforced in the database.
```

## Still open

See `docs/DECISIONS.md`, Open items O-1 to O-5. None block P1.
