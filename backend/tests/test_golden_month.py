"""The golden month (SCENARIOS.md §D) and the derived figures of CLAUDE.md §5.

The month is entered through the templates exactly as §D lists it, and every figure §D states is
asserted to the cent. Each test builds its own copy, so D.7's voids cannot leak into another test.
"""

import uuid
from collections.abc import Generator, Iterator
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.models.ledger import Account, AccountSubtype, Category, CategoryKind, Transaction
from app.services import figures, ledger
from app.services.figures import Credit
from app.services.ledger import RuleViolation
from app.services.users import provision_user

Sub = AccountSubtype


def d(month_day: str) -> date:
    month, day = month_day.split("-")
    return date(2026, int(month), int(day))


@dataclass
class Month:
    s: Session
    uid: uuid.UUID
    acct: dict[str, uuid.UUID]  # chase, wallet, amex, visa, world, opening, recv:Tom, pay:Mia...
    person: dict[str, uuid.UUID]  # counterparty ids by name
    cat: dict[str, uuid.UUID]
    g: dict[int, Transaction]  # G-01..G-22


def build_month(engine: Engine) -> Generator[Month]:
    with Session(engine) as s:
        uid = provision_user(s, f"golden|{uuid.uuid4()}", "Golden", "America/New_York").id
        acct = {
            "chase": ledger.create_account(s, uid, name="Chase", subtype=Sub.bank).id,
            "wallet": ledger.create_account(s, uid, name="Wallet", subtype=Sub.cash).id,
            "amex": ledger.create_account(
                s, uid, name="Amex", subtype=Sub.credit_card, meta={"limit_minor": 500000}
            ).id,
            "visa": ledger.create_account(
                s, uid, name="Visa", subtype=Sub.credit_card, meta={"limit_minor": 200000}
            ).id,
        }
        for sub in (Sub.world, Sub.opening):
            q = select(Account.id).where(Account.user_id == uid, Account.subtype == sub)
            acct[sub] = s.scalars(q).one()
        person = {n: ledger.create_counterparty(s, uid, name=n).id for n in ("Tom", "Mia", "Raj")}
        cat = {c.name: c.id for c in s.scalars(select(Category).where(Category.user_id == uid))}
        a, p = acct, person
        g: dict[int, Transaction] = {}

        def op(n: int, fn: object, day: str, **kw: object) -> None:
            g[n] = fn(s, uid, occurred_on=d(day), **kw)  # type: ignore[operator]

        op(1, ledger.opening, "02-28", account_id=a["chase"], amount_minor=150000)
        op(2, ledger.opening, "02-28", account_id=a["wallet"], amount_minor=12000)
        op(3, ledger.opening, "02-28", account_id=a["amex"], amount_minor=20000)
        recv_tom = ledger.person_account(s, uid, p["Tom"], Sub.receivable).id
        op(4, ledger.opening, "02-28", account_id=recv_tom, amount_minor=3000)
        op(
            5,
            ledger.spend,
            "03-03",
            funding_id=a["chase"],
            amount_minor=4250,
            category_id=cat["Food"],
        )
        op(
            6,
            ledger.spend,
            "03-04",
            funding_id=a["wallet"],
            amount_minor=600,
            category_id=cat["Food"],
        )
        op(
            7,
            ledger.spend,
            "03-05",
            funding_id=a["amex"],
            amount_minor=4000,
            category_id=cat["Food"],
        )
        op(
            8,
            ledger.lend,
            "03-05",
            counterparty_id=p["Mia"],
            funding_id=a["amex"],
            amount_minor=2000,
        )
        op(
            9,
            ledger.lend,
            "03-06",
            counterparty_id=p["Raj"],
            funding_id=a["wallet"],
            amount_minor=5000,
        )
        op(
            10,
            ledger.spend,
            "03-07",
            funding_id=a["visa"],
            amount_minor=3500,
            category_id=cat["Transport"],
        )
        op(
            11,
            ledger.spend,
            "03-08",
            funding_id=a["visa"],
            amount_minor=1599,
            category_id=cat["Subscriptions"],
        )
        op(
            12,
            ledger.friend_repay,
            "03-10",
            counterparty_id=p["Tom"],
            funding_id=a["chase"],
            amount_minor=3000,
        )
        op(13, ledger.transfer, "03-12", from_id=a["wallet"], to_id=a["chase"], amount_minor=5000)
        op(
            14,
            ledger.borrow,
            "03-14",
            counterparty_id=p["Mia"],
            dest_id=a["chase"],
            amount_minor=2500,
        )
        op(
            15,
            ledger.income,
            "03-15",
            dest_id=a["chase"],
            amount_minor=90000,
            category_id=cat["Salary"],
        )
        op(
            16,
            ledger.spend,
            "03-16",
            funding_id=a["chase"],
            amount_minor=5820,
            category_id=cat["Food"],
        )
        op(
            17,
            ledger.refund,
            "03-18",
            funding_id=a["chase"],
            amount_minor=500,
            refund_of_id=g[16].id,
        )
        op(
            18,
            ledger.friend_repay,
            "03-20",
            counterparty_id=p["Raj"],
            funding_id=a["wallet"],
            amount_minor=3000,
        )
        op(
            19,
            ledger.card_payment,
            "03-22",
            card_id=a["amex"],
            funding_id=a["chase"],
            amount_minor=15000,
        )
        op(
            20,
            ledger.spend,
            "03-26",
            funding_id=a["wallet"],
            amount_minor=2700,
            category_id=cat["Food"],
        )
        op(
            21,
            ledger.repay_friend,
            "03-28",
            counterparty_id=p["Mia"],
            funding_id=a["chase"],
            amount_minor=500,
        )
        op(
            22,
            ledger.card_payment,
            "03-30",
            card_id=a["visa"],
            funding_id=a["chase"],
            amount_minor=5000,
        )
        s.commit()

        for name in person:
            for sub, prefix in ((Sub.receivable, "recv"), (Sub.payable, "pay")):
                q = select(Account.id).where(
                    Account.counterparty_id == person[name], Account.subtype == sub
                )
                found = s.scalars(q).one_or_none()
                if found is not None:
                    acct[f"{prefix}:{name}"] = found
        yield Month(s, uid, acct, person, cat, g)
        s.rollback()


@pytest.fixture
def month(engine: Engine) -> Iterator[Month]:
    yield from build_month(engine)


END = d("03-31")


def raw(m: Month, as_of: date) -> dict[str, int]:
    """Raw balance of every named account, by its §D name."""
    got = figures.balances(m.s, m.uid, as_of)
    return {name: got[i] for name, i in m.acct.items()}


# --- D.1, D.2 --------------------------------------------------------------------------------


def test_d1_balances_at_month_end(month: Month) -> None:
    assert raw(month, END) == {
        "chase": 220430,
        "wallet": 1700,
        "recv:Tom": 0,
        "recv:Mia": 2000,
        "recv:Raj": 2000,
        "amex": -11000,
        "visa": -99,
        "pay:Mia": -2000,
        "world": -68031,
        "opening": -145000,
    }


def test_d1_balances_agree_with_balance_raw(month: Month) -> None:
    for name, account_id in month.acct.items():
        expected = ledger.balance_raw(month.s, month.uid, account_id, END)
        assert figures.balances(month.s, month.uid, END)[account_id] == expected, name


def test_d2_net_worth_both_forms(month: Month) -> None:
    assert figures.net_worth(month.s, month.uid, END) == 213031
    assert figures.net_worth_outside(month.s, month.uid, END) == 213031


def test_d2_net_worth_before_the_month(month: Month) -> None:
    assert figures.net_worth(month.s, month.uid, d("02-28")) == 145000
    assert figures.net_worth_outside(month.s, month.uid, d("02-28")) == 145000
    assert figures.net_worth(month.s, month.uid, d("02-27")) == 0


def test_d2_march_change_is_income_minus_spending(month: Month) -> None:
    change = figures.net_worth(month.s, month.uid, END) - figures.net_worth(
        month.s, month.uid, d("02-28")
    )
    totals = figures.category_totals(month.s, month.uid, start=d("03-01"), end=END)
    assert change == totals.income - totals.expense == 68031


# --- D.3 -------------------------------------------------------------------------------------


def test_d3_category_totals_for_march(month: Month) -> None:
    c = month.cat
    totals = figures.category_totals(month.s, month.uid, start=d("03-01"), end=END)
    assert totals.by_category == {
        c["Food"]: 16870,
        c["Transport"]: 3500,
        c["Subscriptions"]: 1599,
        c["Salary"]: 90000,
    }
    assert totals.expense == 21969
    assert totals.income == 90000


def test_d3_card_payments_are_not_spending(month: Month) -> None:
    totals = figures.category_totals(month.s, month.uid, start=d("03-01"), end=END)
    assert totals.expense != 21969 + 20000  # the double-count bug the design exists to prevent
    # Voiding both card payments changes balances but no category total.
    ledger.void(month.s, month.uid, month.g[19].id)
    ledger.void(month.s, month.uid, month.g[22].id)
    month.s.commit()
    assert figures.category_totals(month.s, month.uid, start=d("03-01"), end=END) == totals


def test_d3_first_half_of_march(month: Month) -> None:
    c = month.cat
    totals = figures.category_totals(month.s, month.uid, start=d("03-01"), end=d("03-15"))
    assert totals.by_category == {
        c["Food"]: 8850,
        c["Transport"]: 3500,
        c["Subscriptions"]: 1599,
        c["Salary"]: 90000,
    }
    assert totals.expense == 8850 + 3500 + 1599


def test_d3_range_is_inclusive_at_both_ends(month: Month) -> None:
    food = month.cat["Food"]
    one_day = figures.category_totals(month.s, month.uid, start=d("03-03"), end=d("03-03"))
    assert one_day.by_category == {food: 4250}
    assert figures.category_totals(
        month.s, month.uid, start=d("03-17"), end=d("03-18")
    ).by_category == {food: -500}  # a refund alone is a negative spend


def test_d3_backwards_range_is_rejected(month: Month) -> None:
    with pytest.raises(RuleViolation) as e:
        figures.category_totals(month.s, month.uid, start=d("03-31"), end=d("03-01"))
    assert e.value.rule == "period"


# --- D.4 -------------------------------------------------------------------------------------


def test_d4_credit(month: Month) -> None:
    cards, total = figures.credit(month.s, month.uid, END)
    assert cards == {
        month.acct["amex"]: Credit(
            limit_minor=500000, owed=11000, available=489000, utilization_bps=220
        ),
        month.acct["visa"]: Credit(
            limit_minor=200000, owed=99, available=199901, utilization_bps=5
        ),
    }
    assert total == Credit(limit_minor=700000, owed=11099, available=688901, utilization_bps=159)


# --- D.5 -------------------------------------------------------------------------------------


def test_d5_friend_positions(month: Month) -> None:
    p = month.person
    assert figures.friend_positions(month.s, month.uid, END) == {
        p["Raj"]: 2000,
        p["Mia"]: 0,
        p["Tom"]: 0,
    }


# --- D.6 -------------------------------------------------------------------------------------


def test_d6_as_of_excludes_later_transactions(month: Month) -> None:
    got = raw(month, d("03-10"))
    assert {k: got[k] for k in ("chase", "wallet", "recv:Tom", "recv:Mia", "recv:Raj")} == {
        "chase": 148750,
        "wallet": 6400,
        "recv:Tom": 0,
        "recv:Mia": 2000,
        "recv:Raj": 5000,
    }
    assert (-got["amex"], -got["visa"], -got["pay:Mia"]) == (26000, 5099, 0)
    assert figures.net_worth(month.s, month.uid, d("03-10")) == 131051
    assert figures.net_worth_outside(month.s, month.uid, d("03-10")) == 131051


# --- D.7 -------------------------------------------------------------------------------------


def test_d7_void_check(month: Month) -> None:
    m = month
    with pytest.raises(RuleViolation):
        ledger.void(m.s, m.uid, m.g[16].id)  # R-10: G-17 is still live
    m.s.rollback()
    ledger.void(m.s, m.uid, m.g[17].id)
    ledger.void(m.s, m.uid, m.g[16].id)
    m.s.commit()
    assert raw(m, END)["chase"] == 225750
    assert figures.net_worth(m.s, m.uid, END) == 218351
    assert figures.net_worth_outside(m.s, m.uid, END) == 218351
    food = figures.category_totals(m.s, m.uid, start=d("03-01"), end=END).by_category
    assert food[m.cat["Food"]] == 11550


# --- §5 rules the month does not exercise ----------------------------------------------------


def test_utilization_rounds_half_up_in_integers() -> None:
    assert figures.utilization_bps(99, 200000) == 5  # 4.95
    assert figures.utilization_bps(11099, 700000) == 159  # 158.56
    assert figures.utilization_bps(1, 20000) == 1  # 0.5 exactly rounds up
    assert figures.utilization_bps(1, 20001) == 0  # just under 0.5
    assert figures.utilization_bps(0, 500000) == 0
    assert figures.utilization_bps(-5000, 500000) == 0  # a credit balance is not utilization
    assert figures.utilization_bps(700000, 500000) == 14000  # over the limit
    assert figures.utilization_bps(100, None) is None


def test_card_without_limit_has_no_utilization_and_is_left_out_of_the_aggregate(
    month: Month,
) -> None:
    m = month
    store = ledger.create_account(m.s, m.uid, name="Store card", subtype=Sub.credit_card).id
    ledger.spend(
        m.s,
        m.uid,
        funding_id=store,
        amount_minor=1234,
        category_id=m.cat["Food"],
        occurred_on=d("03-02"),
    )
    m.s.commit()
    cards, total = figures.credit(m.s, m.uid, END)
    assert cards[store] == Credit(limit_minor=None, owed=1234, available=None, utilization_bps=None)
    assert total == Credit(limit_minor=700000, owed=11099, available=688901, utilization_bps=159)


def test_card_credit_balance_gives_more_than_the_limit_and_does_not_offset_other_cards(
    month: Month,
) -> None:
    m = month
    # Overpay the Visa (owed 99) by 10000: it now holds a credit balance of 9901.
    ledger.card_payment(
        m.s,
        m.uid,
        card_id=m.acct["visa"],
        funding_id=m.acct["chase"],
        amount_minor=10000,
        occurred_on=d("03-31"),
    )
    m.s.commit()
    cards, total = figures.credit(m.s, m.uid, END)
    assert cards[m.acct["visa"]] == Credit(
        limit_minor=200000, owed=-9901, available=209901, utilization_bps=0
    )
    # Owed and available sum as they are; utilization counts only what is owed (11000 on Amex).
    assert total == Credit(limit_minor=700000, owed=1099, available=698901, utilization_bps=157)


def test_archived_card_is_left_out_of_credit(month: Month) -> None:
    m = month
    old = ledger.create_account(
        m.s, m.uid, name="Old card", subtype=Sub.credit_card, meta={"limit_minor": 100000}
    ).id
    ledger.archive_account(m.s, m.uid, old)
    m.s.commit()
    cards, total = figures.credit(m.s, m.uid, END)
    assert old not in cards
    assert total.limit_minor == 700000


def test_child_category_rolls_up_into_its_parent(month: Month) -> None:
    m = month
    food = m.cat["Food"]
    groceries = Category(user_id=m.uid, name="Groceries", kind=CategoryKind.expense, parent_id=food)
    m.s.add(groceries)
    m.s.flush()
    ledger.spend(
        m.s,
        m.uid,
        funding_id=m.acct["chase"],
        amount_minor=1000,
        category_id=groceries.id,
        occurred_on=d("04-02"),
    )
    ledger.spend(
        m.s,
        m.uid,
        funding_id=m.acct["chase"],
        amount_minor=300,
        category_id=food,
        occurred_on=d("04-03"),
    )
    m.s.commit()
    totals = figures.category_totals(m.s, m.uid, start=d("04-01"), end=d("04-30"))
    assert totals.by_category == {food: 1300, groceries.id: 1000}
    assert totals.expense == 1300  # the child is not counted twice


def test_archived_category_keeps_its_history(month: Month) -> None:
    m = month
    m.s.get_one(Category, m.cat["Subscriptions"]).is_archived = True
    m.s.commit()
    totals = figures.category_totals(m.s, m.uid, start=d("03-01"), end=END)
    assert totals.by_category[m.cat["Subscriptions"]] == 1599


def test_friend_with_no_accounts_has_position_zero(month: Month) -> None:
    m = month
    ana = ledger.create_counterparty(m.s, m.uid, name="Ana").id
    m.s.commit()
    assert figures.friend_positions(m.s, m.uid, END)[ana] == 0


def test_bad_as_of_is_rejected(month: Month) -> None:
    for bad in (datetime(2026, 3, 31, 12), "2026-03-31"):
        with pytest.raises(RuleViolation) as e:
            figures.net_worth(month.s, month.uid, bad)  # type: ignore[arg-type]
        assert e.value.rule == "as_of"


# --- Default as_of: today in the user's timezone (D-013) -------------------------------------


def test_today_is_in_the_users_timezone(engine: Engine) -> None:
    # UTC+14 and UTC-11 are 25 hours apart, so their calendar dates always differ.
    with Session(engine) as s:
        east = provision_user(s, f"tz|{uuid.uuid4()}", "East", "Pacific/Kiritimati").id
        west = provision_user(s, f"tz|{uuid.uuid4()}", "West", "Pacific/Pago_Pago").id
        s.commit()
        assert figures.today(s, east) == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
        assert figures.today(s, west) == datetime.now(ZoneInfo("Pacific/Pago_Pago")).date()
        assert figures.today(s, east) != figures.today(s, west)


def test_figures_default_to_today_and_exclude_future_dates(month: Month) -> None:
    m = month
    tomorrow = figures.today(m.s, m.uid) + timedelta(days=1)
    ledger.spend(
        m.s,
        m.uid,
        funding_id=m.acct["chase"],
        amount_minor=777,
        category_id=m.cat["Food"],
        occurred_on=tomorrow,
    )
    m.s.commit()
    assert figures.net_worth(m.s, m.uid) == 213031
    assert figures.net_worth_outside(m.s, m.uid) == 213031
    assert figures.balances(m.s, m.uid)[m.acct["chase"]] == 220430
    assert figures.net_worth(m.s, m.uid, tomorrow) == 213031 - 777


# --- T-01 ------------------------------------------------------------------------------------


def test_t01_two_users_with_the_same_month_see_the_same_figures(engine: Engine) -> None:
    first, second = build_month(engine), build_month(engine)
    a, b = next(first), next(second)  # b is built while a's rows are already committed

    def everything(m: Month) -> tuple[object, ...]:
        names = {i: n for n, i in m.acct.items()}
        people = {i: n for n, i in m.person.items()}
        cats = {i: n for n, i in m.cat.items()}
        totals = figures.category_totals(m.s, m.uid, start=d("03-01"), end=END)
        cards, total = figures.credit(m.s, m.uid, END)
        return (
            {names[i]: n for i, n in figures.balances(m.s, m.uid, END).items() if i in names},
            figures.net_worth(m.s, m.uid, END),
            figures.net_worth_outside(m.s, m.uid, END),
            {cats[i]: n for i, n in totals.by_category.items()},
            (totals.expense, totals.income),
            {names[i]: c for i, c in cards.items()},
            total,
            {people[i]: n for i, n in figures.friend_positions(m.s, m.uid, END).items()},
        )

    assert everything(a) == everything(b)
    assert figures.net_worth(a.s, a.uid, END) == 213031
    first.close()
    second.close()
