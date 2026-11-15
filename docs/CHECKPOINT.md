# Checkpoint

Overwritten at each checkpoint. History lives in git tags (`checkpoint-p0-scaffold`, `p0-done`) and in git log. Last updated: 2026-11-15.

## Where we are

**Phase P1 (ledger core and tenancy) is done: tasks 1 to 5.** Repo: https://github.com/chintan-jikkar/fulcrum (public, so no real data goes in).

- Task 1 (schema): migration 0001, database invariants I1, I2, I3, I5, I6, I7.
- Task 2: migration 0002 `idempotency_keys`, models in `app/models/ledger.py` with a column drift test, `provision_user` (T-05).
- Task 3 (2026-10-19): `app/services/ledger.py` with all ten templates, `void`, `set_memo` / `set_method` / `set_category`, `create_account`, `create_counterparty`, `person_account`, `archive_account` / `unarchive_account`, `balance_raw`. Enforces I3, I4, I8, I9, I10, the refund rules, R-07, R-21 and T-02 (404 for other tenants' ids). Migration 0003 makes transaction facts fixed and voids final in the database (R-14, R-15; D-046).
- Task 4 (2026-10-21): `app/services/figures.py` (D-051 to D-053): `balances`, `net_worth` and `net_worth_outside`, `credit` and `utilization_bps`, `category_totals`, `friend_positions`, `today`. `tests/test_golden_month.py` enters SCENARIOS §D through the templates and asserts every figure in D.1 to D.7 exactly, plus T-01 and the §5 edge cases (no-limit card, credit balance, archived card, child category, user's timezone). `tests/test_properties.py` runs P-1 to P-7, P-9 and P-10 with Hypothesis against an independent Python model over two users (D-054). Hand mutation check: 17 breaks in `figures.py` (void filter, as_of bound, UTC today, rounding, archived cards, aggregate offset, outside accounts in net worth, world filter, income sign, rollup, double count, range ends, payables, no-limit cards, input checks) each fail a test. 150 tests pass locally in about 15 s.
- Task 5 (2026-11-15): `app/idempotency.py` (`idempotent()`, D-056), `app/auth.py` (`current_user_id`, refuses with 401 until O-1; D-055), and the first routes in `app/routers/transactions.py`: `POST /transactions/spend` and `POST /transactions/{id}/void` (D-057). `tests/test_idempotency.py` covers R-11, R-12, R-21, T-03 and P-8 over HTTP against the real database, plus the in-flight 409 (a real two-request race), stored rejections, the 7-day window, a missing key, a crashed request and the 401. Hand mutation check: 10 breaks in the idempotency code each fail a test. 163 tests pass locally in about 22 s.
- **The P1 exit criteria hold:** the golden month is exact, card payments provably stay out of every category total (D.3 test, P-5), and the two-tenant tests pass (T-01, P-6).
- `tests/test_ledger_service.py` covers SCENARIOS S-01 to S-12 and R-01 to R-10, R-13 to R-16, R-21, T-02, plus a refund-cap race. 123 tests pass locally. Hand mutation check: 15 removed or weakened rules (locks, I4, I8 kind and archive, I9, I10, refund cap and category, R-10, cascade, void into archived, input types, tenancy) each fail a test.

Things to know:
- Tests need Postgres on `DATABASE_URL` (default: the compose `db`). Run `docker compose up -d --wait db` first. Each run drops and recreates `fulcrum_test`.
- PENDING the owner's yes: D-035 (account type is fixed) and D-048 (refunds follow their spend's category; no void into an archived account).
- Only the refund-cap race has a test. The I10 and archive-vs-post locks (D-049) are reasoned, not tested.
- A process killed mid-request leaves its key in flight: 409 until it expires after 7 days. The client retries with a new key (D-056).
- Only spend and void have routes. Responses carry no `amount_minor` or display string yet (D-057).
- This folder is in iCloud Drive and the Mac's disk is nearly full, so macOS evicts project files and `backend/.venv`; tests then hang on file reads. Point `UV_PROJECT_ENVIRONMENT` at a folder outside iCloud, or move the repo.
- The deployed API must not connect as the table owner, or it could drop the triggers (D-036). Settle this with O-2.
- `api` still has no healthcheck; the CI curl retries.

## Next steps

1. Owner to confirm D-035 and D-048.
2. Resolve O-1 and O-2. P2 starts with them.
3. P2: web shell, auth, first deploy.

## Model guidance

P1 is done. Use the table for what comes next.

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
FULCRUM. Read docs/CLAUDE.md and docs/CHECKPOINT.md. Phase: P2. Today: decide O-1 and O-2 with the owner, then replace the body of current_user_id with JWT verification. Tests first.
```

## Still open

See `docs/DECISIONS.md`, Open items O-1 to O-5. O-1 and O-2 block P2.
