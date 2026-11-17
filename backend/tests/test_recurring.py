"""Subscriptions and other recurring charges (CLAUDE.md §12, D-079).

A rule proposes; it never posts by itself. A reminder shows from `remind_days` before the due
date. Confirming writes one spend and moves the rule to its next date; skipping only moves it;
cancelling stops it."""

from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.services.recurring import next_after
from tests.test_api import Caller


@pytest.mark.parametrize(
    ("due", "cadence", "anchor", "want"),
    [
        (date(2026, 1, 15), "monthly", 15, date(2026, 2, 15)),
        (date(2026, 1, 31), "monthly", 31, date(2026, 2, 28)),  # short month: its last day
        (date(2026, 2, 28), "monthly", 31, date(2026, 3, 31)),  # and back to the 31st after
        (date(2026, 12, 5), "monthly", 5, date(2027, 1, 5)),
        (date(2028, 2, 29), "yearly", 29, date(2029, 2, 28)),
        (date(2026, 11, 17), "yearly", 17, date(2027, 11, 17)),
        (date(2026, 11, 17), "weekly", 17, date(2026, 11, 24)),
    ],
)
def test_next_after(due: date, cadence: str, anchor: int, want: date) -> None:
    assert next_after(due, cadence, anchor) == want


def _netflix(me: Caller, card: str, due: date, **extra: object) -> dict[str, Any]:
    out: dict[str, Any] = me.post(
        "/recurring",
        name="Netflix",
        amount_minor=1549,
        funding_id=card,
        category_id=me.cat["Subscriptions"],
        cadence="monthly",
        next_due_on=due.isoformat(),
        **extra,
    )
    return out


def test_a_subscription_is_saved_with_its_reminder_window(me: Caller) -> None:
    card = me.account("Card", "credit_card")

    rule = _netflix(me, card, me.today + timedelta(days=2))

    assert rule["name"] == "Netflix"
    assert rule["amount"] == {"minor": 1549, "display": "$15.49"}
    assert rule["brand"]["key"] == "netflix"
    assert rule["funding_name"] == "Card"
    assert rule["cadence"] == "monthly"
    assert rule["remind_days"] == 2  # the default: two days before
    assert rule["days_until_due"] == 2
    assert rule["remind"] is True
    assert rule["is_active"] is True
    assert me.get("/recurring") == [rule]


def test_reminders_list_only_what_is_due_soon(me: Caller) -> None:
    card = me.account("Card", "credit_card")
    soon = _netflix(me, card, me.today + timedelta(days=1))
    _netflix(me, card, me.today + timedelta(days=10))  # not yet
    overdue = _netflix(me, card, me.today - timedelta(days=3))  # missed: still shown
    today = _netflix(me, card, me.today + timedelta(days=5), remind_days=7)  # longer window

    upcoming = me.get("/reminders/upcoming")

    # Soonest first.
    assert [r["id"] for r in upcoming] == [overdue["id"], soon["id"], today["id"]]


def test_confirm_writes_the_spend_and_moves_to_the_next_date(me: Caller) -> None:
    card = me.account("Card", "credit_card")
    due = me.today
    rule = _netflix(me, card, due)

    r = me.post_raw(f"/recurring/{rule['id']}/confirm")

    assert r.status_code == 200, r.text
    assert r.json()["next_due_on"] > due.isoformat()
    rows = me.get("/transactions")
    assert [(x["template"], x["memo"], x["amount"]["minor"], x["occurred_on"]) for x in rows] == [
        ("spend", "Netflix", 1549, due.isoformat())
    ]
    assert rows[0]["category"]["name"] == "Subscriptions"


def test_confirming_early_books_it_today_not_on_the_future_date(me: Caller) -> None:
    # "Paid" pressed two days early means the charge already happened: a future-dated spend
    # would not show on the card until then.
    card = me.account("Card", "credit_card")
    rule = _netflix(me, card, me.today + timedelta(days=2))

    me.post_raw(f"/recurring/{rule['id']}/confirm")

    assert me.get("/transactions")[0]["occurred_on"] == me.today.isoformat()


def test_confirm_can_take_the_actual_amount(me: Caller) -> None:
    card = me.account("Card", "credit_card")
    rule = _netflix(me, card, me.today)

    me.post_raw(f"/recurring/{rule['id']}/confirm", amount_minor=1799)

    assert me.get("/transactions")[0]["amount"]["minor"] == 1799
    assert me.get("/recurring")[0]["amount"]["minor"] == 1549  # the rule keeps its amount


def test_skip_moves_on_without_a_transaction(me: Caller) -> None:
    card = me.account("Card", "credit_card")
    rule = _netflix(me, card, me.today)

    r = me.post_raw(f"/recurring/{rule['id']}/skip")

    assert r.status_code == 200, r.text
    assert r.json()["next_due_on"] > me.today.isoformat()
    assert me.get("/transactions") == []


def test_cancel_stops_reminders_and_resume_brings_them_back(me: Caller) -> None:
    card = me.account("Card", "credit_card")
    rule = _netflix(me, card, me.today)

    cancelled = me.post_raw(f"/recurring/{rule['id']}/cancel")
    assert cancelled.json()["is_active"] is False
    assert me.get("/reminders/upcoming") == []
    refused = me.post_raw(f"/recurring/{rule['id']}/confirm")
    assert (refused.status_code, refused.json()["code"]) == (422, "recurring")

    resumed = me.post_raw(f"/recurring/{rule['id']}/resume")
    assert resumed.json()["is_active"] is True


def test_edit_a_subscription(me: Caller) -> None:
    card = me.account("Card", "credit_card")
    bank = me.account("Bank", "bank")
    rule = _netflix(me, card, me.today + timedelta(days=9))

    r = me.post_raw(
        f"/recurring/{rule['id']}",
        amount_minor=1999,
        funding_id=bank,
        next_due_on=(me.today + timedelta(days=1)).isoformat(),
        remind_days=1,
    )

    assert r.status_code == 200, r.text
    out = r.json()
    assert (out["amount"]["minor"], out["funding_name"], out["remind"]) == (1999, "Bank", True)


@pytest.mark.parametrize(
    "bad",
    [
        {"amount_minor": 0},
        {"name": "  "},
        {"cadence": "daily"},
        {"remind_days": 15},
        {"remind_days": -1},
        {"income_category": True},
        {"funding": "person"},
    ],
)
def test_bad_subscriptions_are_refused(me: Caller, bad: dict[str, object]) -> None:
    card = me.account("Card", "credit_card")
    body: dict[str, object] = {
        "name": "Netflix",
        "amount_minor": 1549,
        "funding_id": card,
        "category_id": me.cat["Subscriptions"],
        "cadence": "monthly",
        "next_due_on": me.today.isoformat(),
    }
    if bad.pop("income_category", False):
        body["category_id"] = me.cat["Salary"]
    if bad.pop("funding", None) == "person":
        sam = me.post("/counterparties", name="Sam")["id"]
        wallet = me.account("Wallet", "cash", opening=1000)
        me.txn("lend", 100, counterparty_id=sam, funding_id=wallet)
        body["funding_id"] = next(
            a["id"] for a in me.get("/accounts") if a["name"] == "Sam owes me"
        )
    body.update(bad)

    r = me.post_raw("/recurring", **body)

    assert r.status_code == 422, r.text
    assert me.get("/recurring") == []


def test_another_tenants_rule_and_accounts_are_404(
    me: Caller, api: TestClient, engine: Engine
) -> None:
    them = Caller(api, engine)
    their_card = them.account("Theirs", "credit_card")
    theirs = _netflix(them, their_card, them.today)
    my_card = me.account("Card", "credit_card")

    assert me.post_raw(f"/recurring/{theirs['id']}/confirm").status_code == 404
    assert me.post_raw(f"/recurring/{theirs['id']}", amount_minor=1).status_code == 404
    using_theirs = me.post_raw(
        "/recurring",
        name="X",
        amount_minor=100,
        funding_id=their_card,
        category_id=me.cat["Subscriptions"],
        cadence="monthly",
        next_due_on=me.today.isoformat(),
    )
    assert using_theirs.status_code == 404
    assert me.get("/recurring") == []
    assert my_card  # mine are untouched
