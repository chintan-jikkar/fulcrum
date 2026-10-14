# FULCRUM — Scenarios

Plain-English test scenarios with hand-calculated expected numbers. These are the source of truth for the ledger: tests are written from this file, not the other way round. If a scenario here is wrong, fix it here first, log it in `DECISIONS.md`, then fix the code.

All figures are integer minor units (cents). Debit is positive. Postings are written `account amount`. Every person, bank, and number below is fictional; keep it that way (the repo may be public).

The §D figures were also replayed with an independent script on 2026-10-14; every number matches.

---

## A. One scenario per template

**Base state** for every scenario in this section. Each row starts from this state independently, except rows that say "After S-nn", which build on that row:

| Account | Subtype | Raw balance | Display |
|---|---|---|---|
| Chase | bank | 150000 | $1,500.00 |
| Wallet | cash | 40000 | $400.00 |
| Amex | credit_card, limit 500000 | 0 | owed $0.00 |

Net worth = 190000 ($1,900.00).

| ID | Scenario | Postings | Category | Expected after |
|---|---|---|---|---|
| S-01 | Spend $40 groceries on debit | `world +4000, chase -4000` | Food | Chase 146000 · NW 186000 · Food +4000 |
| S-02 | Spend $40 groceries on Amex | `world +4000, amex -4000` | Food | Amex owed 4000 · Chase unchanged · NW 186000 · Food +4000 |
| S-03 | Pay $200 toward Amex from Chase (card owes $200 before) | `amex +20000, chase -20000` | none | Amex owed drops by 20000 · Chase 130000 · **NW unchanged · every category total unchanged** |
| S-04 | Lend Raj $50 cash | `recv:Raj +5000, wallet -5000` | none | Wallet 35000 · Raj position +5000 · NW 190000 unchanged · no category total changes |
| S-05 | After S-04, Raj repays $50 by Zelle | `chase +5000, recv:Raj -5000` | none | Chase 155000 · Raj position 0 · NW 190000 |
| S-06 | Paycheck $600 into Chase | `chase +60000, world -60000` | Salary (income) | Chase 210000 · NW 250000 · Salary income 60000 |
| S-07 | Deposit $300 cash into Chase | `chase +30000, wallet -30000` | none | Chase 180000 · Wallet 10000 · NW 190000 |
| S-08 | Borrow $25 from Mia by Zelle | `chase +2500, pay:Mia -2500` | none | Chase 152500 · Mia position −2500 · NW 190000 (asset +2500, owed +2500) |
| S-09 | After S-08, repay Mia $25 | `pay:Mia +2500, chase -2500` | none | Chase 150000 · Mia position 0 |
| S-10 | After S-01, refund $10 of the $40 | `chase +1000, world -1000` (`refund_of` = S-01) | Food | Chase 147000 · Food net +3000 · NW 187000 |
| S-11 | Opening balance: Amex already owes $200 | `opening +20000, amex -20000` | none | Amex owed 20000 · NW 170000 · no category total changes, no income recorded |
| S-12 | Dinner $60 on Amex, Mia's share is $20: record own share as a spend, then lend the rest on the card | `world +4000, amex -4000` (Food) and `recv:Mia +2000, amex -2000` | Food / none | Amex owed 6000 · Mia position +2000 · NW 186000 · Food +4000 only |

---

## B. Things that must be rejected

| ID | Attempt | Expected |
|---|---|---|
| R-01 | Card payment with a category | Rejected (I5) |
| R-02 | Spend with no category | Rejected (I5) |
| R-03 | Income using an expense category, or spend using an income category | Rejected (I8) |
| R-04 | Amount zero or negative | Rejected (I3) |
| R-05 | Posting on an archived account | Rejected (I4) |
| R-06 | Transfer from an account to itself | Rejected (I3) |
| R-07 | `transfer` verb with a credit card on either side | Rejected; use `card_payment` |
| R-08 | Refund larger than the original, or cumulative refunds above the original | Rejected |
| R-09 | Refund whose category differs from the original's | Rejected |
| R-10 | Void a spend that still has live refunds | Rejected until the refunds are voided |
| R-11 | Same `Idempotency-Key`, same body, sent twice | Exactly one transaction exists; second call returns the stored response |
| R-12 | Same `Idempotency-Key`, different body | 409, nothing written |
| R-13 | Archive an account whose balance is not zero | Rejected (I9) |
| R-14 | Edit amount, accounts, date, or template of an existing transaction | Rejected; void and re-enter |
| R-15 | Un-void a voided transaction | Rejected; re-enter |
| R-16 | A second non-voided `opening` for the same account | Rejected (I10) |
| R-17 | Raw SQL inserting two postings that do not sum to zero, or three postings, or one posting | Database rejects at commit (I1, I2) |
| R-18 | Raw SQL setting a category on a transaction with no `world` leg, or omitting it on one with a `world` leg | Database rejects at commit (I5) |
| R-19 | Raw SQL UPDATE or DELETE on a posting | Database rejects (I7) |
| R-20 | Raw SQL posting that points at another user's account | Database rejects (I6) |
| R-21 | Void the same transaction twice with different keys | Second call returns 409 |

---

## C. Tenancy

| ID | Scenario | Expected |
|---|---|---|
| T-01 | Users A and B run the same sequence of operations | Each user's balances, net worth, and category totals equal what a lone user would see |
| T-02 | A sends B's account id, category id, transaction id, or counterparty id in any request | 404, indistinguishable from a nonexistent id; nothing written |
| T-03 | Same `Idempotency-Key` used by A and B | Independent; neither sees the other's response |
| T-04 | A deletes their account | Every row for A is gone, B's data is untouched, B's net worth is unchanged |
| T-05 | New user's first request | `world`, `opening`, and default categories exist exactly once; a second request creates no duplicates |

---

## D. Golden month

A fictional person, March 2026, timezone `America/New_York`.

**Cast:**

| Account | Subtype | Limit |
|---|---|---|
| Chase | bank | |
| Wallet | cash | |
| Amex | credit_card | 500000 ($5,000.00) |
| Visa | credit_card | 200000 ($2,000.00) |
| recv:Tom, recv:Mia, recv:Raj | receivable | |
| pay:Mia | payable | |

**Transactions** (the minus sign is ASCII so rows can be copied into fixtures):

| ID | Date | Template | What | Postings | Category |
|---|---|---|---|---|---|
| G-01 | 02-28 | opening | Chase starts at $1,500.00 | `chase +150000, opening -150000` | none |
| G-02 | 02-28 | opening | Wallet starts at $120.00 | `wallet +12000, opening -12000` | none |
| G-03 | 02-28 | opening | Amex already owes $200.00 | `opening +20000, amex -20000` | none |
| G-04 | 02-28 | opening | Tom already owes $30.00 | `recv:Tom +3000, opening -3000` | none |
| G-05 | 03-03 | spend | Groceries $42.50, Chase debit | `world +4250, chase -4250` | Food |
| G-06 | 03-04 | spend | Coffee $6.00, cash | `world +600, wallet -600` | Food |
| G-07 | 03-05 | spend | Dinner, own share $40.00, Amex | `world +4000, amex -4000` | Food |
| G-08 | 03-05 | lend | Mia's $20.00 share of that dinner, on Amex | `recv:Mia +2000, amex -2000` | none |
| G-09 | 03-06 | lend | Lend Raj $50.00 cash | `recv:Raj +5000, wallet -5000` | none |
| G-10 | 03-07 | spend | Gas $35.00, Visa | `world +3500, visa -3500` | Transport |
| G-11 | 03-08 | spend | Subscription $15.99, Visa | `world +1599, visa -1599` | Subscriptions |
| G-12 | 03-10 | friend_repay | Tom repays $30.00 by Zelle | `chase +3000, recv:Tom -3000` | none |
| G-13 | 03-12 | transfer | Deposit $50.00 cash into Chase | `chase +5000, wallet -5000` | none |
| G-14 | 03-14 | borrow | Borrow $25.00 from Mia by Zelle | `chase +2500, pay:Mia -2500` | none |
| G-15 | 03-15 | income | Paycheck $900.00 | `chase +90000, world -90000` | Salary |
| G-16 | 03-16 | spend | Groceries $58.20, Chase debit | `world +5820, chase -5820` | Food |
| G-17 | 03-18 | refund | Refund $5.00 on G-16 | `chase +500, world -500` (`refund_of` = G-16) | Food |
| G-18 | 03-20 | friend_repay | Raj repays $30.00 cash | `wallet +3000, recv:Raj -3000` | none |
| G-19 | 03-22 | card_payment | Pay Amex $150.00 from Chase | `amex +15000, chase -15000` | none |
| G-20 | 03-26 | spend | Dining out $27.00, cash | `world +2700, wallet -2700` | Food |
| G-21 | 03-28 | repay_friend | Repay Mia $5.00 by Zelle | `pay:Mia +500, chase -500` | none |
| G-22 | 03-30 | card_payment | Pay Visa $50.00 from Chase | `visa +5000, chase -5000` | none |

### D.1 Balances as of 2026-03-31

| Account | Raw | Display |
|---|---|---|
| Chase | 220430 | $2,204.30 |
| Wallet | 1700 | $17.00 |
| recv:Tom | 0 | $0.00 |
| recv:Mia | 2000 | $20.00 |
| recv:Raj | 2000 | $20.00 |
| Amex | −11000 | owed $110.00 |
| Visa | −99 | owed $0.99 |
| pay:Mia | −2000 | owed $20.00 |
| world | −68031 | not displayed |
| opening | −145000 | not displayed |

### D.2 Net worth

- Assets: 220430 + 1700 + 0 + 2000 + 2000 = 226130
- Owed: 11000 + 99 + 2000 = 13099
- **Net worth = 213031 ($2,130.31)**
- Cross-check: −(world + opening) = −(−68031 − 145000) = 213031 ✓
- Net worth as of 2026-02-28 = 145000 ($1,450.00). March change = 68031 = income 90000 − net spending 21969 ✓

### D.3 Categories, 2026-03-01 to 2026-03-31

| Category | Calculation | Total |
|---|---|---|
| Food | 4250 + 600 + 4000 + 5820 + 2700 − 500 | **16870** ($168.70) |
| Transport | 3500 | **3500** ($35.00) |
| Subscriptions | 1599 | **1599** ($15.99) |
| Total expense | | **21969** ($219.69) |
| Salary (income) | | **90000** ($900.00) |

Card payments total 20000 (G-19 + G-22). They appear in **no** category. If the app ever reports total spending of 41969 (21969 + 20000), that is the double-count bug this design exists to prevent.

Also absent by construction: the openings, both lends, the borrow, all friend repayments, and the cash deposit.

Food only, 2026-03-01 to 2026-03-15: **8850**. All categories for that range: Food 8850, Transport 3500, Subscriptions 1599.

### D.4 Credit

| | Limit | Owed | Available | Utilization |
|---|---|---|---|---|
| Amex | 500000 | 11000 | 489000 ($4,890.00) | 220 bps (2.20%) |
| Visa | 200000 | 99 | 199901 ($1,999.01) | 5 bps (0.05%) — 4.95 rounded half up |
| Aggregate | 700000 | 11099 | 688901 ($6,889.01) | 159 bps (1.59%) — 158.56 rounded half up |

### D.5 Friend positions as of 2026-03-31

| Person | Calculation | Position |
|---|---|---|
| Raj | recv +2000 | **+2000** (owes you $20.00) |
| Mia | recv +2000 + payable −2000 | **0** (each account still shows $20.00; the position is what the UI headlines) |
| Tom | recv 0 | **0** |

### D.6 Checkpoint: as_of 2026-03-10

Proves `as_of` excludes later transactions.

| Item | Value |
|---|---|
| Chase | 148750 |
| Wallet | 6400 |
| recv:Tom / recv:Mia / recv:Raj | 0 / 2000 / 5000 |
| Amex owed / Visa owed | 26000 / 5099 |
| pay:Mia owed | 0 |
| **Net worth** | **131051** ($1,310.51) |

### D.7 Void check

Starting from the full month: voiding G-16 while G-17 is live is rejected (R-10). Void G-17, then G-16:

| Item | Value |
|---|---|
| Chase | 225750 |
| Net worth | 218351 |
| Food, March | 11550 (4250 + 600 + 4000 + 2700) |

---

## E. Property tests (Hypothesis)

Run on randomly generated sequences of valid template calls, across at least two users.

| ID | Property |
|---|---|
| P-1 | Every committed transaction has exactly 2 postings summing to zero |
| P-2 | For every account, the balance function equals an independent replay of its postings |
| P-3 | The category rule holds: `category_id` is set if and only if exactly one posting is on `world` |
| P-4 | Net worth (assets − owed) equals −(raw(world) + raw(opening)) at every `as_of` |
| P-5 | Appending any `transfer`, `card_payment`, `lend`, `friend_repay`, `borrow`, `repay_friend`, or `opening` never changes any category total |
| P-6 | Operations by user A never change any figure for user B |
| P-7 | Voiding a transaction gives the same figures as if it had never been entered |
| P-8 | Replaying any request with its `Idempotency-Key` leaves the database unchanged |
| P-9 | Category spend for a range equals the sum of its sub-ranges |
| P-10 | Utilization uses integer arithmetic only; the same inputs always give the same basis points |
