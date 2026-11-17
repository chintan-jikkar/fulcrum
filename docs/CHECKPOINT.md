# Checkpoint

Overwritten at each checkpoint. History lives in git tags (`checkpoint-p0-scaffold`, `p0-done`) and in git log. Last updated: 2026-11-15.

## Where we are

**Phase P1 (ledger core and tenancy) is done: tasks 1 to 5. P2's screens are started and run locally (D-062); auth and deploy are not.** Repo: https://github.com/chintan-jikkar/fulcrum (public, so no real data goes in).

- Task 1 (schema): migration 0001, database invariants I1, I2, I3, I5, I6, I7.
- Task 2: migration 0002 `idempotency_keys`, models in `app/models/ledger.py` with a column drift test, `provision_user` (T-05).
- Task 3 (2026-10-19): `app/services/ledger.py` with all ten templates, `void`, `set_memo` / `set_method` / `set_category`, `create_account`, `create_counterparty`, `person_account`, `archive_account` / `unarchive_account`, `balance_raw`. Enforces I3, I4, I8, I9, I10, the refund rules, R-07, R-21 and T-02 (404 for other tenants' ids). Migration 0003 makes transaction facts fixed and voids final in the database (R-14, R-15; D-046).
- Task 4 (2026-10-21): `app/services/figures.py` (D-051 to D-053): `balances`, `net_worth` and `net_worth_outside`, `credit` and `utilization_bps`, `category_totals`, `friend_positions`, `today`. `tests/test_golden_month.py` enters SCENARIOS §D through the templates and asserts every figure in D.1 to D.7 exactly, plus T-01 and the §5 edge cases (no-limit card, credit balance, archived card, child category, user's timezone). `tests/test_properties.py` runs P-1 to P-7, P-9 and P-10 with Hypothesis against an independent Python model over two users (D-054). Hand mutation check: 17 breaks in `figures.py` (void filter, as_of bound, UTC today, rounding, archived cards, aggregate offset, outside accounts in net worth, world filter, income sign, rollup, double count, range ends, payables, no-limit cards, input checks) each fail a test. 150 tests pass locally in about 15 s.
- Task 5 (2026-11-15): `app/idempotency.py` (`idempotent()`, D-056), `app/auth.py` (`current_user_id`, refuses with 401 until O-1; D-055), and the first routes in `app/routers/transactions.py`: `POST /transactions/spend` and `POST /transactions/{id}/void` (D-057). `tests/test_idempotency.py` covers R-11, R-12, R-21, T-03 and P-8 over HTTP against the real database, plus the in-flight 409 (a real two-request race), stored rejections, the 7-day window, a missing key, a crashed request and the 401. Hand mutation check: 10 breaks in the idempotency code each fail a test. 163 tests pass locally in about 22 s.
- P2 so far (2026-11-15): the API the screens need (D-059) in `app/routers/transactions.py` and `app/routers/book.py`, with `tests/test_api.py` checking every figure against a hand calculation; a local dev sign-in (`DEV_AUTH_SUB`, D-058); fictional demo data (`app/seed.py`); and the web app in `web/` (D-060): overview, activity, friends, add transaction, add account. Checked by hand in the browser at desktop and phone sizes, light and dark: a spend entered through the sheet moved net worth, the wallet and the Food total by exactly its amount, and a void moved them back. 184 backend tests pass; `npm run build` passes. The web app has no tests of its own.
- **The P1 exit criteria hold:** the golden month is exact, card payments provably stay out of every category total (D.3 test, P-5), and the two-tenant tests pass (T-01, P-6).
- `tests/test_ledger_service.py` covers SCENARIOS S-01 to S-12 and R-01 to R-10, R-13 to R-16, R-21, T-02, plus a refund-cap race. 123 tests pass locally. Hand mutation check: 15 removed or weakened rules (locks, I4, I8 kind and archive, I9, I10, refund cap and category, R-10, cascade, void into archived, input types, tenancy) each fail a test.

Things to know:
- Tests need Postgres on `DATABASE_URL` (default: the compose `db`). Run `docker compose up -d --wait db` first. Each run drops and recreates `fulcrum_test`.
- PENDING the owner's yes: D-035 (account type is fixed), D-048 (refunds follow their spend's category; no void into an archived account) and D-061 (the web app parses typed amounts into cents).
- Only the refund-cap race has a test. The I10 and archive-vs-post locks (D-049) are reasoned, not tested.
- A process killed mid-request leaves its key in flight: 409 until it expires after 7 days. The client retries with a new key (D-056).
- To run the app, see "Try the web app locally" in `README.md`.
- Done in the UI since P1: overview, activity (search, brand and category filters), friends, add transaction and account, Settings (profile, account rename/limit/archive, colours and light/dark), brand tiles and Logo.dev logos (D-064 to D-069).
- Not in the UI yet: linked refunds (refund of a chosen spend), editing memo/method/category, managing categories, opening balances for people. The service functions exist for all but the last.
- Logos need `LOGO_DEV_SECRET_KEY` in `backend/.env` (git-ignored); without it the app shows brand-colour tiles.
- A killed vite or uvicorn started by a Claude session may still hold ports 5173 and 8000.
- This folder is in iCloud Drive and the Mac's disk is nearly full, so macOS evicts project files and tools hang on file reads. `.venv` and `node_modules` now live behind `.nosync` symlinks (D-063). Freeing disk space or moving the repo out of `~/Documents` is the real fix.
- The deployed API must not connect as the table owner, or it could drop the triggers (D-036). Settle this with O-2.
- `api` still has no healthcheck; the CI curl retries.

## Next steps

1. Owner to use the local app and list what to add or change.
   - **Owner request, 2026-11-17, contacts for people:** when lending to or borrowing from someone, pick the person from the phone's contacts (with the user's permission) instead of typing a name. Fills the counterparty's `name` and `contact` (§3.2 already has a `contact` column). Platform reality: on the web only Chrome on Android has a contact picker (the Contact Picker API); iOS Safari and desktop browsers have none, so the web keeps typing as the fallback. The full version lands with the native app (P6, `expo-contacts`). Pick one contact at a time, never upload the whole address book, and store only what the user picked: these are real people's details, so the friend-gate privacy rules apply.
   - **Owner decision, 2026-11-17, card vault (P6, D-073):** saving full card details for copy-and-paste is built in the phone app only, never on the web or the server. Encrypted on the device with a key held by the Secure Enclave / Android Keystore, Face ID (or passcode) for each reveal, never synced to the API, no security code stored, clipboard cleared after 60 seconds, hidden from screenshots and backups.
   - **Owner request, 2026-11-17, Apple Wallet taps (P6, D-073):** bring in purchases made by tapping an iPhone or Apple Watch, as Wallet shows them. The likely route is Apple's FinanceKit (on-device, read-only, needs an entitlement Apple must grant, iOS only, Expo needs a native module). Check at P6 which cards FinanceKit actually covers (Apple Card / Cash / Savings for certain; other issuers' cards may not be), and amend CLAUDE.md §14 assumption 3 if adopted. Imported taps go through the same staged-and-confirm step as statement import (P5), with the same dedupe.
   - **Owner request, 2026-11-17, for P5 (statement import):** upload a PDF bank or card statement, or screenshots of the Apple Wallet app, to fill in transactions the owner forgot to enter. Parse → staged rows the owner corrects → commit, deduped against what is already entered (§10 P5). Apple Wallet screenshots mean image input (OCR or a vision model), not only PDF text. The brand table (D-066) can label the staged rows.
2. Owner to confirm D-035, D-048 and D-061.
3. Resolve O-1 and O-2, then auth, CORS and the first deploy.

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
FULCRUM. Read docs/CLAUDE.md and docs/CHECKPOINT.md. Phase: P2. Today: <the owner's list from using the local app, or O-1 and O-2>. Tests first for anything touching money.
```

## Still open

See `docs/DECISIONS.md`, Open items O-1 to O-5. O-1 and O-2 block P2.
