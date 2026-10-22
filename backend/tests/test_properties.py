"""Property tests P-1 to P-7, P-9 and P-10 (SCENARIOS.md §E). P-8 needs the HTTP layer.

Hypothesis generates sequences of template calls, voids and recategorisations spread over two
users. Each call is replayed into a plain-Python model that writes its own postings straight from
the §4 table, without the service code, and every figure is compared with the model. Calls the
rules would reject (a second opening, a refund over the cap, voiding a spend with live refunds)
are skipped before they are made, so any exception from the service is a failure. Every call is
committed, so the deferred database checks (I1, I2, I5) run on everything written.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from fractions import Fraction
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models.ledger import Account, AccountSubtype, Category, CategoryKind, Posting, Transaction
from app.services import figures, ledger
from app.services.users import provision_user

Sub = AccountSubtype

CASH_BANK = ("chase", "wallet")
FUNDING = ("chase", "wallet", "amex", "visa", "store")  # store is a card with no limit
CARDS = ("amex", "visa", "store")
OPENABLE = FUNDING + ("recv:Ann", "pay:Ann", "recv:Ben", "pay:Ben")
PEOPLE = ("Ann", "Ben")
EXPENSE = ("Food", "Transport", "Groceries")  # Groceries is a child of Food
INCOME = ("Salary", "Other income")
NO_CATEGORY = {
    "transfer",
    "card_payment",
    "lend",
    "friend_repay",
    "borrow",
    "repay_friend",
    "opening",
}
VERBS = sorted(NO_CATEGORY | {"spend", "income", "refund", "void", "recategorise"})

START, END = date(2026, 2, 1), date(2026, 4, 30)


@dataclass
class MTxn:
    """The model's copy of one transaction."""

    uid: uuid.UUID
    id: uuid.UUID
    template: str
    on: date
    legs: list[tuple[uuid.UUID, int]]
    category: uuid.UUID | None = None
    refund_of: "MTxn | None" = None
    voided: bool = False

    @property
    def amount(self) -> int:
        return max(n for _, n in self.legs)


@dataclass
class User:
    uid: uuid.UUID
    acct: dict[str, uuid.UUID] = field(default_factory=dict)
    person: dict[str, uuid.UUID] = field(default_factory=dict)
    cat: dict[str, uuid.UUID] = field(default_factory=dict)
    parent: dict[uuid.UUID, uuid.UUID | None] = field(default_factory=dict)
    kind: dict[uuid.UUID, CategoryKind] = field(default_factory=dict)


def make_user(s: Session) -> User:
    u = User(provision_user(s, f"prop|{uuid.uuid4()}", "Prop", "America/New_York").id)
    for name, sub, meta in [
        ("chase", Sub.bank, {}),
        ("wallet", Sub.cash, {}),
        ("amex", Sub.credit_card, {"limit_minor": 300000}),
        ("visa", Sub.credit_card, {"limit_minor": 100000}),
        ("store", Sub.credit_card, {}),
    ]:
        u.acct[name] = ledger.create_account(s, u.uid, name=name, subtype=sub, meta=meta).id
    for sub in (Sub.world, Sub.opening):
        q = select(Account.id).where(Account.user_id == u.uid, Account.subtype == sub)
        u.acct[sub] = s.scalars(q).one()
    for name in PEOPLE:
        u.person[name] = ledger.create_counterparty(s, u.uid, name=name).id
        for sub, prefix in ((Sub.receivable, "recv"), (Sub.payable, "pay")):
            u.acct[f"{prefix}:{name}"] = ledger.person_account(s, u.uid, u.person[name], sub).id
    q2 = select(Category).where(Category.user_id == u.uid)
    food = next(c for c in s.scalars(q2) if c.name == "Food")
    s.add(Category(user_id=u.uid, name="Groceries", kind=CategoryKind.expense, parent_id=food.id))
    s.flush()
    for c in s.scalars(q2):
        u.cat[c.name], u.parent[c.id], u.kind[c.id] = c.id, c.parent_id, c.kind
    s.commit()
    return u


Op = tuple[int, str, int, int, int, int, int]  # user, verb, day, amount, a, b, pick


def apply(s: Session, u: User, txns: list[MTxn], op: Op) -> str | None:
    """Make one call and mirror it in the model. Returns the verb, or None if it was skipped."""
    _, verb, day, x, a, b, pick = op
    on = date(2026, 3, day)
    A = u.acct
    w, o = A[Sub.world], A[Sub.opening]
    mine = [t for t in txns if t.uid == u.uid]
    live = [t for t in mine if not t.voided]
    kw: dict[str, Any] = {"amount_minor": x, "occurred_on": on}

    def add(t: Transaction, legs: list[tuple[uuid.UUID, int]], **extra: Any) -> None:
        txns.append(MTxn(u.uid, t.id, verb, on, legs, **extra))

    if verb == "spend":
        f, c = A[FUNDING[a % 5]], u.cat[EXPENSE[b % 3]]
        t = ledger.spend(s, u.uid, funding_id=f, category_id=c, **kw)
        add(t, [(w, x), (f, -x)], category=c)
    elif verb == "income":
        dest, c = A[CASH_BANK[a % 2]], u.cat[INCOME[b % 2]]
        t = ledger.income(s, u.uid, dest_id=dest, category_id=c, **kw)
        add(t, [(dest, x), (w, -x)], category=c)
    elif verb == "refund":
        f = A[FUNDING[a % 5]]
        spends = [t for t in live if t.template == "spend"]
        if b % 2 == 0 and spends:
            orig = spends[pick % len(spends)]
            left = orig.amount - sum(r.amount for r in live if r.refund_of is orig)
            if left == 0:
                return None
            x = kw["amount_minor"] = min(x, left)
            t = ledger.refund(s, u.uid, funding_id=f, refund_of_id=orig.id, **kw)
            add(t, [(f, x), (w, -x)], category=orig.category, refund_of=orig)
        else:
            c = u.cat[EXPENSE[b % 3]]
            t = ledger.refund(s, u.uid, funding_id=f, category_id=c, **kw)
            add(t, [(f, x), (w, -x)], category=c)
    elif verb == "transfer":
        frm, to = A[CASH_BANK[a % 2]], A[CASH_BANK[1 - a % 2]]
        t = ledger.transfer(s, u.uid, from_id=frm, to_id=to, **kw)
        add(t, [(to, x), (frm, -x)])
    elif verb == "card_payment":
        card, f = A[CARDS[a % 3]], A[CASH_BANK[b % 2]]
        t = ledger.card_payment(s, u.uid, card_id=card, funding_id=f, **kw)
        add(t, [(card, x), (f, -x)])
    elif verb in ("lend", "friend_repay", "borrow", "repay_friend"):
        name = PEOPLE[b % 2]
        p, recv, pay = u.person[name], A[f"recv:{name}"], A[f"pay:{name}"]
        if verb == "lend":
            f = A[FUNDING[a % 5]]
            t = ledger.lend(s, u.uid, counterparty_id=p, funding_id=f, **kw)
            add(t, [(recv, x), (f, -x)])
        elif verb == "friend_repay":
            f = A[CASH_BANK[a % 2]]
            t = ledger.friend_repay(s, u.uid, counterparty_id=p, funding_id=f, **kw)
            add(t, [(f, x), (recv, -x)])
        elif verb == "borrow":
            dest = A[CASH_BANK[a % 2]]
            t = ledger.borrow(s, u.uid, counterparty_id=p, dest_id=dest, **kw)
            add(t, [(dest, x), (pay, -x)])
        else:
            f = A[CASH_BANK[a % 2]]
            t = ledger.repay_friend(s, u.uid, counterparty_id=p, funding_id=f, **kw)
            add(t, [(pay, x), (f, -x)])
    elif verb == "opening":
        name = OPENABLE[a % len(OPENABLE)]
        acct = A[name]
        if any(t.template == "opening" and acct in dict(t.legs) for t in live):
            return None  # I10
        t = ledger.opening(s, u.uid, account_id=acct, **kw)
        asset = name in CASH_BANK or name.startswith("recv:")
        add(t, [(acct, x), (o, -x)] if asset else [(o, x), (acct, -x)])
    elif verb == "void":
        if not live:
            return None
        target = live[pick % len(live)]
        if any(r.refund_of is target for r in live):
            return None  # R-10
        ledger.void(s, u.uid, target.id)
        target.voided = True
    elif verb == "recategorise":
        spends = [t for t in mine if t.template == "spend"]
        if not spends:
            return None
        target, c = spends[pick % len(spends)], u.cat[EXPENSE[b % 3]]
        ledger.set_category(s, u.uid, target.id, c)
        for m in [target, *(r for r in mine if r.refund_of is target)]:
            m.category = c
    else:
        raise AssertionError(verb)
    s.commit()
    return verb


# --- The model's figures, written from §3.9 and §5 alone -------------------------------------


def m_balances(u: User, txns: list[MTxn], as_of: date) -> dict[uuid.UUID, int]:
    out = dict.fromkeys(u.acct.values(), 0)
    for t in txns:
        if t.uid == u.uid and not t.voided and t.on <= as_of:
            for acct, n in t.legs:
                out[acct] += n
    return out


def m_net_worth(u: User, txns: list[MTxn], as_of: date) -> int:
    bal = m_balances(u, txns, as_of)
    outside = {u.acct[Sub.world], u.acct[Sub.opening]}
    return sum(n for acct, n in bal.items() if acct not in outside)


def m_totals(u: User, txns: list[MTxn], start: date, end: date) -> figures.PeriodTotals:
    own: dict[uuid.UUID, int] = defaultdict(int)
    for t in txns:
        if t.uid == u.uid and not t.voided and start <= t.on <= end and t.category:
            world_leg = sum(n for acct, n in t.legs if acct == u.acct[Sub.world])
            sign = 1 if u.kind[t.category] is CategoryKind.expense else -1
            own[t.category] += sign * world_leg
    by_category = dict(own)
    for c, n in own.items():
        parent = u.parent[c]
        if parent is not None:
            by_category[parent] = by_category.get(parent, 0) + n
    expense = sum(n for c, n in own.items() if u.kind[c] is CategoryKind.expense)
    income = sum(n for c, n in own.items() if u.kind[c] is CategoryKind.income)
    return figures.PeriodTotals(by_category=by_category, expense=expense, income=income)


def m_positions(u: User, txns: list[MTxn], as_of: date) -> dict[uuid.UUID, int]:
    bal = m_balances(u, txns, as_of)
    return {p: bal[u.acct[f"recv:{n}"]] + bal[u.acct[f"pay:{n}"]] for n, p in u.person.items()}


def snapshot(s: Session, u: User) -> tuple[Any, ...]:
    """Every figure for one user, for the P-5 and P-6 before/after comparisons."""
    as_of = date(2026, 3, 31)
    return (
        figures.balances(s, u.uid, as_of),
        figures.net_worth(s, u.uid, as_of),
        figures.net_worth_outside(s, u.uid, as_of),
        figures.category_totals(s, u.uid, start=START, end=END),
        figures.friend_positions(s, u.uid, as_of),
        figures.credit(s, u.uid, as_of),
    )


ops = st.lists(
    st.tuples(
        st.integers(0, 1),
        st.sampled_from(VERBS),
        st.integers(1, 31),
        st.integers(1, 100000),
        st.integers(0, 8),
        st.integers(0, 5),
        st.integers(0, 10**6),
    ),
    max_size=20,
)


@settings(max_examples=30, deadline=None)
@given(ops=ops, split=st.integers(1, 30))
def test_ledger_properties(engine: Engine, ops: list[Op], split: int) -> None:
    with Session(engine) as s:
        users = [make_user(s), make_user(s)]
        txns: list[MTxn] = []

        for op in ops:
            me, them = users[op[0]], users[1 - op[0]]
            before_mine = figures.category_totals(s, me.uid, start=START, end=END)
            before_theirs = snapshot(s, them)
            verb = apply(s, me, txns, op)
            if verb in NO_CATEGORY:  # P-5
                assert figures.category_totals(s, me.uid, start=START, end=END) == before_mine
            assert snapshot(s, them) == before_theirs  # P-6

        uids = [u.uid for u in users]
        world = select(Account.id).where(Account.subtype == Sub.world)
        rows = s.execute(
            select(
                Transaction.category_id,
                func.count(Posting.id),
                func.sum(Posting.amount_minor),
                func.count(Posting.id).filter(Posting.account_id.in_(world)),
            )
            .join(Posting, Posting.transaction_id == Transaction.id)
            .where(Transaction.user_id.in_(uids))
            .group_by(Transaction.id)
        ).all()
        assert len(rows) == len(txns)  # nothing written beyond what the model knows of
        for category_id, legs, total, world_legs in rows:
            assert (legs, total) == (2, 0)  # P-1
            assert (category_id is not None) == (world_legs == 1)  # P-3

        dates = sorted({t.on for t in txns} | {date(2026, 2, 27), date(2026, 3, 31)})
        for u in users:
            for as_of in dates:
                expected = m_balances(u, txns, as_of)  # live transactions only: P-7
                assert figures.balances(s, u.uid, as_of) == expected  # P-2
                for acct, n in expected.items():
                    assert ledger.balance_raw(s, u.uid, acct, as_of) == n  # P-2
                nw = m_net_worth(u, txns, as_of)
                assert figures.net_worth(s, u.uid, as_of) == nw  # P-4
                assert figures.net_worth_outside(s, u.uid, as_of) == nw  # P-4
                assert figures.friend_positions(s, u.uid, as_of) == m_positions(u, txns, as_of)

            whole = figures.category_totals(s, u.uid, start=START, end=END)
            assert whole == m_totals(u, txns, START, END)  # P-7 for category totals

            # P-9: a range equals the sum of its two halves.
            mid = date(2026, 3, split)
            first = figures.category_totals(s, u.uid, start=START, end=mid)
            second = figures.category_totals(s, u.uid, start=mid + timedelta(days=1), end=END)
            joined = defaultdict(int, first.by_category)
            for c, n in second.by_category.items():
                joined[c] += n
            assert dict(joined) == whole.by_category
            assert first.expense + second.expense == whole.expense
            assert first.income + second.income == whole.income
        s.rollback()


# --- P-10 ------------------------------------------------------------------------------------


@given(owed=st.integers(-(2**62), 2**62), limit=st.integers(1, 2**62))
def test_utilization_is_exact_integer_half_up(owed: int, limit: int) -> None:
    bps = figures.utilization_bps(owed, limit)
    assert type(bps) is int
    exact = Fraction(max(owed, 0) * 10000, limit)
    assert bps == int(exact + Fraction(1, 2))  # floor(x + 1/2): half up for x >= 0
    assert figures.utilization_bps(owed, limit) == bps
