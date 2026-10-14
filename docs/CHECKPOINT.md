# Checkpoint

Overwritten at each checkpoint. History lives in git tags (`checkpoint-p0-scaffold`, `p0-done`) and in git log. Last updated: 2026-10-14.

## Where we are

**Phase P1 (ledger core and tenancy), task 1 done: schema and database invariants.** Repo: https://github.com/chintan-jikkar/fulcrum (public, so no real data goes in).

Done in task 1:
- Migration `0001_ledger_core` (hand-written SQL) creates users, counterparties, accounts, categories, transactions and postings.
- The database enforces I1, I2 and I5 (deferred constraint triggers, checked at COMMIT), I3 (check plus unique), I6 (composite FKs on `(id, user_id)`) and I7 (append-only postings, TRUNCATE refused, purge exception per D-036).
- `tests/test_ledger_schema.py`: 33 raw-SQL tests covering SCENARIOS R-04, R-06 and R-17 to R-20, plus a downgrade/upgrade round trip. Hand mutation check: narrowing the posting trigger, the category re-check, the subtype freeze, or the purge exception each fails a test. `world_legs = 1` vs `>= 1` is untestable, since I3 and one `world` per user make two world legs impossible.
- CI's `backend` job now has a Postgres 16 service. Not yet run in CI: push and check.

Things to know:
- Tests need Postgres on `DATABASE_URL` (default: the compose `db`). Run `docker compose up -d --wait db` first. Each run drops and recreates `fulcrum_test`.
- D-035 (account type is fixed) is PENDING the owner's yes.
- The deployed API must not connect as the table owner, or it could drop the I7 trigger (D-036). Settle this with O-2.
- `api` still has no healthcheck; the CI curl retries.

## Next steps

1. P1 task 2: `idempotency_keys` migration, SQLAlchemy models for the six tables, and idempotent provisioning (world, opening, default categories; SCENARIOS T-05). Tests first.
2. P1 task 3: the ten templates in `services/ledger.py` with I4, I8, I9, I10 and the refund rules (SCENARIOS §A, §B).
3. P1 task 4: balance and derived-figure queries, the golden month fixture (§D), Hypothesis properties (§E).
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
FULCRUM. Read docs/CLAUDE.md and docs/CHECKPOINT.md. Phase: P1. Today: write failing tests, then the idempotency_keys migration, SQLAlchemy models for the six ledger tables, and idempotent user provisioning (SCENARIOS T-05).
```

## Still open

See `docs/DECISIONS.md`, Open items O-1 to O-5. None block P1.
