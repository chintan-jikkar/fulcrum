"""The ten transaction templates and the write-path rules (CLAUDE.md §4, §6; SCENARIOS.md §A, §B).

Every scenario starts from the §A base state: Chase 150000, Wallet 40000, Amex 0 with a limit of
500000, set through the `opening` template. Each test commits, so the deferred database checks
(I1, I2, I5) run on everything the service writes.

Figures beyond raw balances (net worth, category totals) arrive with the queries in P1 task 4.
"""

import threading
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models.ledger import (
    Account,
    AccountSubtype,
    Category,
    PaymentMethod,
    Posting,
    Transaction,
)
from app.services import ledger
from app.services.ledger import Conflict, NotFound, RuleViolation
from app.services.users import provision_user

DAY = date(2026, 3, 1)
OPENED = date(2026, 2, 28)


@dataclass
class Book:
    s: Session
    uid: uuid.UUID
    world: uuid.UUID
    opening: uuid.UUID
    chase: uuid.UUID
    wallet: uuid.UUID
    amex: uuid.UUID
    raj: uuid.UUID
    mia: uuid.UUID

    def category(self, name: str) -> uuid.UUID:
        q = select(Category.id).where(Category.user_id == self.uid, Category.name == name)
        return self.s.scalars(q).one()

    def outside(self, subtype: AccountSubtype) -> uuid.UUID:
        q = select(Account.id).where(Account.user_id == self.uid, Account.subtype == subtype)
        return self.s.scalars(q).one()

    def balance(self, account_id: uuid.UUID) -> int:
        return ledger.balance_raw(self.s, self.uid, account_id)

    def recv(self, counterparty: uuid.UUID) -> uuid.UUID:
        return ledger.person_account(self.s, self.uid, counterparty, AccountSubtype.receivable).id

    def pay(self, counterparty: uuid.UUID) -> uuid.UUID:
        return ledger.person_account(self.s, self.uid, counterparty, AccountSubtype.payable).id

    def legs(self, txn: Transaction) -> set[tuple[uuid.UUID, int]]:
        q = select(Posting.account_id, Posting.amount_minor).where(Posting.transaction_id == txn.id)
        return {(a, n) for a, n in self.s.execute(q)}

    def txn_count(self) -> int:
        q = select(func.count()).select_from(Transaction).where(Transaction.user_id == self.uid)
        count: int = self.s.scalar(q) or 0
        return count

    # Shorthands for the common calls; everything else passes straight through.
    def spend(self, funding: uuid.UUID, amount: int, category: str = "Food") -> Transaction:
        return ledger.spend(
            self.s,
            self.uid,
            funding_id=funding,
            amount_minor=amount,
            category_id=self.category(category),
            occurred_on=DAY,
        )

    def refund(
        self, funding: uuid.UUID, amount: int, of: Transaction | None, **kw: Any
    ) -> Transaction:
        return ledger.refund(
            self.s,
            self.uid,
            funding_id=funding,
            amount_minor=amount,
            refund_of_id=of.id if of else None,
            occurred_on=DAY,
            **kw,
        )


def make_book(engine: Engine) -> Iterator[Book]:
    with Session(engine) as s:
        uid = provision_user(s, f"test|{uuid.uuid4()}", "Test User", "America/New_York").id

        def account(name: str, subtype: AccountSubtype, **meta: Any) -> uuid.UUID:
            return ledger.create_account(s, uid, name=name, subtype=subtype, meta=meta).id

        chase = account("Chase", AccountSubtype.bank)
        wallet = account("Wallet", AccountSubtype.cash)
        amex = account("Amex", AccountSubtype.credit_card, limit_minor=500000)
        for acct, amount in [(chase, 150000), (wallet, 40000)]:
            ledger.opening(s, uid, account_id=acct, amount_minor=amount, occurred_on=OPENED)
        raj = ledger.create_counterparty(s, uid, name="Raj").id
        mia = ledger.create_counterparty(s, uid, name="Mia").id
        s.commit()

        q = select(Account.id).where(Account.user_id == uid)
        book = Book(
            s,
            uid,
            world=s.scalars(q.where(Account.subtype == AccountSubtype.world)).one(),
            opening=s.scalars(q.where(Account.subtype == AccountSubtype.opening)).one(),
            chase=chase,
            wallet=wallet,
            amex=amex,
            raj=raj,
            mia=mia,
        )
        yield book
        s.rollback()


@pytest.fixture
def book(engine: Engine) -> Iterator[Book]:
    yield from make_book(engine)


@pytest.fixture
def other(engine: Engine) -> Iterator[Book]:
    yield from make_book(engine)


def rejected(b: Book, rule: str, call: Callable[[], object]) -> None:
    """The call raises RuleViolation for `rule`, and nothing it wrote survives."""
    before = b.txn_count()
    with pytest.raises(RuleViolation) as err:
        call()
    assert err.value.rule == rule, err.value
    b.s.rollback()
    assert b.txn_count() == before


def test_base_state(book: Book) -> None:
    b = book
    assert (b.balance(b.chase), b.balance(b.wallet), b.balance(b.amex)) == (150000, 40000, 0)
    assert b.balance(b.opening) == -190000


# --- §A: one scenario per template ----------------------------------------------------------


def test_s01_spend_on_debit(book: Book) -> None:
    b = book
    txn = b.spend(b.chase, 4000)
    b.s.commit()
    assert b.legs(txn) == {(b.world, 4000), (b.chase, -4000)}
    assert txn.category_id == b.category("Food")
    assert b.balance(b.chase) == 146000


def test_s02_spend_on_card(book: Book) -> None:
    b = book
    txn = b.spend(b.amex, 4000)
    b.s.commit()
    assert b.legs(txn) == {(b.world, 4000), (b.amex, -4000)}
    assert (b.balance(b.amex), b.balance(b.chase)) == (-4000, 150000)


def test_s03_card_payment_is_not_spending(book: Book) -> None:
    b = book
    ledger.opening(b.s, b.uid, account_id=b.amex, amount_minor=20000, occurred_on=OPENED)
    txn = ledger.card_payment(
        b.s, b.uid, card_id=b.amex, funding_id=b.chase, amount_minor=20000, occurred_on=DAY
    )
    b.s.commit()
    assert b.legs(txn) == {(b.amex, 20000), (b.chase, -20000)}
    assert txn.category_id is None
    assert (b.balance(b.amex), b.balance(b.chase)) == (0, 130000)


def test_s04_s05_lend_cash_then_repaid_by_zelle(book: Book) -> None:
    b = book
    lent = ledger.lend(
        b.s,
        b.uid,
        counterparty_id=b.raj,
        funding_id=b.wallet,
        amount_minor=5000,
        occurred_on=DAY,
        method=PaymentMethod.cash,
    )
    b.s.commit()
    recv = b.recv(b.raj)
    assert b.legs(lent) == {(recv, 5000), (b.wallet, -5000)}
    assert (lent.category_id, lent.method) == (None, PaymentMethod.cash)
    assert (b.balance(b.wallet), b.balance(recv)) == (35000, 5000)

    repaid = ledger.friend_repay(
        b.s,
        b.uid,
        counterparty_id=b.raj,
        funding_id=b.chase,
        amount_minor=5000,
        occurred_on=DAY,
        method=PaymentMethod.bank_transfer,
    )
    b.s.commit()
    assert b.legs(repaid) == {(b.chase, 5000), (recv, -5000)}
    assert (b.balance(b.chase), b.balance(recv)) == (155000, 0)


def test_s06_paycheck(book: Book) -> None:
    b = book
    txn = ledger.income(
        b.s,
        b.uid,
        dest_id=b.chase,
        amount_minor=60000,
        category_id=b.category("Salary"),
        occurred_on=DAY,
    )
    b.s.commit()
    assert b.legs(txn) == {(b.chase, 60000), (b.world, -60000)}
    assert b.balance(b.chase) == 210000


def test_s07_cash_deposit_is_a_transfer(book: Book) -> None:
    b = book
    txn = ledger.transfer(
        b.s, b.uid, from_id=b.wallet, to_id=b.chase, amount_minor=30000, occurred_on=DAY
    )
    b.s.commit()
    assert b.legs(txn) == {(b.chase, 30000), (b.wallet, -30000)}
    assert (b.balance(b.chase), b.balance(b.wallet)) == (180000, 10000)


def test_s08_s09_borrow_then_repay(book: Book) -> None:
    b = book
    borrowed = ledger.borrow(
        b.s, b.uid, counterparty_id=b.mia, dest_id=b.chase, amount_minor=2500, occurred_on=DAY
    )
    b.s.commit()
    pay = b.pay(b.mia)
    assert b.legs(borrowed) == {(b.chase, 2500), (pay, -2500)}
    assert (b.balance(b.chase), b.balance(pay)) == (152500, -2500)

    repaid = ledger.repay_friend(
        b.s, b.uid, counterparty_id=b.mia, funding_id=b.chase, amount_minor=2500, occurred_on=DAY
    )
    b.s.commit()
    assert b.legs(repaid) == {(pay, 2500), (b.chase, -2500)}
    assert (b.balance(b.chase), b.balance(pay)) == (150000, 0)


def test_s10_partial_refund_takes_the_spends_category(book: Book) -> None:
    b = book
    sp = b.spend(b.chase, 4000)
    txn = b.refund(b.chase, 1000, of=sp)
    b.s.commit()
    assert b.legs(txn) == {(b.chase, 1000), (b.world, -1000)}
    assert (txn.category_id, txn.refund_of_id) == (b.category("Food"), sp.id)
    assert b.balance(b.chase) == 147000


def test_unlinked_refund_needs_an_expense_category(book: Book) -> None:
    b = book
    txn = b.refund(b.amex, 1000, of=None, category_id=b.category("Shopping"))
    b.s.commit()
    assert b.legs(txn) == {(b.amex, 1000), (b.world, -1000)}
    rejected(b, "I5", lambda: b.refund(b.amex, 1000, of=None))
    rejected(b, "I8", lambda: b.refund(b.amex, 1000, of=None, category_id=b.category("Salary")))


def test_s11_opening_on_a_card_records_what_is_owed(book: Book) -> None:
    b = book
    txn = ledger.opening(b.s, b.uid, account_id=b.amex, amount_minor=20000, occurred_on=OPENED)
    b.s.commit()
    assert b.legs(txn) == {(b.opening, 20000), (b.amex, -20000)}
    assert txn.category_id is None
    assert b.balance(b.amex) == -20000


def test_opening_on_a_person_account(book: Book) -> None:
    # SCENARIOS.md G-04: Tom already owes $30.00.
    b = book
    tom = ledger.create_counterparty(b.s, b.uid, name="Tom").id
    recv = b.recv(tom)
    txn = ledger.opening(b.s, b.uid, account_id=recv, amount_minor=3000, occurred_on=OPENED)
    b.s.commit()
    assert b.legs(txn) == {(recv, 3000), (b.opening, -3000)}


def test_s12_split_dinner_on_a_card(book: Book) -> None:
    b = book
    own = b.spend(b.amex, 4000)
    lent = ledger.lend(
        b.s, b.uid, counterparty_id=b.mia, funding_id=b.amex, amount_minor=2000, occurred_on=DAY
    )
    b.s.commit()
    recv = b.recv(b.mia)
    assert b.legs(own) == {(b.world, 4000), (b.amex, -4000)}
    assert b.legs(lent) == {(recv, 2000), (b.amex, -2000)}
    assert (b.balance(b.amex), b.balance(recv)) == (-6000, 2000)


def test_person_account_is_created_once_per_counterparty(book: Book) -> None:
    b = book
    for _ in range(2):
        ledger.lend(
            b.s,
            b.uid,
            counterparty_id=b.raj,
            funding_id=b.wallet,
            amount_minor=100,
            occurred_on=DAY,
        )
    b.s.commit()
    q = select(func.count()).where(
        Account.counterparty_id == b.raj, Account.subtype == AccountSubtype.receivable
    )
    assert b.s.scalar(q) == 1
    assert b.balance(b.recv(b.raj)) == 200


def test_memo_and_method_are_stored(book: Book) -> None:
    b = book
    txn = ledger.transfer(
        b.s,
        b.uid,
        from_id=b.chase,
        to_id=b.wallet,
        amount_minor=100,
        occurred_on=DAY,
        memo="ATM",
        method=PaymentMethod.other,
    )
    b.s.commit()
    assert (txn.memo, txn.method, txn.occurred_on) == ("ATM", PaymentMethod.other, DAY)


# --- §B: things that must be rejected -------------------------------------------------------


def test_r01_category_on_a_card_payment(book: Book) -> None:
    # The template takes no category, so the only way to try is an edit.
    b = book
    txn = ledger.card_payment(
        b.s, b.uid, card_id=b.amex, funding_id=b.chase, amount_minor=100, occurred_on=DAY
    )
    b.s.commit()
    rejected(b, "I5", lambda: ledger.set_category(b.s, b.uid, txn.id, b.category("Food")))


def test_r02_spend_without_a_category(book: Book) -> None:
    b = book
    rejected(
        b,
        "I5",
        lambda: ledger.spend(
            b.s,
            b.uid,
            funding_id=b.chase,
            amount_minor=100,
            category_id=None,
            occurred_on=DAY,
        ),
    )


def test_r03_category_kind_must_match_the_template(book: Book) -> None:
    b = book
    rejected(b, "I8", lambda: b.spend(b.chase, 100, category="Salary"))
    rejected(
        b,
        "I8",
        lambda: ledger.income(
            b.s,
            b.uid,
            dest_id=b.chase,
            amount_minor=100,
            category_id=b.category("Food"),
            occurred_on=DAY,
        ),
    )


def test_i8_archived_category_is_rejected(book: Book) -> None:
    b = book
    food = b.s.get_one(Category, b.category("Food"))
    food.is_archived = True
    b.s.commit()
    rejected(b, "I8", lambda: b.spend(b.chase, 100))


@pytest.mark.parametrize("amount", [0, -4000, True, 1.5, "100", 2**63])
def test_r04_amount_must_be_a_positive_integer(book: Book, amount: Any) -> None:
    b = book
    rejected(b, "I3", lambda: b.spend(b.chase, amount))


def test_occurred_on_must_be_a_bare_date(book: Book) -> None:
    b = book
    rejected(
        b,
        "occurred_on",
        lambda: ledger.transfer(
            b.s,
            b.uid,
            from_id=b.chase,
            to_id=b.wallet,
            amount_minor=100,
            occurred_on=datetime(2026, 3, 1, 12),
        ),
    )


def test_r05_no_posting_on_an_archived_account(book: Book) -> None:
    b = book
    savings = ledger.create_account(b.s, b.uid, name="Savings", subtype=AccountSubtype.bank)
    ledger.archive_account(b.s, b.uid, savings.id)
    b.s.commit()
    rejected(b, "I4", lambda: b.spend(savings.id, 100))
    rejected(
        b,
        "I4",
        lambda: ledger.transfer(
            b.s, b.uid, from_id=b.chase, to_id=savings.id, amount_minor=100, occurred_on=DAY
        ),
    )


def test_r05_archived_person_account_is_rejected(book: Book) -> None:
    b = book
    recv = b.recv(b.raj)
    ledger.archive_account(b.s, b.uid, recv)
    b.s.commit()
    rejected(
        b,
        "I4",
        lambda: ledger.lend(
            b.s, b.uid, counterparty_id=b.raj, funding_id=b.chase, amount_minor=1, occurred_on=DAY
        ),
    )


def test_unarchived_account_takes_postings_again(book: Book) -> None:
    b = book
    savings = ledger.create_account(b.s, b.uid, name="Savings", subtype=AccountSubtype.bank)
    ledger.archive_account(b.s, b.uid, savings.id)
    ledger.unarchive_account(b.s, b.uid, savings.id)
    b.spend(savings.id, 100)
    b.s.commit()
    assert b.balance(savings.id) == -100


def test_r06_transfer_to_the_same_account(book: Book) -> None:
    b = book
    rejected(
        b,
        "I3",
        lambda: ledger.transfer(
            b.s, b.uid, from_id=b.chase, to_id=b.chase, amount_minor=100, occurred_on=DAY
        ),
    )


@pytest.mark.parametrize("side", ["from", "to"])
def test_r07_transfer_with_a_card_is_rejected(book: Book, side: str) -> None:
    b = book
    frm, to = (b.amex, b.chase) if side == "from" else (b.chase, b.amex)
    before = b.txn_count()
    with pytest.raises(RuleViolation, match="card_payment") as err:
        ledger.transfer(b.s, b.uid, from_id=frm, to_id=to, amount_minor=100, occurred_on=DAY)
    assert err.value.rule == "template"
    b.s.rollback()
    assert b.txn_count() == before


@pytest.mark.parametrize(
    ("call", "kwargs"),
    [
        (ledger.spend, {"funding_id": "receivable"}),
        (ledger.income, {"dest_id": "amex"}),
        (ledger.card_payment, {"card_id": "chase", "funding_id": "wallet"}),
        (ledger.card_payment, {"card_id": "amex", "funding_id": "amex"}),
        (ledger.friend_repay, {"funding_id": "amex"}),
        (ledger.borrow, {"dest_id": "amex"}),
        (ledger.repay_friend, {"funding_id": "amex"}),
    ],
)
def test_accounts_outside_a_templates_allowed_set_are_rejected(
    book: Book, call: Callable[..., Transaction], kwargs: dict[str, str]
) -> None:
    b = book
    ids = {"chase": b.chase, "wallet": b.wallet, "amex": b.amex, "receivable": b.recv(b.raj)}
    b.s.commit()
    args: dict[str, Any] = {k: ids[v] for k, v in kwargs.items()}
    if call in (ledger.spend, ledger.income):
        args["category_id"] = b.category("Food" if call is ledger.spend else "Salary")
    if call in (ledger.friend_repay, ledger.borrow, ledger.repay_friend):
        args["counterparty_id"] = b.raj
    rejected(b, "template", lambda: call(b.s, b.uid, amount_minor=100, occurred_on=DAY, **args))


def test_outside_accounts_are_never_used_directly(book: Book) -> None:
    b = book
    rejected(b, "template", lambda: b.spend(b.world, 100))
    rejected(
        b,
        "template",
        lambda: ledger.opening(b.s, b.uid, account_id=b.opening, amount_minor=100, occurred_on=DAY),
    )


def test_r08_refund_cannot_exceed_the_original(book: Book) -> None:
    b = book
    sp = b.spend(b.chase, 4000)
    b.s.commit()
    rejected(b, "refund", lambda: b.refund(b.chase, 4001, of=sp))
    b.refund(b.chase, 3000, of=sp)
    b.s.commit()
    rejected(b, "refund", lambda: b.refund(b.chase, 1001, of=sp))
    b.refund(b.chase, 1000, of=sp)  # exactly the rest is fine
    b.s.commit()


def test_voided_refunds_do_not_count_toward_the_cap(book: Book) -> None:
    b = book
    sp = b.spend(b.chase, 4000)
    first = b.refund(b.chase, 4000, of=sp)
    ledger.void(b.s, b.uid, first.id)
    b.refund(b.chase, 4000, of=sp)
    b.s.commit()


def test_refund_must_point_at_a_live_spend(book: Book) -> None:
    b = book
    paycheck = ledger.income(
        b.s,
        b.uid,
        dest_id=b.chase,
        amount_minor=100,
        category_id=b.category("Salary"),
        occurred_on=DAY,
    )
    sp = b.spend(b.chase, 100)
    ledger.void(b.s, b.uid, sp.id)
    b.s.commit()
    rejected(b, "refund", lambda: b.refund(b.chase, 100, of=paycheck))
    rejected(b, "refund", lambda: b.refund(b.chase, 100, of=sp))


def test_r09_refund_category_must_match_the_original(book: Book) -> None:
    b = book
    sp = b.spend(b.chase, 4000)
    b.s.commit()
    rejected(b, "refund", lambda: b.refund(b.chase, 100, of=sp, category_id=b.category("Health")))
    same = b.refund(b.chase, 100, of=sp, category_id=b.category("Food"))
    b.s.commit()
    assert same.category_id == b.category("Food")


def test_racing_refunds_cannot_exceed_the_original(engine: Engine, book: Book) -> None:
    b = book
    sp = b.spend(b.chase, 4000)
    b.s.commit()
    outcome: list[str] = []

    def second_refund() -> None:
        with Session(engine) as s2:
            try:
                ledger.refund(
                    s2,
                    b.uid,
                    funding_id=b.chase,
                    amount_minor=3000,
                    refund_of_id=sp.id,
                    occurred_on=DAY,
                )
                s2.commit()
                outcome.append("written")
            except RuleViolation as e:
                outcome.append(e.rule)

    with Session(engine) as s1:
        ledger.refund(
            s1, b.uid, funding_id=b.chase, amount_minor=3000, refund_of_id=sp.id, occurred_on=DAY
        )
        racer = threading.Thread(target=second_refund)
        racer.start()
        racer.join(timeout=0.5)
        assert racer.is_alive(), "the second refund should wait for the first to commit"
        s1.commit()
    racer.join(timeout=10)
    assert outcome == ["refund"]


def test_r10_spend_with_live_refunds_cannot_be_voided(book: Book) -> None:
    b = book
    sp = b.spend(b.chase, 4000)
    rf = b.refund(b.chase, 1000, of=sp)
    b.s.commit()
    rejected(b, "refund", lambda: ledger.void(b.s, b.uid, sp.id))
    ledger.void(b.s, b.uid, rf.id)
    ledger.void(b.s, b.uid, sp.id)
    b.s.commit()
    assert b.balance(b.chase) == 150000


def test_r13_account_with_a_balance_cannot_be_archived(book: Book) -> None:
    b = book
    rejected(b, "I9", lambda: ledger.archive_account(b.s, b.uid, b.chase))
    # A future-dated posting counts: the balance is not zero, only not yet.
    savings = ledger.create_account(b.s, b.uid, name="Savings", subtype=AccountSubtype.bank)
    ledger.transfer(
        b.s,
        b.uid,
        from_id=b.chase,
        to_id=savings.id,
        amount_minor=100,
        occurred_on=date(2099, 1, 1),
    )
    b.s.commit()
    rejected(b, "I9", lambda: ledger.archive_account(b.s, b.uid, savings.id))


def test_outside_accounts_cannot_be_archived(book: Book) -> None:
    b = book
    rejected(b, "archive", lambda: ledger.archive_account(b.s, b.uid, b.world))


def test_void_that_would_move_an_archived_account_is_rejected(book: Book) -> None:
    # Archived accounts stay at zero (I9), so a void may not change their balance either.
    b = book
    savings = ledger.create_account(b.s, b.uid, name="Savings", subtype=AccountSubtype.bank)
    txn = ledger.transfer(
        b.s, b.uid, from_id=b.chase, to_id=savings.id, amount_minor=100, occurred_on=DAY
    )
    ledger.transfer(
        b.s, b.uid, from_id=savings.id, to_id=b.chase, amount_minor=100, occurred_on=DAY
    )
    ledger.archive_account(b.s, b.uid, savings.id)
    b.s.commit()
    with pytest.raises(RuleViolation) as err:
        ledger.void(b.s, b.uid, txn.id)
    assert err.value.rule == "I9"


def test_r14_only_memo_method_and_category_can_be_edited(book: Book) -> None:
    b = book
    txn = b.spend(b.chase, 4000)
    b.s.commit()
    ledger.set_memo(b.s, b.uid, txn.id, "groceries")
    ledger.set_method(b.s, b.uid, txn.id, PaymentMethod.card)
    ledger.set_category(b.s, b.uid, txn.id, b.category("Shopping"))
    b.s.commit()
    assert (txn.memo, txn.method, txn.category_id) == (
        "groceries",
        PaymentMethod.card,
        b.category("Shopping"),
    )
    assert b.legs(txn) == {(b.world, 4000), (b.chase, -4000)}
    # Amount, accounts, date and template have no edit function; the database refuses them too
    # (test_ledger_schema.py, R-14).


def test_category_edits_follow_i5_and_i8(book: Book) -> None:
    b = book
    sp = b.spend(b.chase, 4000)
    b.s.commit()
    rejected(b, "I5", lambda: ledger.set_category(b.s, b.uid, sp.id, None))
    rejected(b, "I8", lambda: ledger.set_category(b.s, b.uid, sp.id, b.category("Salary")))
    move = ledger.transfer(
        b.s, b.uid, from_id=b.chase, to_id=b.wallet, amount_minor=1, occurred_on=DAY
    )
    b.s.commit()
    ledger.set_category(b.s, b.uid, move.id, None)  # already none: allowed, changes nothing
    b.s.commit()


def test_recategorising_a_spend_moves_its_refunds_too(book: Book) -> None:
    b = book
    sp = b.spend(b.chase, 4000)
    rf = b.refund(b.chase, 1000, of=sp)
    b.s.commit()
    rejected(b, "refund", lambda: ledger.set_category(b.s, b.uid, rf.id, b.category("Shopping")))
    ledger.set_category(b.s, b.uid, sp.id, b.category("Shopping"))
    b.s.commit()
    b.s.refresh(rf)
    assert rf.category_id == b.category("Shopping")


def test_r16_one_live_opening_per_account(book: Book) -> None:
    b = book
    first = b.s.scalars(
        select(Transaction)
        .join(Posting, Posting.transaction_id == Transaction.id)
        .where(Transaction.template == "opening", Posting.account_id == b.chase)
    ).one()
    rejected(
        b,
        "I10",
        lambda: ledger.opening(b.s, b.uid, account_id=b.chase, amount_minor=1, occurred_on=OPENED),
    )
    ledger.void(b.s, b.uid, first.id)
    ledger.opening(b.s, b.uid, account_id=b.chase, amount_minor=99, occurred_on=OPENED)
    b.s.commit()
    assert b.balance(b.chase) == 99


def test_r21_voiding_twice_is_a_conflict(book: Book) -> None:
    b = book
    txn = b.spend(b.chase, 100)
    ledger.void(b.s, b.uid, txn.id)
    b.s.commit()
    with pytest.raises(Conflict):
        ledger.void(b.s, b.uid, txn.id)
    assert b.balance(b.chase) == 150000


# --- Accounts and counterparties ------------------------------------------------------------


@pytest.mark.parametrize(
    "subtype",
    [AccountSubtype.world, AccountSubtype.opening, AccountSubtype.receivable],
)
def test_only_cash_bank_and_cards_are_created_directly(book: Book, subtype: AccountSubtype) -> None:
    b = book
    with pytest.raises(RuleViolation) as err:
        ledger.create_account(b.s, b.uid, name="X", subtype=subtype)
    assert err.value.rule == "account"


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "500000"])
def test_card_limit_must_be_a_positive_integer(book: Book, limit: Any) -> None:
    b = book
    with pytest.raises(RuleViolation):
        ledger.create_account(
            b.s, b.uid, name="Visa", subtype=AccountSubtype.credit_card, meta={"limit_minor": limit}
        )


def test_card_linked_bank_must_be_the_users_own_bank(book: Book, other: Book) -> None:
    b = book
    linked = ledger.create_account(
        b.s,
        b.uid,
        name="Visa",
        subtype=AccountSubtype.credit_card,
        meta={"linked_bank_id": str(b.chase)},
    )
    assert linked.meta == {"linked_bank_id": str(b.chase)}
    for bad in [str(b.wallet), "not-a-uuid"]:
        with pytest.raises(RuleViolation):
            ledger.create_account(
                b.s,
                b.uid,
                name="Visa",
                subtype=AccountSubtype.credit_card,
                meta={"linked_bank_id": bad},
            )
    with pytest.raises(NotFound):
        ledger.create_account(
            b.s,
            b.uid,
            name="Visa",
            subtype=AccountSubtype.credit_card,
            meta={"linked_bank_id": str(other.chase)},
        )


def test_counterparty_names_are_unique_ignoring_case(book: Book) -> None:
    b = book
    with pytest.raises(Conflict):
        ledger.create_counterparty(b.s, b.uid, name="  rAJ ")
    b.s.rollback()
    with pytest.raises(RuleViolation):
        ledger.create_counterparty(b.s, b.uid, name="   ")


# --- T-02: another tenant's ids behave like ids that do not exist ---------------------------


def test_t02_other_tenants_ids_are_not_found(book: Book, other: Book) -> None:
    b, o = book, other
    theirs = o.spend(o.chase, 100)
    o.s.commit()
    before = (b.txn_count(), o.txn_count())

    calls: list[Callable[[], object]] = [
        lambda: b.spend(o.chase, 100),
        lambda: ledger.spend(
            b.s,
            b.uid,
            funding_id=b.chase,
            amount_minor=100,
            category_id=o.category("Food"),
            occurred_on=DAY,
        ),
        lambda: ledger.lend(
            b.s, b.uid, counterparty_id=o.raj, funding_id=b.chase, amount_minor=1, occurred_on=DAY
        ),
        lambda: b.refund(b.chase, 100, of=theirs),
        lambda: ledger.void(b.s, b.uid, theirs.id),
        lambda: ledger.set_memo(b.s, b.uid, theirs.id, "mine now"),
        lambda: ledger.archive_account(b.s, b.uid, o.chase),
        lambda: ledger.person_account(b.s, b.uid, o.raj, AccountSubtype.receivable),
        lambda: ledger.opening(b.s, b.uid, account_id=o.amex, amount_minor=1, occurred_on=DAY),
    ]
    missing = uuid.uuid4()
    calls.append(lambda: ledger.void(b.s, b.uid, missing))
    for call in calls:
        with pytest.raises(NotFound):
            call()
        b.s.rollback()

    assert (b.txn_count(), o.txn_count()) == before
    o.s.refresh(theirs)
    assert (theirs.voided_at, theirs.memo) == (None, "")
