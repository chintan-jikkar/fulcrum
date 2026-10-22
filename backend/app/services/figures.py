"""The derived figures of CLAUDE.md §5: balances, net worth, credit, category totals, friends.

Read-only; the write path is ledger.py. Every figure replays postings of non-voided transactions
(§3.9) and caches nothing. Figures that take `as_of` default to today in the user's timezone
(D-013) and count transactions with occurred_on <= as_of. All arithmetic is on Python ints.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ledger import (
    Account,
    AccountKind,
    AccountSubtype,
    Category,
    CategoryKind,
    Counterparty,
    Posting,
    Transaction,
    User,
)
from app.services.ledger import RuleViolation

Sub = AccountSubtype


@dataclass(frozen=True)
class Credit:
    """One card, or the aggregate over cards with a limit. Without a limit, available and
    utilization are None."""

    limit_minor: int | None
    owed: int
    available: int | None
    utilization_bps: int | None


@dataclass(frozen=True)
class PeriodTotals:
    """by_category holds every category with a transaction in the period, plus its parent,
    whose total includes its children. Income categories are positive. expense and income
    count each transaction once."""

    by_category: dict[uuid.UUID, int]
    expense: int
    income: int


def today(session: Session, user_id: uuid.UUID) -> date:
    tz = session.scalars(select(User.timezone).where(User.id == user_id)).one()
    return datetime.now(ZoneInfo(tz)).date()


def _as_of(session: Session, user_id: uuid.UUID, as_of: date | None) -> date:
    if as_of is None:
        return today(session, user_id)
    if type(as_of) is not date:  # a datetime is a date subclass, and is not a valid as_of
        raise RuleViolation("as_of", f"must be a bare date, got {as_of!r}")
    return as_of


def _balances(
    session: Session, user_id: uuid.UUID, as_of: date | None
) -> list[tuple[Account, int]]:
    """Every account of the user with its raw balance at as_of, zero if it has no postings."""
    as_of = _as_of(session, user_id, as_of)
    sums = (
        select(Posting.account_id, func.sum(Posting.amount_minor).label("raw"))
        .join(Transaction, Transaction.id == Posting.transaction_id)
        .where(
            Posting.user_id == user_id,
            Transaction.voided_at.is_(None),
            Transaction.occurred_on <= as_of,
        )
        .group_by(Posting.account_id)
        .subquery()
    )
    q = (
        select(Account, func.coalesce(sums.c.raw, 0))
        .outerjoin(sums, sums.c.account_id == Account.id)
        .where(Account.user_id == user_id)
    )
    # Postgres returns SUM(bigint) as numeric; int() of that Decimal is exact.
    return [(acct, int(raw)) for acct, raw in session.execute(q)]


def balances(
    session: Session, user_id: uuid.UUID, as_of: date | None = None
) -> dict[uuid.UUID, int]:
    """Raw balance of every account (§3.9). Display: asset as is, liability owed is minus this."""
    return {acct.id: raw for acct, raw in _balances(session, user_id, as_of)}


def net_worth(session: Session, user_id: uuid.UUID, as_of: date | None = None) -> int:
    """Assets minus owed. Owed is minus the raw balance, so this is the sum of raw balances."""
    return sum(
        raw
        for acct, raw in _balances(session, user_id, as_of)
        if acct.kind is not AccountKind.EXTERNAL
    )


def net_worth_outside(session: Session, user_id: uuid.UUID, as_of: date | None = None) -> int:
    """The equivalent form, -(raw(world) + raw(opening)). P-4 checks the two always agree."""
    return -sum(
        raw for acct, raw in _balances(session, user_id, as_of) if acct.kind is AccountKind.EXTERNAL
    )


def utilization_bps(owed: int, limit_minor: int | None) -> int | None:
    """max(owed, 0) * 10000 / limit in basis points, rounded half up, in integers (D-014)."""
    if limit_minor is None:
        return None
    return (max(owed, 0) * 20000 + limit_minor) // (2 * limit_minor)


def credit(
    session: Session, user_id: uuid.UUID, as_of: date | None = None
) -> tuple[dict[uuid.UUID, Credit], Credit]:
    """Per active card, and the aggregate over active cards that have a limit. In the aggregate
    a card's credit balance lowers owed and raises available, but never offsets another card's
    utilization: utilization counts only what each card owes (D-052)."""
    cards: dict[uuid.UUID, Credit] = {}
    limit_sum = owed_sum = owed_positive = 0
    for acct, raw in _balances(session, user_id, as_of):
        if acct.subtype is not Sub.credit_card or not acct.is_active:
            continue
        owed, limit = -raw, acct.meta.get("limit_minor")
        cards[acct.id] = Credit(
            limit_minor=limit,
            owed=owed,
            available=None if limit is None else limit - owed,
            utilization_bps=utilization_bps(owed, limit),
        )
        if limit is not None:
            limit_sum += limit
            owed_sum += owed
            owed_positive += max(owed, 0)
    if not limit_sum:
        return cards, Credit(limit_minor=None, owed=0, available=None, utilization_bps=None)
    total = Credit(
        limit_minor=limit_sum,
        owed=owed_sum,
        available=limit_sum - owed_sum,
        utilization_bps=utilization_bps(owed_positive, limit_sum),
    )
    return cards, total


def category_totals(
    session: Session, user_id: uuid.UUID, *, start: date, end: date
) -> PeriodTotals:
    """Spend and income per category over [start, end], inclusive (§5): the world leg of each
    non-voided categorised transaction. Refunds carry a negative world leg, so they reduce
    spend. Transfers, payments, loans and openings have no category and cannot appear."""
    for name, value in (("start", start), ("end", end)):
        if type(value) is not date:
            raise RuleViolation("period", f"{name} must be a bare date, got {value!r}")
    if start > end:
        raise RuleViolation("period", f"start {start} is after end {end}")

    q = (
        select(Category, func.sum(Posting.amount_minor))
        .join(Transaction, Transaction.category_id == Category.id)
        .join(Posting, Posting.transaction_id == Transaction.id)
        .join(Account, Account.id == Posting.account_id)
        .where(
            Transaction.user_id == user_id,
            Transaction.voided_at.is_(None),
            Transaction.occurred_on.between(start, end),
            Account.subtype == Sub.world,
        )
        .group_by(Category.id)
    )
    totals = {CategoryKind.expense: 0, CategoryKind.income: 0}
    by_category: dict[uuid.UUID, int] = {}
    for cat, world in session.execute(q):
        n = int(world) if cat.kind is CategoryKind.expense else -int(world)
        totals[cat.kind] += n
        by_category[cat.id] = by_category.get(cat.id, 0) + n
        if cat.parent_id is not None:  # one level of nesting at most (§3.4)
            by_category[cat.parent_id] = by_category.get(cat.parent_id, 0) + n
    return PeriodTotals(
        by_category=by_category,
        expense=totals[CategoryKind.expense],
        income=totals[CategoryKind.income],
    )


def friend_positions(
    session: Session, user_id: uuid.UUID, as_of: date | None = None
) -> dict[uuid.UUID, int]:
    """raw(receivable) + raw(payable) per counterparty (§5). Positive: they owe you."""
    q = select(Counterparty.id).where(Counterparty.user_id == user_id)
    positions = dict.fromkeys(session.scalars(q), 0)
    for acct, raw in _balances(session, user_id, as_of):
        if acct.counterparty_id is not None:
            positions[acct.counterparty_id] += raw
    return positions
