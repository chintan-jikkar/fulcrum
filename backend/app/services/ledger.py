"""The ledger write path: the ten templates of CLAUDE.md §4, void, the allowed edits, and archiving.

Nothing else writes postings. Every function takes the session, then the user id, and only ever
reads or writes that user's rows; another user's id raises NotFound, exactly as a missing id does
(§7). The caller commits. The database re-checks I1, I2, I3, I5, I6 and I7 at commit, and the
service checks them first so a mistake gets a clear error instead of a trigger message.

Locking, so concurrent requests cannot break a rule between check and write:
- Every account a template posts to is read FOR SHARE, and archiving takes FOR UPDATE, so an
  account cannot be archived (I9) while a posting to it is in flight (I4).
- `opening` takes FOR UPDATE on its account, so two openings cannot both pass I10.
- `refund`, `void` and `set_category` take FOR UPDATE on the spend involved, so refund totals,
  live-refund checks and category changes are serialised.
"""

import uuid
from collections.abc import Collection
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.ledger import (
    Account,
    AccountKind,
    AccountSubtype,
    Category,
    CategoryKind,
    Counterparty,
    PaymentMethod,
    Posting,
    Transaction,
    TransactionTemplate,
)

T = TransactionTemplate
Sub = AccountSubtype

MAX_MINOR = 2**63 - 1  # bigint

KIND_OF = {
    Sub.cash: AccountKind.ASSET,
    Sub.bank: AccountKind.ASSET,
    Sub.receivable: AccountKind.ASSET,
    Sub.credit_card: AccountKind.LIABILITY,
    Sub.payable: AccountKind.LIABILITY,
    Sub.world: AccountKind.EXTERNAL,
    Sub.opening: AccountKind.EXTERNAL,
}
CASH_BANK = frozenset({Sub.cash, Sub.bank})
CASH_BANK_CARD = CASH_BANK | {Sub.credit_card}
CARD = frozenset({Sub.credit_card})
NOT_EXTERNAL = frozenset(s for s, k in KIND_OF.items() if k is not AccountKind.EXTERNAL)


class LedgerError(Exception):
    pass


class NotFound(LedgerError):
    """404. Also raised for another user's id, which must look exactly like a missing one."""


class Conflict(LedgerError):
    """409: already voided, or a duplicate name."""


class RuleViolation(LedgerError):
    """422. `rule` names what was broken: an invariant ("I4", "I8", ...) or "template",
    "refund", "archive", "account", "counterparty", "occurred_on"."""

    def __init__(self, rule: str, message: str) -> None:
        super().__init__(f"{rule}: {message}")
        self.rule = rule


# --- Reads used by the rules ----------------------------------------------------------------


def balance_raw(
    session: Session, user_id: uuid.UUID, account_id: uuid.UUID, as_of: date | None = None
) -> int:
    """SUM(amount_minor) over the account's postings on non-voided transactions (§3.9).
    With no as_of, every posting counts, future-dated ones included."""
    q = (
        select(func.coalesce(func.sum(Posting.amount_minor), 0))
        .join(Transaction, Transaction.id == Posting.transaction_id)
        .where(
            Posting.user_id == user_id,
            Posting.account_id == account_id,
            Transaction.voided_at.is_(None),
        )
    )
    if as_of is not None:
        q = q.where(Transaction.occurred_on <= as_of)
    # Postgres returns SUM(bigint) as numeric; int() of that Decimal is exact.
    return int(session.scalar(q) or 0)


def _amount(session: Session, txn_id: uuid.UUID) -> int:
    """X for a two-leg transaction: its positive leg."""
    return int(
        session.scalar(
            select(func.max(Posting.amount_minor)).where(Posting.transaction_id == txn_id)
        )
        or 0
    )


def _refunded(session: Session, user_id: uuid.UUID, spend_id: uuid.UUID) -> int:
    q = (
        select(func.coalesce(func.sum(Posting.amount_minor), 0))
        .join(Transaction, Transaction.id == Posting.transaction_id)
        .where(
            Transaction.user_id == user_id,
            Transaction.refund_of_id == spend_id,
            Transaction.voided_at.is_(None),
            Posting.amount_minor > 0,
        )
    )
    return int(session.scalar(q) or 0)


def _transaction(session: Session, user_id: uuid.UUID, txn_id: uuid.UUID) -> Transaction:
    q = (
        select(Transaction)
        .where(Transaction.id == txn_id, Transaction.user_id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    txn = session.scalars(q).one_or_none()
    if txn is None:
        raise NotFound(f"transaction {txn_id}")
    return txn


def _lock_account(
    session: Session, user_id: uuid.UUID, account_id: uuid.UUID, *, exclusive: bool = False
) -> Account:
    q = (
        select(Account)
        .where(Account.id == account_id, Account.user_id == user_id)
        .with_for_update(read=not exclusive)
        .execution_options(populate_existing=True)
    )
    acct = session.scalars(q).one_or_none()
    if acct is None:
        raise NotFound(f"account {account_id}")
    return acct


def _account(
    session: Session,
    user_id: uuid.UUID,
    account_id: uuid.UUID,
    allowed: Collection[AccountSubtype],
    template: TransactionTemplate,
    role: str,
    *,
    exclusive: bool = False,
) -> Account:
    """An account the template may post to: the user's own (I6), of an allowed subtype (§4),
    and active (I4)."""
    acct = _lock_account(session, user_id, account_id, exclusive=exclusive)
    if acct.subtype not in allowed:
        hint = (
            "; use card_payment"
            if template is T.transfer and acct.subtype is Sub.credit_card
            else ""
        )
        names = "/".join(sorted(allowed))
        raise RuleViolation(
            "template", f"{template} {role} must be {names}, not {acct.subtype}{hint}"
        )
    if not acct.is_active:
        raise RuleViolation("I4", f"account {acct.name!r} is archived")
    return acct


def _outside(session: Session, user_id: uuid.UUID, subtype: AccountSubtype) -> Account:
    q = select(Account).where(Account.user_id == user_id, Account.subtype == subtype)
    return session.scalars(q).one()


def _category(
    session: Session,
    user_id: uuid.UUID,
    category_id: uuid.UUID | None,
    template: TransactionTemplate,
) -> Category:
    """A category the template may carry: present (I5), the user's own, the template's kind and
    not archived (I8)."""
    if category_id is None:
        raise RuleViolation("I5", f"{template} needs a category")
    q = select(Category).where(Category.id == category_id, Category.user_id == user_id)
    cat = session.scalars(q).one_or_none()
    if cat is None:
        raise NotFound(f"category {category_id}")
    kind = CategoryKind.income if template is T.income else CategoryKind.expense
    if cat.kind is not kind:
        raise RuleViolation(
            "I8", f"{template} needs an {kind} category; {cat.name!r} is {cat.kind}"
        )
    if cat.is_archived:
        raise RuleViolation("I8", f"category {cat.name!r} is archived")
    return cat


def _check_inputs(amount_minor: int, occurred_on: date) -> None:
    # type() rather than isinstance: bool is an int and datetime is a date, and neither is valid.
    if type(amount_minor) is not int or not 0 < amount_minor <= MAX_MINOR:
        raise RuleViolation(
            "I3", f"amount must be a positive whole number of cents, got {amount_minor!r}"
        )
    if type(occurred_on) is not date:
        raise RuleViolation("occurred_on", f"must be a bare date, got {occurred_on!r}")


def _write(
    session: Session,
    user_id: uuid.UUID,
    template: TransactionTemplate,
    occurred_on: date,
    legs: list[tuple[Account, int]],
    *,
    category_id: uuid.UUID | None = None,
    memo: str = "",
    method: PaymentMethod | None = None,
    refund_of_id: uuid.UUID | None = None,
) -> Transaction:
    """Insert the transaction and its two postings, after the service-side I1, I2, I3, I5."""
    if len(legs) != 2 or sum(n for _, n in legs) != 0 or any(n == 0 for _, n in legs):
        raise AssertionError(f"template {template} built bad legs: {legs}")  # a bug here, not input
    if legs[0][0].id == legs[1][0].id:
        raise RuleViolation("I3", "both sides are the same account")
    world_legs = sum(1 for a, _ in legs if a.subtype is Sub.world)
    if (category_id is not None) != (world_legs == 1):
        raise AssertionError(f"template {template} broke I5")  # templates fix the category rule

    txn = Transaction(
        user_id=user_id,
        template=template,
        occurred_on=occurred_on,
        memo=memo,
        category_id=category_id,
        method=method,
        refund_of_id=refund_of_id,
    )
    session.add(txn)
    session.flush()
    session.add_all(
        Posting(user_id=user_id, transaction_id=txn.id, account_id=a.id, amount_minor=n)
        for a, n in legs
    )
    session.flush()
    return txn


# --- Accounts and counterparties ------------------------------------------------------------


def create_account(
    session: Session,
    user_id: uuid.UUID,
    *,
    name: str,
    subtype: AccountSubtype,
    meta: dict[str, Any] | None = None,
) -> Account:
    """A cash, bank or credit card account. Person accounts are made on first use by
    person_account; world and opening exist from provisioning.

    Only the meta fields the ledger reads are checked here: a card's limit_minor (utilization)
    and linked_bank_id (§3.3). The API schema validates the rest (P3)."""
    if subtype not in CASH_BANK_CARD:
        raise RuleViolation("account", f"{subtype} accounts are not created directly")
    meta = dict(meta or {})
    if subtype is Sub.credit_card:
        limit = meta.get("limit_minor")
        if limit is not None and (type(limit) is not int or not 0 < limit <= MAX_MINOR):
            raise RuleViolation("account", f"limit_minor must be positive cents, got {limit!r}")
        bank_id = meta.get("linked_bank_id")
        if bank_id is not None:
            try:
                bank_uuid = uuid.UUID(str(bank_id))
            except ValueError:
                raise RuleViolation(
                    "account", f"linked_bank_id is not an id: {bank_id!r}"
                ) from None
            if _lock_account(session, user_id, bank_uuid).subtype is not Sub.bank:
                raise RuleViolation("account", "linked_bank_id must be a bank account")

    acct = Account(user_id=user_id, name=name, kind=KIND_OF[subtype], subtype=subtype, meta=meta)
    session.add(acct)
    session.flush()
    return acct


def create_counterparty(
    session: Session, user_id: uuid.UUID, *, name: str, contact: str | None = None
) -> Counterparty:
    name = name.strip()
    if not name:
        raise RuleViolation("counterparty", "name is empty")
    new_id = session.scalar(
        insert(Counterparty)
        .values(user_id=user_id, name=name, contact=contact)
        .on_conflict_do_nothing()  # the unique index on (user_id, lower(name))
        .returning(Counterparty.id)
    )
    if new_id is None:
        raise Conflict(f"a person named {name!r} already exists")
    return session.get_one(Counterparty, new_id)


def person_account(
    session: Session, user_id: uuid.UUID, counterparty_id: uuid.UUID, subtype: AccountSubtype
) -> Account:
    """The counterparty's receivable or payable account, created on first use (§4). Read FOR
    SHARE like any account about to be posted to. Raises I4 if it is archived."""
    if subtype not in (Sub.receivable, Sub.payable):
        raise RuleViolation("account", f"{subtype} is not a person account")
    q = select(Counterparty).where(
        Counterparty.id == counterparty_id, Counterparty.user_id == user_id
    )
    person = session.scalars(q).one_or_none()
    if person is None:
        raise NotFound(f"counterparty {counterparty_id}")

    label = f"{person.name} owes me" if subtype is Sub.receivable else f"I owe {person.name}"
    # A racing first use waits on the one-per-counterparty unique index, then finds this row.
    session.execute(
        insert(Account)
        .values(
            user_id=user_id,
            name=label,
            kind=KIND_OF[subtype],
            subtype=subtype,
            counterparty_id=counterparty_id,
        )
        .on_conflict_do_nothing()
    )
    q2 = select(Account.id).where(
        Account.counterparty_id == counterparty_id, Account.subtype == subtype
    )
    acct = _lock_account(session, user_id, session.scalars(q2).one())
    if not acct.is_active:
        raise RuleViolation("I4", f"account {acct.name!r} is archived")
    return acct


def archive_account(session: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    acct = _lock_account(session, user_id, account_id, exclusive=True)
    if acct.kind is AccountKind.EXTERNAL:
        raise RuleViolation("archive", f"{acct.subtype} cannot be archived")
    balance = balance_raw(session, user_id, account_id)
    if balance != 0:
        raise RuleViolation("I9", f"account {acct.name!r} has balance {balance}, not 0")
    acct.is_active = False
    session.flush()
    return acct


def unarchive_account(session: Session, user_id: uuid.UUID, account_id: uuid.UUID) -> Account:
    acct = _lock_account(session, user_id, account_id, exclusive=True)
    acct.is_active = True
    session.flush()
    return acct


# --- The ten templates (§4). X is amount_minor, always positive; debit is positive. ----------


def spend(
    session: Session,
    user_id: uuid.UUID,
    *,
    funding_id: uuid.UUID,
    amount_minor: int,
    category_id: uuid.UUID | None,
    occurred_on: date,
    memo: str = "",
    method: PaymentMethod | None = None,
) -> Transaction:
    """world +X, funding -X."""
    _check_inputs(amount_minor, occurred_on)
    funding = _account(session, user_id, funding_id, CASH_BANK_CARD, T.spend, "funding")
    cat = _category(session, user_id, category_id, T.spend)
    world = _outside(session, user_id, Sub.world)
    legs = [(world, amount_minor), (funding, -amount_minor)]
    return _write(
        session, user_id, T.spend, occurred_on, legs, category_id=cat.id, memo=memo, method=method
    )


def income(
    session: Session,
    user_id: uuid.UUID,
    *,
    dest_id: uuid.UUID,
    amount_minor: int,
    category_id: uuid.UUID | None,
    occurred_on: date,
    memo: str = "",
    method: PaymentMethod | None = None,
) -> Transaction:
    """dest +X, world -X."""
    _check_inputs(amount_minor, occurred_on)
    dest = _account(session, user_id, dest_id, CASH_BANK, T.income, "destination")
    cat = _category(session, user_id, category_id, T.income)
    world = _outside(session, user_id, Sub.world)
    legs = [(dest, amount_minor), (world, -amount_minor)]
    return _write(
        session, user_id, T.income, occurred_on, legs, category_id=cat.id, memo=memo, method=method
    )


def refund(
    session: Session,
    user_id: uuid.UUID,
    *,
    funding_id: uuid.UUID,
    amount_minor: int,
    occurred_on: date,
    category_id: uuid.UUID | None = None,
    refund_of_id: uuid.UUID | None = None,
    memo: str = "",
    method: PaymentMethod | None = None,
) -> Transaction:
    """funding +X, world -X. With refund_of_id, the original must be a live spend of this user;
    the refund takes its category, and live refunds against it may not exceed its amount."""
    _check_inputs(amount_minor, occurred_on)
    funding = _account(session, user_id, funding_id, CASH_BANK_CARD, T.refund, "funding")
    if refund_of_id is not None:
        original = _transaction(session, user_id, refund_of_id)  # FOR UPDATE: serialises refunds
        if original.template is not T.spend:
            raise RuleViolation("refund", f"only a spend can be refunded, not {original.template}")
        if original.voided_at is not None:
            raise RuleViolation("refund", "the spend is void")
        if category_id is not None and category_id != original.category_id:
            raise RuleViolation("refund", "a refund takes the category of the spend it refunds")
        category_id = original.category_id
        left = _amount(session, original.id) - _refunded(session, user_id, original.id)
        if amount_minor > left:
            raise RuleViolation("refund", f"only {left} of the spend is left to refund")
    cat = _category(session, user_id, category_id, T.refund)
    world = _outside(session, user_id, Sub.world)
    legs = [(funding, amount_minor), (world, -amount_minor)]
    return _write(
        session,
        user_id,
        T.refund,
        occurred_on,
        legs,
        category_id=cat.id,
        memo=memo,
        method=method,
        refund_of_id=refund_of_id,
    )


def transfer(
    session: Session,
    user_id: uuid.UUID,
    *,
    from_id: uuid.UUID,
    to_id: uuid.UUID,
    amount_minor: int,
    occurred_on: date,
    memo: str = "",
    method: PaymentMethod | None = None,
) -> Transaction:
    """to +X, from -X. Cash and bank only; a card on either side is a card_payment (R-07)."""
    _check_inputs(amount_minor, occurred_on)
    if from_id == to_id:
        raise RuleViolation("I3", "both sides are the same account")
    to = _account(session, user_id, to_id, CASH_BANK, T.transfer, "destination")
    frm = _account(session, user_id, from_id, CASH_BANK, T.transfer, "source")
    legs = [(to, amount_minor), (frm, -amount_minor)]
    return _write(session, user_id, T.transfer, occurred_on, legs, memo=memo, method=method)


def card_payment(
    session: Session,
    user_id: uuid.UUID,
    *,
    card_id: uuid.UUID,
    funding_id: uuid.UUID,
    amount_minor: int,
    occurred_on: date,
    memo: str = "",
    method: PaymentMethod | None = None,
) -> Transaction:
    """card +X, funding -X. Never a category, so never spending."""
    _check_inputs(amount_minor, occurred_on)
    card = _account(session, user_id, card_id, CARD, T.card_payment, "card")
    funding = _account(session, user_id, funding_id, CASH_BANK, T.card_payment, "funding")
    legs = [(card, amount_minor), (funding, -amount_minor)]
    return _write(session, user_id, T.card_payment, occurred_on, legs, memo=memo, method=method)


def lend(
    session: Session,
    user_id: uuid.UUID,
    *,
    counterparty_id: uuid.UUID,
    funding_id: uuid.UUID,
    amount_minor: int,
    occurred_on: date,
    memo: str = "",
    method: PaymentMethod | None = None,
) -> Transaction:
    """receivable:P +X, funding -X. A card may fund it: that is how bill-splitting works."""
    _check_inputs(amount_minor, occurred_on)
    funding = _account(session, user_id, funding_id, CASH_BANK_CARD, T.lend, "funding")
    recv = person_account(session, user_id, counterparty_id, Sub.receivable)
    legs = [(recv, amount_minor), (funding, -amount_minor)]
    return _write(session, user_id, T.lend, occurred_on, legs, memo=memo, method=method)


def friend_repay(
    session: Session,
    user_id: uuid.UUID,
    *,
    counterparty_id: uuid.UUID,
    funding_id: uuid.UUID,
    amount_minor: int,
    occurred_on: date,
    memo: str = "",
    method: PaymentMethod | None = None,
) -> Transaction:
    """funding +X, receivable:P -X."""
    _check_inputs(amount_minor, occurred_on)
    funding = _account(session, user_id, funding_id, CASH_BANK, T.friend_repay, "funding")
    recv = person_account(session, user_id, counterparty_id, Sub.receivable)
    legs = [(funding, amount_minor), (recv, -amount_minor)]
    return _write(session, user_id, T.friend_repay, occurred_on, legs, memo=memo, method=method)


def borrow(
    session: Session,
    user_id: uuid.UUID,
    *,
    counterparty_id: uuid.UUID,
    dest_id: uuid.UUID,
    amount_minor: int,
    occurred_on: date,
    memo: str = "",
    method: PaymentMethod | None = None,
) -> Transaction:
    """dest +X, payable:P -X."""
    _check_inputs(amount_minor, occurred_on)
    dest = _account(session, user_id, dest_id, CASH_BANK, T.borrow, "destination")
    pay = person_account(session, user_id, counterparty_id, Sub.payable)
    legs = [(dest, amount_minor), (pay, -amount_minor)]
    return _write(session, user_id, T.borrow, occurred_on, legs, memo=memo, method=method)


def repay_friend(
    session: Session,
    user_id: uuid.UUID,
    *,
    counterparty_id: uuid.UUID,
    funding_id: uuid.UUID,
    amount_minor: int,
    occurred_on: date,
    memo: str = "",
    method: PaymentMethod | None = None,
) -> Transaction:
    """payable:P +X, funding -X."""
    _check_inputs(amount_minor, occurred_on)
    funding = _account(session, user_id, funding_id, CASH_BANK, T.repay_friend, "funding")
    pay = person_account(session, user_id, counterparty_id, Sub.payable)
    legs = [(pay, amount_minor), (funding, -amount_minor)]
    return _write(session, user_id, T.repay_friend, occurred_on, legs, memo=memo, method=method)


def opening(
    session: Session,
    user_id: uuid.UUID,
    *,
    account_id: uuid.UUID,
    amount_minor: int,
    occurred_on: date,
    memo: str = "",
) -> Transaction:
    """Asset: acct +X, opening -X. Liability, where X is the amount owed: opening +X, acct -X.
    At most one live opening per account (I10)."""
    _check_inputs(amount_minor, occurred_on)
    acct = _account(
        session, user_id, account_id, NOT_EXTERNAL, T.opening, "account", exclusive=True
    )
    existing = session.scalar(
        select(func.count())
        .select_from(Transaction)
        .join(Posting, Posting.transaction_id == Transaction.id)
        .where(
            Transaction.user_id == user_id,
            Transaction.template == T.opening,
            Transaction.voided_at.is_(None),
            Posting.account_id == account_id,
        )
    )
    if existing:
        raise RuleViolation("I10", f"account {acct.name!r} already has an opening balance")
    outside = _outside(session, user_id, Sub.opening)
    if acct.kind is AccountKind.ASSET:
        legs = [(acct, amount_minor), (outside, -amount_minor)]
    else:
        legs = [(outside, amount_minor), (acct, -amount_minor)]
    return _write(session, user_id, T.opening, occurred_on, legs, memo=memo)


# --- Corrections (§6): void, and the three editable fields -----------------------------------


def void(session: Session, user_id: uuid.UUID, transaction_id: uuid.UUID) -> Transaction:
    """Final; the transaction drops out of every figure. A second void is a Conflict (R-21)."""
    txn = _transaction(session, user_id, transaction_id)
    if txn.voided_at is not None:
        raise Conflict(f"transaction {transaction_id} is already void")
    if txn.template is T.spend and _refunded(session, user_id, txn.id):
        raise RuleViolation("refund", "void this spend's refunds first")
    # An archived account holds zero (I9); voiding into it would change that.
    account_ids = session.scalars(
        select(Posting.account_id).where(Posting.transaction_id == txn.id)
    )
    for account_id in account_ids.all():
        acct = _lock_account(session, user_id, account_id)
        if not acct.is_active:
            raise RuleViolation("I9", f"account {acct.name!r} is archived; unarchive it first")
    txn.voided_at = datetime.now(UTC)
    session.flush()
    return txn


def set_memo(
    session: Session, user_id: uuid.UUID, transaction_id: uuid.UUID, memo: str
) -> Transaction:
    txn = _transaction(session, user_id, transaction_id)
    txn.memo = memo
    session.flush()
    return txn


def set_method(
    session: Session, user_id: uuid.UUID, transaction_id: uuid.UUID, method: PaymentMethod | None
) -> Transaction:
    txn = _transaction(session, user_id, transaction_id)
    txn.method = method
    session.flush()
    return txn


def set_category(
    session: Session, user_id: uuid.UUID, transaction_id: uuid.UUID, category_id: uuid.UUID | None
) -> Transaction:
    """Subject to I5 and I8. A linked refund keeps its spend's category; recategorising the
    spend moves its refunds with it (D-010)."""
    txn = _transaction(session, user_id, transaction_id)
    if txn.template not in (T.spend, T.income, T.refund):
        if category_id is not None:
            raise RuleViolation("I5", f"a {txn.template} cannot have a category")
        return txn
    if txn.refund_of_id is not None and category_id != txn.category_id:
        raise RuleViolation("refund", "a refund takes its spend's category; change the spend")
    cat = _category(session, user_id, category_id, txn.template)
    txn.category_id = cat.id
    if txn.template is T.spend:
        session.execute(
            update(Transaction)
            .where(Transaction.user_id == user_id, Transaction.refund_of_id == txn.id)
            .values(category_id=cat.id)
        )
    session.flush()
    return txn
