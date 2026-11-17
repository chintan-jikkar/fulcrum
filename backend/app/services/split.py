"""Splitting a bill between you and friends (D-078).

A bill of `total` cents has shared items, each split by units ("12 cases of water: 2 for Tara,
3 for Avi, the rest mine"). Everything not in a shared item is yours. Your share becomes a
`spend`; each friend's share becomes a `lend` on the same funding account (CLAUDE.md §4 notes:
that is how bill-splitting works), so only your share counts as spending.

Rounding: a friend's share of an item is rounded down to the cent, and the payer keeps the
leftover cents, so a friend is never charged a cent more than their units, and the shares
always add up to the bill exactly. All integer arithmetic (§6).
"""

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.models.ledger import PaymentMethod, Transaction
from app.services import ledger
from app.services.ledger import RuleViolation


@dataclass(frozen=True)
class Item:
    amount_minor: int
    my_units: int
    units: Mapping[Any, int]  # friend (a counterparty id; any key in tests) -> their units


def allocate(total: int, items: Sequence[Item]) -> tuple[int, dict[Any, int]]:
    """(my share, each friend's share) in cents, friends in first-seen order."""
    if type(total) is not int or total <= 0:
        raise RuleViolation("split", "the bill must be a positive amount")
    if not items:
        raise RuleViolation("split", "add at least one shared item")
    theirs: dict[Any, int] = {}
    for item in items:
        if type(item.amount_minor) is not int or item.amount_minor <= 0:
            raise RuleViolation("split", "each item needs a positive amount")
        if not item.units:
            raise RuleViolation("split", "each item needs at least one friend")
        counts = [item.my_units, *item.units.values()]
        if any(type(n) is not int or n < 0 for n in counts) or any(
            n <= 0 for n in item.units.values()
        ):
            raise RuleViolation("split", "units must be whole numbers, at least 1 for a friend")
        whole = sum(counts)
        for friend, n in item.units.items():
            theirs[friend] = theirs.get(friend, 0) + item.amount_minor * n // whole
    if sum(i.amount_minor for i in items) > total:
        raise RuleViolation("split", "the shared items cost more than the bill")
    return total - sum(theirs.values()), theirs


def split(
    session: Session,
    user_id: uuid.UUID,
    *,
    amount_minor: int,
    occurred_on: date,
    funding_id: uuid.UUID,
    category_id: uuid.UUID,
    items: Sequence[Item],
    memo: str = "",
    method: PaymentMethod | None = None,
) -> list[Transaction]:
    """Write the split in the caller's transaction: my spend (if I have a share), then a lend
    per friend. Any failure rolls the whole split back."""
    mine, theirs = allocate(amount_minor, items)
    written = []
    if mine > 0:
        written.append(
            ledger.spend(
                session,
                user_id,
                funding_id=funding_id,
                amount_minor=mine,
                category_id=category_id,
                occurred_on=occurred_on,
                memo=memo,
                method=method,
            )
        )
    for person, share in theirs.items():
        if share > 0:
            written.append(
                ledger.lend(
                    session,
                    user_id,
                    counterparty_id=person,
                    funding_id=funding_id,
                    amount_minor=share,
                    occurred_on=occurred_on,
                    memo=memo,
                    method=method,
                )
            )
    return written
