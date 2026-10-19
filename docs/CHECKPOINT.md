# Checkpoint

Overwritten at each checkpoint. History lives in git tags (`checkpoint-p0-scaffold`, `p0-done`) and in git log. Last updated: 2026-10-19.

## Where we are

**Phase P1 (ledger core and tenancy), tasks 1 to 3 done.** Repo: https://github.com/chintan-jikkar/fulcrum (public, so no real data goes in).

- Task 1 (schema): migration 0001, database invariants I1, I2, I3, I5, I6, I7.
- Task 2: migration 0002 `idempotency_keys`, models in `app/models/ledger.py` with a column drift test, `provision_user` (T-05).
- Task 3 (2026-10-19): `app/services/ledger.py` with all ten templates, `void`, `set_memo` / `set_method` / `set_category`, `create_account`, `create_counterparty`, `person_account`, `archive_account` / `unarchive_account`, `balance_raw`. Enforces I3, I4, I8, I9, I10, the refund rules, R-07, R-21 and T-02 (404 for other tenants' ids). Migration 0003 makes transaction facts fixed and voids final in the database (R-14, R-15; D-046).
- `tests/test_ledger_service.py` covers SCENARIOS S-01 to S-12 and R-01 to R-10, R-13 to R-16, R-21, T-02, plus a refund-cap race. 123 tests pass locally. Hand mutation check: 15 removed or weakened rules (locks, I4, I8 kind and archive, I9, I10, refund cap and category, R-10, cascade, void into archived, input types, tenancy) each fail a test.

Things to know:
- Tests need Postgres on `DATABASE_URL` (default: the compose `db`). Run `docker compose up -d --wait db` first. Each run drops and recreates `fulcrum_test`.
- PENDING the owner's yes: D-035 (account type is fixed) and D-048 (refunds follow their spend's category; no void into an archived account).
- Only the refund-cap race has a test. The I10 and archive-vs-post locks (D-049) are reasoned, not tested.
- R-11, R-12 and P-8 (idempotency replay) need the HTTP layer and are not done.
- The deployed API must not connect as the table owner, or it could drop the triggers (D-036). Settle this with O-2.
- `api` still has no healthcheck; the CI curl retries. Nothing calls the services over HTTP yet.

## Next steps

1. P1 task 4: net worth (both forms), utilization, category spend and income, friend position on top of `balance_raw`; the golden month (§D) as a fixture with every figure exact; Hypothesis properties P-1 to P-10 (§E) across two users. Tests first.
2. Idempotency semantics (R-11, R-12, R-21 over HTTP, P-8) with the first POST route.
3. Owner to confirm D-035 and D-048.
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
FULCRUM. Read docs/CLAUDE.md and docs/CHECKPOINT.md. Phase: P1. Today: write failing tests from SCENARIOS §D and §E, then the derived-figure queries (net worth, utilization, category totals, friend position), the golden month fixture and the Hypothesis properties.
```

## Still open

See `docs/DECISIONS.md`, Open items O-1 to O-5. None block P1.
