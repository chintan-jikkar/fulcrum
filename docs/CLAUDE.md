# FULCRUM — Project Brief

> Spec v1.0 · locked 2026-10-14 · Product name: **Parity** (chosen 2026-10-14, availability not yet checked). FULCRUM stays as the codename for the repo, folder, and session opener. Logo is deferred until the app has been used for real.

This file is the contract for every Claude Code session on this project. Read it first, every time.

**Session opener:**

```
FULCRUM. Read docs/CLAUDE.md. Phase: <P0..P6>. Today: <task>.
```

Companion files: `docs/DECISIONS.md` (append-only log, includes open items), `docs/SCENARIOS.md` (hand-calculated test scenarios, including the golden month).

## 0. How this file is governed

Every section carries one tag:

- **[LOCKED]** — ledger logic and data rules. Changing one needs a `DECISIONS.md` entry that says "supersedes", the reason, and the updated scenario or test, all in the same commit as the code. Never change silently.
- **[DEFAULT]** — current best choice. Change it with a one-line `DECISIONS.md` entry.
- **[OPEN]** — undecided. Listed in `DECISIONS.md` under Open items, each with the point by which it must be decided.

---

## 1. What this is  [DEFAULT]

A personal finance app for a single owner first, then friends with their own accounts, built because no existing tracker models money the way it actually moves.

It tracks:

- Cash, bank accounts, and credit cards as distinct things with distinct rules
- Spending against user-defined categories
- A friends ledger — who owes whom, in cash or by bank transfer
- Budgets per category per period
- A wage engine for hourly work: hours logged, pay projected, payday recorded
- Net worth, computed rather than typed in
- Recurring expenses with due-date reminders

**Surfaces, in order:** a web app first (static single-page app on GitHub Pages talking to a hosted Python API), a native mobile app later (Expo, iOS first). Both use the same API. Bulk statement import (PDF or image) lands on the web app.

---

## 2. The one principle everything hangs on  [LOCKED]

**Every transaction is a movement between two accounts. Nothing is a bare "amount plus category."**

This is double-entry bookkeeping, and it is not optional here. Mainstream trackers model a transaction as `{amount, category}`, and that single shortcut is why they all break:

- Paying off a credit card gets counted as spending, on top of the original purchases — so the month looks twice as bad as it was
- Lending a friend $50 pollutes a spending category, when in reality cash just converted into a claim on that friend
- Net worth drifts, because nothing enforces that the books balance

Model it as movement and these problems cannot occur. Net worth becomes assets minus liabilities and is correct by construction.

**Corollary rule, enforced in the service layer and in the database:** a category may be attached to a transaction **only** when exactly one leg touches `world`. Card payments, transfers, and friend loans touch two internal accounts, therefore they cannot carry a category, therefore they can never appear as spending. That one validation is the whole defence.

**Two outside accounts, not one.** Each user has a `world` account (money entering or leaving their life: spending, income) and an `opening` account (the other side of starting balances). Starting balances must not look like income, and they cannot be uncategorised `world` legs without breaking the corollary, so they get their own outside account. Neither is ever shown as a balance.

---

## 3. Data model  [LOCKED]

Every table except `users` carries `user_id` (see §7). Money is `bigint` minor units. Dates are bare `date`; timestamps are `timestamptz` in UTC.

### 3.1 `users`

`id` uuid · `auth_sub` text unique (the auth provider's subject id) · `display_name` · `timezone` (IANA name, e.g. `America/New_York`; defines "today" and month boundaries) · `created_at`.

A user row is provisioned on first authenticated request, together with their `world` account, `opening` account, and default categories. Provisioning is idempotent.

### 3.2 `counterparties`

`id` · `user_id` · `name` · `contact` null · `is_active` · `created_at`. Unique on `(user_id, lower(name))`.

A counterparty is a person in the owner's private records. It is **not** linked to a user, even if that person also has an account. The friend ledger is one-sided in v1.

### 3.3 `accounts`

| column | type | notes |
|---|---|---|
| `id` | uuid | unique together with `user_id` |
| `user_id` | uuid | |
| `name` | text | user-facing |
| `kind` | enum | `ASSET` / `LIABILITY` / `EXTERNAL`; fixed by subtype (below) |
| `subtype` | enum | see below |
| `currency` | char(3) | `USD` only in v1, column exists anyway |
| `counterparty_id` | uuid null | required iff subtype is `receivable` or `payable` |
| `is_active` | bool | archive instead of delete |
| `meta` | jsonb | subtype-specific fields |
| `created_at` | timestamptz | |

| subtype | kind | meta / notes |
|---|---|---|
| `cash` | ASSET | physical cash on hand |
| `bank` | ASSET | `institution`, `last4`. A debit card is not an account; it is this account being spent from. |
| `credit_card` | LIABILITY | `limit_minor`, `statement_day`, `due_day`, `apr_bps`, `linked_bank_id` (same user, subtype `bank`; validated in service) |
| `receivable` | ASSET | a person who owes you. One per counterparty, created on first use. |
| `payable` | LIABILITY | a person you owe. One per counterparty, created on first use. |
| `world` | EXTERNAL | exactly one per user |
| `opening` | EXTERNAL | exactly one per user |

Categories are user-editable labels on transactions. Keeping them out of the chart of accounts means renaming "Food" to "Groceries" never touches the ledger.

### 3.4 `categories`

`id` (unique with `user_id`) · `user_id` · `name` · `icon` · `color` · `kind` (`expense` / `income`) · `parent_id` null (one level of nesting max; parent and child share a kind) · `is_archived`. A default set is copied to each new user and is fully editable.

### 3.5 `transactions`

| column | type | notes |
|---|---|---|
| `id` | uuid | unique together with `user_id` |
| `user_id` | uuid | |
| `template` | enum | `spend` / `income` / `refund` / `transfer` / `card_payment` / `lend` / `friend_repay` / `borrow` / `repay_friend` / `opening` — the verb that created it (§4) |
| `occurred_on` | date | local calendar date, no timezone |
| `memo` | text | |
| `category_id` | uuid null | **null unless exactly one leg is `world`** |
| `method` | enum null | `cash` / `bank_transfer` / `card` / `other` — mainly for the friends ledger. Zelle is `bank_transfer`. |
| `refund_of_id` | uuid null | only on `refund`, points at the spend being refunded |
| `voided_at` | timestamptz null | soft void; see §6 |
| `created_at` | timestamptz | UTC |

### 3.6 `postings`

| column | type | notes |
|---|---|---|
| `id` | uuid | |
| `user_id` | uuid | |
| `transaction_id` | uuid | |
| `account_id` | uuid | |
| `amount_minor` | bigint | signed; **positive = debit** |

### 3.7 `idempotency_keys`

`user_id` · `key` text · `request_hash` · `response_status` · `response_body` jsonb · `created_at`. Primary key `(user_id, key)`. Retained 7 days.

### 3.8 Invariants

Enforced in the service layer always, and as DB constraints or triggers wherever Postgres can express them.

| # | Invariant | Where |
|---|---|---|
| I1 | `SUM(amount_minor) = 0` for every transaction | DB (deferred constraint trigger) + service |
| I2 | Exactly 2 postings per transaction in v1 (schema allows N so splits can land later without migration) | DB (same trigger) + service |
| I3 | `amount_minor <> 0`, and the two postings are on different accounts | DB + service |
| I4 | No new posting on an inactive account | service |
| I5 | `category_id IS NOT NULL` if and only if exactly one posting hits a `world` account | DB (trigger) + service |
| I6 | Every posting, category, refund link, and counterparty belongs to the same `user_id` as its transaction. Schema-enforced with composite foreign keys `(id, user_id)`. | DB |
| I7 | Postings are append-only: no UPDATE, no DELETE. The one exception is the tenant purge in §7. | DB (trigger) |
| I8 | Category kind matches the template: `spend` and `refund` take an expense category, `income` takes an income category. The category must not be archived at write time. | service |
| I9 | An account with a non-zero balance cannot be archived. | service |
| I10 | At most one non-voided `opening` transaction per account. | service |

### 3.9 Balances

`balance_raw(account, as_of) = SUM(amount_minor)` over postings of non-voided transactions with `occurred_on <= as_of`.

- ASSET → display balance = `balance_raw`
- LIABILITY → display *owed* = `-balance_raw`
- EXTERNAL → never displayed as a balance

**No balance floors.** Overdrafts, card credit balances, and overpaid receivables are real states. The ledger accepts them; the UI may warn.

Never cache running totals. Always replay. Add materialized snapshots only when a real query gets slow, and only behind the same function signature.

---

## 4. Transaction templates  [LOCKED]

These are the user-facing verbs. Each is a service function that emits the posting pair. **The UI never constructs postings.** `X` is always a positive integer in minor units. Debit is positive.

| Template | Postings | Allowed accounts | Category |
|---|---|---|---|
| `spend` | `world +X`, `funding −X` | funding: cash, bank, credit_card | required, expense |
| `income` | `dest +X`, `world −X` | dest: cash, bank | required, income |
| `refund` | `funding +X`, `world −X` | funding: cash, bank, credit_card | required, expense |
| `transfer` | `to +X`, `from −X` | both cash or bank, different accounts | forbidden |
| `card_payment` | `card +X`, `funding −X` | card: credit_card; funding: cash, bank | forbidden |
| `lend` | `receivable:P +X`, `funding −X` | funding: cash, bank, credit_card | forbidden |
| `friend_repay` | `funding +X`, `receivable:P −X` | funding: cash, bank | forbidden |
| `borrow` | `dest +X`, `payable:P −X` | dest: cash, bank | forbidden |
| `repay_friend` | `payable:P +X`, `funding −X` | funding: cash, bank | forbidden |
| `opening` | asset: `acct +X`, `opening −X` · liability (X = amount owed): `opening +X`, `acct −X` | any non-EXTERNAL account | forbidden |

Notes:

- **Lending on a credit card is allowed.** It is how bill-splitting works: record your own share as a `spend`, then the friend's share as a `lend` on the same card. Net worth is unchanged by the `lend`.
- **Refund rules.** If `refund_of_id` is given, the original must be a non-voided `spend` of the same user, the refund takes the original's category, and the sum of non-voided refunds against it may not exceed its amount. A spend with live refunds cannot be voided until its refunds are voided.
- **Person accounts.** `lend` and `friend_repay` resolve the counterparty's `receivable`; `borrow` and `repay_friend` resolve their `payable`. The service creates the account on first use.
- **Opening balances** are the only way to give an account a starting balance. They are not spending and not income.
- **Not in v1, but the model supports it:** writing off a friend's debt (`world +X`, `receivable −X`, expense category), a friend forgiving what you owe (income), split transactions (N postings), multi-currency.

Worked examples (also test fixtures; full set in `SCENARIOS.md`):

```
$40 groceries on debit   →  world +4000, chase -4000        cat=Food
$40 groceries on card    →  world +4000, amex  -4000        cat=Food   (amex owed +40)
$200 card payment        →  amex +20000, chase -20000       cat=null   (not spending)
Lend Raj $50 cash        →  recv:Raj +5000, cash -5000      cat=null   (net worth unchanged)
Raj repays via Zelle     →  chase +5000, recv:Raj -5000     cat=null
Paycheck $600 to bank    →  chase +60000, world -60000      cat=Salary
Cash deposit $300        →  chase +30000, cash -30000       cat=null
Opening: chase $1,500    →  chase +150000, opening -150000  cat=null
Opening: amex owes $200  →  opening +20000, amex -20000     cat=null
```

---

## 5. Derived figures  [LOCKED]

All server-side, all Python, all integer arithmetic.

**Time.** Every figure takes `as_of` (default: today in the user's timezone) and includes non-voided transactions with `occurred_on <= as_of`. Period figures take an inclusive `[start, end]` date range; "this month" is the calendar month in the user's timezone.

- **Net worth** = Σ(ASSET balances) − Σ(LIABILITY owed). Equivalent form: `−(raw(world) + raw(opening))`. Both forms must always agree; that agreement is a property test.
- **Available credit** = `limit_minor − owed`. May exceed the limit if the card has a credit balance.
- **Utilization** = `max(owed, 0) × 10000 / limit_minor`, in integer basis points, rounded half up. Per card, and aggregate over cards that have a limit. Null when there is no limit.
- **Category spend for a period** = Σ `amount_minor` of the `world` posting on non-voided transactions in the period whose category is an expense category (or a child of it). Refunds carry a negative `world` leg, so they reduce the total. **Category income** = −Σ of the same for income categories. Transfers, payments, loans, and openings are structurally absent.
- **Friend position** per counterparty = `raw(receivable:P) + raw(payable:P)`. Positive: they owe you. Negative: you owe them. The UI shows the position and the transaction list behind it; a person's two accounts may each show a balance while the position is zero.
- **Hours equivalent** — **PARKED.** Not in v1 scope until the owner decides (see `DECISIONS.md`, O-4).

---

## 6. Rules the code must not break  [LOCKED]

- **Money is `bigint` minor units.** Never float, anywhere, for any reason. `Decimal` only at the serialization boundary. Basis-point and percentage maths use integers with an explicit rounding rule.
- **No money math in TypeScript.** Not available credit, not payday projection, not net worth, not a sum of a list. If a number is wrong, you should be debugging Python. The API returns both `amount_minor` and a preformatted display string.
- **Ledgers do not delete.** A mistake is corrected by **voiding**: `voided_at` is set on the transaction, it drops out of balances and reports, and it stays visible in history. A void cannot be undone; re-enter the transaction instead. Voiding an already-void transaction returns 409. Postings are immutable: amount, accounts, date, and template can never be edited in place. Only `memo`, `method`, and `category_id` (subject to I5 and I8) may be edited. Reversing-entry corrections are out of v1 because there are no closed periods to protect. The single exception to "no delete" is the user-initiated tenant purge in §7.
- **`Idempotency-Key` header on every POST**, voids included. Same key and same body returns the stored response. Same key with a different body, or while the first request is still running, returns 409. Phones and flaky networks retry, and duplicate transactions are the most corrosive bug this app can have.
- **Dates:** `occurred_on` is a bare local date. Timestamps are `timestamptz` in UTC. Do not mix them.
- **Generate the TypeScript client from FastAPI's OpenAPI schema.** CI regenerates it and fails on any diff. Hand-written fetch wrappers drift from the backend within two weeks.
- **No real data in the repo.** The repo may be public (GitHub Pages on a free plan). No secrets, no real names, no real balances in code, seeds, fixtures, or screenshots. Fixtures are always fictional.

---

## 7. Tenancy, access, and the friend gate  [LOCKED]

The app is multi-user from the first schema, because friends get their own accounts.

- **Isolation by construction.** Every row has `user_id`. Composite foreign keys make cross-tenant references impossible at the schema level (I6). Every service function takes `user_id` as its first argument and filters on it; nothing reads a global "current user".
- **404, not 403.** Another tenant's id behaves exactly like an id that does not exist.
- **Auth.** A managed provider handles sign-up, passwords, and login. FastAPI only verifies the provider's JWT (signature via JWKS) and maps `sub` to `users.auth_sub`. The API never sees a password. Tokens travel in the `Authorization: Bearer` header, never in cookies, so there is no CSRF surface. CORS allows only the Pages origin and localhost for development.
- **Sign-up is closed by default.** Accounts are created by invitation.
- **Export.** Each user can download all of their data (JSON, plus CSV of transactions).
- **Deletion.** Each user can delete their account in-app. Export is offered first. This is the only hard-delete path: one transaction purges every row for that `user_id`, which temporarily lifts I7 for that transaction only.
- **Counterparties are private to their owner.** Inviting a friend does not link their account to the counterparty record you keep for them.

**Friend gate.** Until all of these are true, the owner is the only user:

1. Privacy policy published and linked in the app
2. In-app account deletion and data export implemented and tested
3. Backup and restore documented and rehearsed once
4. Cross-tenant property tests green in CI
5. Sign-up set to invitation-only at the auth provider

---

## 8. Architecture and stack  [DEFAULT]

```
Browser ── static SPA on GitHub Pages (Vite + React + TypeScript)
   │  HTTPS · Authorization: Bearer <JWT> · Idempotency-Key on POST
   ▼
FastAPI (hosted) ──▶ PostgreSQL 16 (hosted, automated backups)
   ▲ verifies JWT against the auth provider's JWKS
Managed auth provider
```

GitHub Pages serves static files only. It hosts the web UI and nothing else; the API and the database run on separate hosting.

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 (sync, psycopg 3), Alembic, `uv` | All business logic lives here, in the language the owner can debug. Sync keeps ledger code simple. |
| DB | PostgreSQL 16 | Deferred constraint triggers for I1–I2 and I5 |
| Web | Vite + React + TypeScript, static build deployed by GitHub Actions | Pages is static; Next.js server features would be unused |
| Mobile | Expo (React Native), TypeScript — Phase P6 | App Store requires native. Reuses the API and generated client. |
| API client | `openapi-typescript`, generated, checked in at `packages/api-client` | |
| Auth | **[OPEN, O-1]** managed provider (Clerk / Supabase Auth / Auth0) | Do not hand-roll auth on an app holding other people's financial data |
| API + DB hosting | **[OPEN, O-2]** | Needs Postgres 16, TLS, encryption at rest, automated backups with a tested restore |
| UI | Glassmorphism, light + dark by system preference. Inter + Roboto Mono. | |
| CI | GitHub Actions: ruff, mypy, pytest, client-staleness check, Pages deploy | |

Two frontends at once, in a language the owner cannot yet debug alone, is how solo projects die. Web ships first; mobile waits until P6.

---

## 9. Repo layout  [DEFAULT]

```
fulcrum/
├── docs/
│   ├── CLAUDE.md            # this file
│   ├── DECISIONS.md         # append-only decision log + open items
│   └── SCENARIOS.md         # hand-calculated test scenarios
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── db.py
│   │   ├── models/          # SQLAlchemy
│   │   ├── schemas/         # Pydantic
│   │   ├── services/        # ledger.py, wage.py, budgets.py, recurring.py
│   │   ├── routers/
│   │   └── seed.py          # fictional data only
│   ├── alembic/
│   ├── tests/
│   └── pyproject.toml
├── web/                     # Vite + React SPA (P2+)
├── mobile/                  # Expo app (P6)
├── packages/api-client/     # generated TS client
├── docker-compose.yml       # local Postgres + API
└── README.md
```

---

## 10. Phases  [DEFAULT — phase order and exit criteria change only via DECISIONS.md]

Each phase has an exit criterion. Do not start the next phase until it is met. One phase per session block; one task per session.

### P0 — Foundation
Git repo, `docker-compose.yml` with Postgres, FastAPI skeleton, config via env, Alembic wired, `/health`, pytest harness, ruff + mypy, CI running lint and tests.
**Exit:** `docker compose up` works and `pytest` is green on an empty suite.

### P1 — Ledger core and tenancy (backend only, no UI)
`users`, counterparties, accounts, categories, transactions, postings, idempotency. All invariants I1–I10 enforced. All ten templates in `services/ledger.py`. Provisioning (world, opening, default categories). Balance, net worth, utilization, category-spend, and friend-position queries. Property tests with Hypothesis (list in `SCENARIOS.md` §E). The golden month from `SCENARIOS.md` §D as a fixture.
**Exit:** the golden month produces every figure in `SCENARIOS.md` exactly, a card payment provably does not appear in any category total, and the two-tenant isolation tests pass.

### P2 — Web shell, auth, first deploy
Resolve O-1 and O-2 first. Vite SPA, auth, generated TS client, design tokens, navigation. API and database deployed, owner-only. Screens: account list with balances, transaction list, add-transaction sheet covering spend / income / transfer / card payment. Opening-balance setup flow.
**Exit:** a full day of real spending gets recorded in the web app (phone browser is fine) instead of a notes app.

### P3 — Credit cards, friends, categories
Card limits, utilization rings, statement and due dates shown in an in-app "due soon" list. Friends ledger screen — tabular, per-person running position, method shown. Category management UI. Institution monogram tiles (see risk note on logos).
**Exit:** the spreadsheet is retired.

### Friend gate (between P3 and P4)
Complete the five items in §7. No friend gets an account before this.

### P4 — Wage engine, budgets, net worth
Shift logging, pay projection, payday confirmation flow, budgets per category, net worth dashboard with trend.
**Exit:** a payday is projected before it lands and recorded through the app when it does.

### P5 — Statement import (web)
Upload PDF or image of a bank or card statement → parse → staged rows → user maps and confirms → commit as transactions, with fuzzy dedupe against existing records on `(date, amount, normalized description)`.
**Exit:** one real statement imports end to end with zero duplicates.

### P6 — Mobile app
Expo project reusing the API and generated client. Local notifications for due dates driven by `/reminders/upcoming`. App Store requirements: in-app deletion and export (already done at the friend gate), privacy policy, review-ready finance-category behavior.
**Exit:** the app is on a phone via TestFlight and a day of spending is recorded there.

---

## 11. Wage engine spec (P4)  [DEFAULT — arithmetic detail OPEN, O-5]

**`wage_profiles`:** `hourly_rate_minor`, `pay_frequency` (weekly / biweekly / semimonthly), `period_anchor_date`, `payday_lag_days`, `holdback_periods` (employer holds back a period before paying), `withholding_pct`, `default_destination_account_id`, `destination_kind` (cash or bank).

**`shift_logs`:** `worked_on`, `hours` (numeric 5,2), `rate_override_minor` nullable, `note`.

**Projection:** for a pay period, `gross = Σ hours × rate`, `net = gross × (1 − withholding_pct)`, payday = period end + lag + holdback. **A projection is never a ledger entry.** It lives in its own table and the dashboard reads it as forecast. How holdback is measured for semimonthly periods (whose length varies) is settled at P4 kickoff and logged.

**Payday flow:** on or after the projected date the app surfaces a confirmation card with the projected net prefilled. The user confirms the actual amount, and only then does an `income` transaction get written. Variance between projected and actual is stored for the next projection's accuracy.

Withholding is a rough user-set percentage, not real payroll tax logic. Do not attempt FICA/state tables.

---

## 12. Budgets and recurring (P3–P4)  [DEFAULT]

**Budgets:** `category_id`, `period` (monthly in v1), `amount_minor`, `rollover` bool. Spend is computed from the ledger using the §5 rule, so it can never be polluted by transfers.

**Recurring rules:** a stored transaction template plus `cadence` and `next_due_on`. Default behavior is **propose, do not autopost** — the app raises a confirmation card on the due date. Autopost is opt-in per rule. The web app shows a `/reminders/upcoming` list; native local notifications come with P6. No push infrastructure in v1.

---

## 13. Risks, acknowledged

- **Statement parsing is not a weekend.** Layouts differ per institution, per statement redesign. This is why it is P5 and why the first version should accept a hand-corrected staging table rather than aiming for accuracy.
- **Bank logos are trademarks.** Use a licensed logo source or ship monogram tiles with brand colors.
- **The moment a friend's data is in Postgres, you are responsible for it.** That is what the friend gate is for.
- **Friend ledger is one-sided in v1.** Your records, not synced between two users. Two-sided reconciliation with invitations and dispute resolution is a whole product on its own.
- **Public repo.** Free GitHub Pages means the repo is public. The rule in §6 (no real data, no secrets) is the mitigation, and CI should include a secrets scan before the first deploy.
- **Hosting limits.** Free or cheap API and database tiers may sleep, throttle, or pause. Check the actual terms when resolving O-2, and confirm backups can be restored.
- **Apple account deletion and data export** must exist before App Store submission. They are built earlier, at the friend gate.

---

## 14. Assumptions  [carried from the original brief; stand unless corrected]

1. USD only. Multi-currency is out of scope, though the column exists.
2. Web first; iOS comes at P6, Android is untested until it is tested.
3. No Plaid or bank API connections. Manual entry plus statement import, permanently.
4. Friend ledger stays one-sided in v1.
5. Wage withholding is a user-set percentage, not real payroll tax logic.

Hours equivalent was assumption 6; it is now parked (O-4).

---

## 15. Working agreement for Claude Code sessions

- Read this file at the start of every session. If a decision in it is wrong, change the file in the same commit as the code, with a `DECISIONS.md` entry.
- **[LOCKED] sections change only by the protocol in §0.**
- Append every non-obvious choice to `docs/DECISIONS.md` with a date and a one-line reason.
- One phase, one task, per session. State the task in the opener.
- **Model check before every task.** Say up front whether the task needs a bigger model. It does for: DB triggers or migrations that enforce money invariants, property-test design, auth, tenant isolation, security config, statement parsing, or anything that would be guesswork. It does not for: scaffolding, wiring, UI from a clear spec, docs. If it does, stop at a checkpoint first (commit, tag, refresh `docs/CHECKPOINT.md`) so the next session resumes from the file, not from memory.
- Write the test before the service function for anything touching money. Scenarios in `SCENARIOS.md` are the source of truth for expected numbers.
- Never introduce a money calculation in TypeScript. If a screen needs a number the API does not return, add it to the API.
- The owner is Python-primary and new to React. Comment the TS generously; explain the React idioms the first time they appear, and the React Native ones when P6 starts.
- Migrations are always Alembic, always reviewed, never autogenerated-and-trusted.
- Never put real financial data, real names, or secrets in the repo.
