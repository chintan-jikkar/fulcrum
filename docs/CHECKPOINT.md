# Checkpoint

Overwritten at each checkpoint. History lives in git tags (`checkpoint-p0-scaffold`, `p0-done`) and in git log. Last updated: 2026-10-17.

## Where we are

**Phase P1 (ledger core and tenancy), tasks 1 and 2 done.** Repo: https://github.com/chintan-jikkar/fulcrum (public, so no real data goes in).

Done in task 1 (schema): migration `0001_ledger_core` with I1, I2, I5 (deferred constraint triggers), I3, I6 (composite FKs) and I7 (append-only postings, purge exception per D-036). 33 raw-SQL tests in `tests/test_ledger_schema.py`. CI green.

Done in task 2 (2026-10-17):
- Migration `0002_idempotency_keys`: PK `(user_id, key)`, null response = in flight (D-042).
- `app/models/ledger.py`: models for the six ledger tables plus `idempotency_keys`, columns only (D-041). `tests/test_models.py` fails on any column drift against the migrated database.
- `app/services/users.py`: `provision_user` creates the user, `world`, `opening` and the default categories (D-040) in one transaction; idempotent under a race via ON CONFLICT on `auth_sub` (D-043).
- `tests/test_provisioning.py` covers T-05, including two racing first requests and a rolled-back first request. Hand mutation check: dropping a model column, changing nullability, removing ON CONFLICT, removing the timezone check, or skipping the opening account each fails a test.
- 51 tests pass locally. Full `docker compose up --build` now runs locally too (D-044).

Things to know:
- Tests need Postgres on `DATABASE_URL` (default: the compose `db`). Run `docker compose up -d --wait db` first. Each run drops and recreates `fulcrum_test`.
- D-035 (account type is fixed) is PENDING the owner's yes.
- The deployed API must not connect as the table owner, or it could drop the I7 trigger (D-036). Settle this with O-2.
- `api` still has no healthcheck; the CI curl retries.
- Nothing calls `provision_user` yet; it gets wired to the auth dependency in P2 (O-1).

## Next steps

1. P1 task 3: the ten templates in `services/ledger.py` with I4, I8, I9, I10 and the refund rules (SCENARIOS §A, §B). Tests first.
2. P1 task 4: balance and derived-figure queries, the golden month fixture (§D), Hypothesis properties (§E).
3. Idempotency semantics (R-11, R-12, R-21, P-8) need an HTTP layer; do them with the first POST route, or as a service-level helper in task 3 if it fits.
4. Resolve O-1 and O-2 before P2.

## Model guidance

**Stay on the bigger model for the rest of P1.** Every remaining P1 task touches money.

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
FULCRUM. Read docs/CLAUDE.md and docs/CHECKPOINT.md. Phase: P1. Today: write failing tests from SCENARIOS §A and §B, then the ten transaction templates in services/ledger.py with I4, I8, I9, I10, the refund rules and void.
```

## Still open

See `docs/DECISIONS.md`, Open items O-1 to O-5. None block P1.
