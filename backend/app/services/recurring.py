"""Subscriptions and other recurring charges (CLAUDE.md §12, D-079).

Propose, do not autopost: a rule only reminds. Confirming writes one ordinary `spend` through
the ledger (so every ledger rule applies to it) and moves the rule to its next date. Skipping
moves it without a transaction; cancelling stops the reminders and resuming starts them again.
"""

import calendar
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.ledger import RecurringCadence, RecurringRule, TransactionTemplate
from app.services import ledger
from app.services.figures import today
from app.services.ledger import CASH_BANK_CARD, MAX_MINOR, NotFound, RuleViolation

Cadence = RecurringCadence


def _on_day(year: int, month: int, day: int) -> date:
    """`day` of that month, or the month's last day if it is shorter."""
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_after(due: date, cadence: Cadence | str, anchor_day: int) -> date:
    """The date after `due`. Monthly and yearly keep to anchor_day where the month allows."""
    match Cadence(cadence):
        case Cadence.weekly:
            return due + timedelta(days=7)
        case Cadence.monthly:
            return _on_day(due.year + due.month // 12, due.month % 12 + 1, anchor_day)
        case Cadence.yearly:
            return _on_day(due.year + 1, due.month, anchor_day)


def _check(
    session: Session,
    user_id: uuid.UUID,
    *,
    name: str,
    amount_minor: int,
    funding_id: uuid.UUID,
    category_id: uuid.UUID,
    remind_days: int,
) -> None:
    """The rule must be a spend the ledger would accept today (§4), so confirming cannot fail
    for a reason the user could have been told about up front."""
    if not name.strip():
        raise RuleViolation("recurring", "give it a name, like Netflix")
    if type(amount_minor) is not int or not 0 < amount_minor <= MAX_MINOR:
        raise RuleViolation("recurring", f"amount must be positive cents, got {amount_minor!r}")
    if type(remind_days) is not int or not 0 <= remind_days <= 14:
        raise RuleViolation("recurring", "remind 0 to 14 days before")
    ledger._account(
        session, user_id, funding_id, CASH_BANK_CARD, TransactionTemplate.spend, "funding"
    )
    ledger._category(session, user_id, category_id, TransactionTemplate.spend)


def create(
    session: Session,
    user_id: uuid.UUID,
    *,
    name: str,
    amount_minor: int,
    funding_id: uuid.UUID,
    category_id: uuid.UUID,
    cadence: Cadence,
    next_due_on: date,
    remind_days: int = 2,
) -> RecurringRule:
    _check(
        session,
        user_id,
        name=name,
        amount_minor=amount_minor,
        funding_id=funding_id,
        category_id=category_id,
        remind_days=remind_days,
    )
    rule = RecurringRule(
        user_id=user_id,
        name=name.strip(),
        amount_minor=amount_minor,
        funding_id=funding_id,
        category_id=category_id,
        cadence=Cadence(cadence),
        anchor_day=next_due_on.day,
        next_due_on=next_due_on,
        remind_days=remind_days,
    )
    session.add(rule)
    session.flush()
    return rule


def get(session: Session, user_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringRule:
    """The user's rule, locked for the change. Another user's is NotFound (§7)."""
    rule = session.scalars(
        select(RecurringRule)
        .where(RecurringRule.id == rule_id, RecurringRule.user_id == user_id)
        .with_for_update()
    ).one_or_none()
    if rule is None:
        raise NotFound(f"recurring rule {rule_id}")
    return rule


def edit(
    session: Session,
    user_id: uuid.UUID,
    rule_id: uuid.UUID,
    *,
    name: str | None = None,
    amount_minor: int | None = None,
    funding_id: uuid.UUID | None = None,
    category_id: uuid.UUID | None = None,
    cadence: Cadence | None = None,
    next_due_on: date | None = None,
    remind_days: int | None = None,
) -> RecurringRule:
    """Change any part of the rule. A new date also becomes its day of the month."""
    rule = get(session, user_id, rule_id)
    _check(
        session,
        user_id,
        name=rule.name if name is None else name,
        amount_minor=rule.amount_minor if amount_minor is None else amount_minor,
        funding_id=funding_id or rule.funding_id,
        category_id=category_id or rule.category_id,
        remind_days=rule.remind_days if remind_days is None else remind_days,
    )
    if name is not None:
        rule.name = name.strip()
    if amount_minor is not None:
        rule.amount_minor = amount_minor
    if funding_id is not None:
        rule.funding_id = funding_id
    if category_id is not None:
        rule.category_id = category_id
    if cadence is not None:
        rule.cadence = Cadence(cadence)
    if next_due_on is not None:
        rule.next_due_on, rule.anchor_day = next_due_on, next_due_on.day
    if remind_days is not None:
        rule.remind_days = remind_days
    session.flush()
    return rule


def _active(session: Session, user_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringRule:
    rule = get(session, user_id, rule_id)
    if not rule.is_active:
        raise RuleViolation("recurring", f"{rule.name} is cancelled; resume it first")
    return rule


def confirm(
    session: Session,
    user_id: uuid.UUID,
    rule_id: uuid.UUID,
    *,
    amount_minor: int | None = None,
    occurred_on: date | None = None,
) -> RecurringRule:
    """The charge happened: write the spend (on its due date, or today if confirmed early,
    unless told otherwise; at the rule's amount unless the bill differed) and move on."""
    rule = _active(session, user_id, rule_id)
    when = occurred_on or min(rule.next_due_on, today(session, user_id))
    ledger.spend(
        session,
        user_id,
        funding_id=rule.funding_id,
        amount_minor=rule.amount_minor if amount_minor is None else amount_minor,
        category_id=rule.category_id,
        occurred_on=when,
        memo=rule.name,
    )
    rule.next_due_on = next_after(rule.next_due_on, rule.cadence, rule.anchor_day)
    session.flush()
    return rule


def skip(session: Session, user_id: uuid.UUID, rule_id: uuid.UUID) -> RecurringRule:
    """Not charged this time (a free month, a paused plan): move on without a transaction."""
    rule = _active(session, user_id, rule_id)
    rule.next_due_on = next_after(rule.next_due_on, rule.cadence, rule.anchor_day)
    session.flush()
    return rule


def set_active(
    session: Session, user_id: uuid.UUID, rule_id: uuid.UUID, active: bool
) -> RecurringRule:
    """Cancel (no more reminders) or resume. History stays either way."""
    rule = get(session, user_id, rule_id)
    rule.is_active = active
    session.flush()
    return rule
