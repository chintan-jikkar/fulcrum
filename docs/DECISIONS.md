# FULCRUM — Decisions

Append-only. One line per decision: ID, date, status, decision, reason. To change a decision, add a new entry that says "supersedes D-nnn"; never edit or delete an old one.

Status: **LOCKED** (ledger core; see CLAUDE.md §0 for the change protocol) · **DEFAULT** (change with a new entry) · **PENDING** (needs the owner's yes before it counts).

---

## Decided by the owner

- **D-001 · 2026-10-14 · LOCKED** — Spec v1.0 locks the ledger core: CLAUDE.md §2–§7 and `SCENARIOS.md`. Reason: the owner wants the logic fixed up front so every later session follows the same rules.
- **D-002 · 2026-10-14 · DEFAULT** — Web app first, as a static SPA on GitHub Pages with a hosted Python API and Postgres; mobile moves from P2 to P6. Reason: owner's call; the same API serves mobile later. Pages is static-only, so the API and DB are hosted elsewhere.
- **D-003 · 2026-10-14 · LOCKED** — Multi-user from the first schema; friends get their own accounts, gated behind the friend gate (CLAUDE.md §7). Reason: owner's call; retrofitting tenancy into a finished ledger is far riskier than building it in.
- **D-004 · 2026-10-14 · DEFAULT** — "Hours equivalent" is parked and removed from §5 scope until the owner decides. Reason: owner said to defer it; it also depends on the wage engine (P4).

## Gaps in the original brief, closed in v1.0 (PENDING the owner's read-through)

- **D-005 · 2026-10-14 · LOCKED** — Add an `opening` EXTERNAL account per user for starting balances, and an `opening` template. Reason: the original had no way to set a starting balance; using `world` would either break the category rule or record income that never happened.
- **D-006 · 2026-10-14 · LOCKED** — `world` and `opening` are one each per *user*, created at provisioning, not once at install. Reason: tenancy (D-003).
- **D-007 · 2026-10-14 · LOCKED** — `counterparties` table, with `accounts.counterparty_id` required on receivable/payable accounts, replacing `person_name` in `meta`. Reason: "friend position" nets two accounts per person, and matching on name text breaks on a typo.
- **D-008 · 2026-10-14 · LOCKED** — Store `transactions.template`. Reason: the verb is needed for display, refund validation, and the one-opening-per-account rule; re-deriving it from account types invites bugs.
- **D-009 · 2026-10-14 · LOCKED** — `lend` may be funded from a credit card, and `card_payment` from cash. Reason: bill-splitting on a card is the common case for the friends ledger; paying a card bill in cash happens.
- **D-010 · 2026-10-14 · LOCKED** — `refund_of_id` plus rules: same category as the original, cumulative refunds cannot exceed it, a spend with live refunds cannot be voided. Reason: the original "same category" rule could not be enforced without the link.
- **D-011 · 2026-10-14 · LOCKED** — Corrections are void (cannot be undone) and re-enter. Postings are immutable; only memo, method, and category are editable. Voiding an already-void transaction returns 409. Reversing entries are out of v1. **This departs from the original brief's "prefer a reversing entry".** Reason: there are no closed periods yet, so a reversing entry would only clutter history; revisit when period close or reconciliation exists.
- **D-012 · 2026-10-14 · LOCKED** — No balance floors in the ledger. Reason: overdrafts, card credit balances, and overpaid receivables are real states.
- **D-013 · 2026-10-14 · LOCKED** — Every figure takes `as_of`, defaulting to today in the user's timezone; `users.timezone` is stored. Reason: "today" and month boundaries are undefined on a server without it, and the net-worth trend needs historical balances.
- **D-014 · 2026-10-14 · LOCKED** — Utilization is integer basis points, rounded half up. Reason: the no-float rule extends to ratios.
- **D-015 · 2026-10-14 · LOCKED** — The user-initiated tenant purge is the only hard-delete path; it lifts the posting-immutability trigger for that transaction only. Reason: reconciles "ledgers do not delete" with account-deletion requirements.
- **D-016 · 2026-10-14 · LOCKED** — Tenant isolation via composite foreign keys `(id, user_id)`; other tenants' ids return 404, not 403. Reason: isolation enforced by the schema survives a forgotten WHERE clause, and 404 leaks nothing.
- **D-017 · 2026-10-14 · LOCKED** — `idempotency_keys` table scoped per user, 7-day retention; same key with a different body, or while in flight, returns 409. Reason: the original required the header but not the semantics.
- **D-018 · 2026-10-14 · LOCKED** — Invariants I3 (non-zero amounts, distinct accounts), I9 (no archiving non-zero accounts), and I10 (one opening per account) added. Reason: closes ways to create meaningless or lossy ledger states.

## Defaults chosen for the owner (change by new entry)

- **D-019 · 2026-10-14 · DEFAULT** — Vite + React + TypeScript SPA instead of Next.js for the web app. Reason: Pages serves static files, so Next.js server features would go unused; Vite is simpler and the React knowledge carries to Expo. Router details are settled at P2 kickoff.
- **D-020 · 2026-10-14 · DEFAULT** — Python 3.12, `uv`, sync SQLAlchemy 2.0 with psycopg 3, GitHub Actions for CI. Reason: simplest toolchain the owner can debug; async adds complexity the ledger does not need.
- **D-021 · 2026-10-14 · DEFAULT** — Bearer-token auth (no cookies); CORS limited to the Pages origin and localhost. Reason: removes the CSRF surface for a cross-origin API.
- **D-022 · 2026-10-14 · DEFAULT** — Fixtures and seeds are always fictional, whatever the repo's visibility. The brief's "real month" golden scenario is replaced by a fictional one (`SCENARIOS.md` §D). Reason: free GitHub Pages implies a public repo.
- **D-023 · 2026-10-14 · DEFAULT** — Phase order: P0 foundation, P1 ledger and tenancy, P2 web shell and first deploy, P3 cards/friends/categories, friend gate, P4 wage/budgets/net worth, P5 statement import (web), P6 mobile. Reason: follows D-002; the friend gate sits before anyone else's data is stored.
- **D-024 · 2026-10-14 · DEFAULT** — Reminders on web are an in-app "due soon" list; native local notifications arrive with P6. Reason: browsers cannot reliably schedule local notifications, and push infrastructure is out of v1.
- **D-025 · 2026-10-14 · PENDING** — Assumptions 1–5 from the original brief stand (USD only, Android untested, no Plaid, one-sided friend ledger, flat withholding percentage). Reason: the owner has not corrected them; confirm explicitly.

## Added at P0

- **D-026 · 2026-10-14 · DEFAULT** — Product name is **Parity**; FULCRUM stays as the codename for the repo, folder, and session opener. Reason: owner's pick. Domain, App Store, and trademark availability are unchecked, and at least one company called Parity exists (blockchain infrastructure), so search before committing publicly.
- **D-027 · 2026-10-14 · LOCKED** — Spec v1.0 is treated as accepted: the owner read the summary and moved on to P0. This confirms D-005 to D-018 and D-025. Reason: nothing was objected to; any of them can still be superseded by a new entry.
- **D-028 · 2026-10-14 · DEFAULT** — Before each task, say whether it needs a bigger model; if so, stop at a checkpoint first (commit, tag, refresh `docs/CHECKPOINT.md`). Rule text is in CLAUDE.md §15. Reason: owner's request, so model effort is spent where mistakes are expensive.
- **D-029 · 2026-10-14 · DEFAULT** — P0 ships one `/health` test instead of a truly empty suite. Reason: pytest exits non-zero when it collects nothing, so "green on an empty suite" is not achievable literally.
- **D-030 · 2026-10-14 · DEFAULT** — P0 creates only the files it uses. The `models/`, `schemas/`, `services/`, `routers/` folders and `seed.py` arrive with P1. Reason: empty scaffolding is noise; the §9 layout is the target, not a P0 requirement.
- **D-031 · 2026-10-14 · DEFAULT** — Docker is not installed on the owner's Mac, so `docker compose up` was not run locally. A CI job (`compose`) runs it on every push, and it still needs a local run once Docker is installed. Compose ports bind to 127.0.0.1 only.
- **D-032 · 2026-10-14 · DEFAULT** — Local Python is 3.13.9 (uv used an installed interpreter); Docker and CI use 3.12, and ruff and mypy target 3.12. Reason: avoids downloading another interpreter. Revisit if a version-specific bug appears.
- **D-033 · 2026-10-14 · DEFAULT** — The container runs `alembic upgrade head` on start, for local development only. Before the P2 deploy this must become a separate release step. Reason: several instances starting together would race on migrations.

## Added at P1

- **D-034 · 2026-10-14 · DEFAULT** — The first migration enforces some §3.3 shape rules in the database beyond the I-list: kind matches subtype, `counterparty_id` set iff receivable/payable, at most one `world` and one `opening` per user, at most one receivable and one payable per counterparty, `refund_of_id` only on `refund`. Reason: each is one line of SQL, and balances, I5 and "created on first use" all rely on them.
- **D-035 · 2026-10-14 · PENDING** — An account's `kind`, `subtype` and `counterparty_id` cannot change after creation (trigger, errors as I5). Reason: I5 counts `world` legs by subtype at write time; turning a bank into `world` later would silently re-categorise its history. This is a new rule; the owner should confirm it.
- **D-036 · 2026-10-14 · LOCKED** — I7 also refuses TRUNCATE on postings. The §7 purge lifts I7 with `set_config('fulcrum.purge_user_id', <user id>, true)` inside its own database transaction: DELETE of that user's postings only, never UPDATE, and the setting ends with the transaction. Implements D-015. Reason: the narrowest exception that still allows the purge. It stops application bugs, not the database owner, so the deployed API must connect as a role that does not own the tables (P2).
- **D-037 · 2026-10-14 · DEFAULT** — Database invariant errors name their rule: trigger messages start `I<n>:` and constraints are named `i<n>_...`. Reason: the service layer can map a database error to the rule it broke without parsing prose.
- **D-038 · 2026-10-14 · DEFAULT** — DB tests run on real Postgres, in a fresh `<db>_test` database recreated each run; tests commit for real and need no cleanup. CI's `backend` job gets a Postgres 16 service. Reason: deferred triggers only fire at COMMIT, which rollback-per-test fixtures would never reach.
- **D-039 · 2026-10-14 · DEFAULT** — Migration 0001 is hand-written SQL, and SQLAlchemy models arrive with the services that use them. `idempotency_keys` gets its own migration with the idempotency work. Reason: the schema is reviewed as SQL (§15), and nothing reads it from Python yet.
- **D-040 · 2026-10-17 · DEFAULT** — Default categories: expense Food, Transport, Housing, Utilities, Subscriptions, Shopping, Health, Entertainment, Other; income Salary, Other income. No icon or color yet. Reason: covers the golden month's categories; icons and colors wait for P2's design tokens.
- **D-041 · 2026-10-17 · DEFAULT** — SQLAlchemy models declare columns only (names, types, nullability, server defaults). Constraints, partial indexes, composite FKs and triggers live in the migrations alone, and `tests/test_models.py` fails if model and migrated columns disagree. Reason: one source of truth for the rules; the drift test catches the rest. It already caught `str` mapping to VARCHAR instead of TEXT.
- **D-042 · 2026-10-17 · DEFAULT** — An `idempotency_keys` row is written when a POST starts, with `response_status` and `response_body` null; null status means in flight, so a replay gets 409. Status must be 100-599. The 7-day cleanup job and any `created_at` index arrive with the idempotency middleware. Reason: the in-flight state of D-017 needs a representation, and a separate column would duplicate the null.
- **D-043 · 2026-10-17 · DEFAULT** — `provision_user(session, auth_sub, display_name, timezone)` is the one service function without `user_id` first. It inserts with ON CONFLICT (auth_sub) DO NOTHING, so a racing first request waits on the unique index and then finds the committed user. `display_name` and `timezone` apply only at creation, and a name not in `zoneinfo.available_timezones()` is rejected. Reason: T-05 under concurrency; the timezone defines every date boundary (D-013), so a bad one must never be stored.
- **D-044 · 2026-10-17 · DEFAULT** — Docker is now installed on the owner's Mac; `docker compose up --build` was run locally and `/health` answered, which closes the open part of D-031. Reason: record that the P0 exit criterion now holds locally too.

---

## Open items

| ID | Question | Decide by | Recommendation |
|---|---|---|---|
| O-1 | Auth provider (Clerk / Supabase Auth / Auth0) | Start of P2 | Needs: invite-only sign-up, JWT verifiable via JWKS, account deletion support. Choose together with O-2; Supabase bundles auth and Postgres. |
| O-2 | Where the API and Postgres run | Start of P2 | Needs Postgres 16, TLS, encryption at rest, automated backups with a rehearsed restore. Check current free-tier terms (sleeping, pausing, limits) before choosing. |
| O-3 | Postgres row-level security as a second layer on top of D-016 | Before the friend gate | Lean yes if the chosen host makes it cheap; the composite foreign keys already cover the main risk. |
| O-4 | Hours equivalent: headline, toggle, or dropped | After P4 starts | Parked per D-004. |
| O-5 | Wage engine: how holdback is measured for semimonthly periods | P4 kickoff | Settle against a real pay stub, then log it. |
