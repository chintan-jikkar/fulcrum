"""Card details the user sets up: due and statement days, last four digits, the card's design.

Never the full card number or the security code: Parity does not store them (D-071)."""

from datetime import date

import pytest

from app.services.figures import next_due
from tests.test_api import Caller


@pytest.mark.parametrize(
    ("today", "due_day", "want"),
    [
        (date(2026, 11, 10), 15, date(2026, 11, 15)),  # later this month
        (date(2026, 11, 15), 15, date(2026, 11, 15)),  # today counts
        (date(2026, 11, 16), 15, date(2026, 12, 15)),  # passed: next month
        (date(2026, 12, 20), 5, date(2027, 1, 5)),  # over the year end
        (date(2026, 2, 10), 31, date(2026, 2, 28)),  # a short month uses its last day
        (date(2026, 1, 31), 30, date(2026, 2, 28)),  # passed, and next month is short too
    ],
)
def test_next_due(today: date, due_day: int, want: date) -> None:
    assert next_due(today, due_day) == want


def test_a_card_keeps_its_details_and_shows_the_next_due_date(me: Caller) -> None:
    card = me.post(
        "/accounts",
        name="Juniper Card",
        subtype="credit_card",
        limit_minor=500000,
        due_day=28,
        statement_day=3,
        last4="4242",
        card_design="aurora",
    )

    assert card["last4"] == "4242"
    credit = card["credit"]
    assert (credit["due_day"], credit["statement_day"], credit["design"]) == (28, 3, "aurora")
    assert credit["next_due_on"] >= me.get("/summary")["as_of"]
    assert 0 <= credit["days_until_due"] <= 31

    edited = me.post_raw(f"/accounts/{card['id']}", due_day=1, last4="0005")
    assert edited.status_code == 200, edited.text
    assert edited.json()["credit"]["due_day"] == 1
    assert edited.json()["last4"] == "0005"
    assert edited.json()["credit"]["statement_day"] == 3  # untouched fields stay
    assert edited.json()["credit"]["design"] == "aurora"


def test_a_card_without_details_has_none(me: Caller) -> None:
    card = me.post("/accounts", name="Plain", subtype="credit_card")

    assert card["last4"] is None
    assert card["credit"]["next_due_on"] is None
    assert card["credit"]["days_until_due"] is None
    assert card["credit"]["design"] is None


def test_a_bank_may_have_last4_but_no_card_fields(me: Caller) -> None:
    bank = me.post("/accounts", name="Harbor", subtype="bank", last4="9876")
    assert bank["last4"] == "9876"

    cases = {
        "due day on a bank": me.post_raw(f"/accounts/{bank['id']}", due_day=5),
        "design on a bank": me.post_raw(f"/accounts/{bank['id']}", card_design="aurora"),
    }
    assert {k: (r.status_code, r.json()["code"]) for k, r in cases.items()} == {
        k: (422, "account") for k in cases
    }


@pytest.mark.parametrize(
    "bad",
    [
        {"due_day": 0},
        {"due_day": 32},
        {"statement_day": -1},
        {"last4": "123"},
        {"last4": "12345"},
        {"last4": "12a4"},
        {"last4": "4111111111111111"},  # a full number is refused, never stored
        {"card_design": "not-a-design"},
        {"card_design": "#12345"},
    ],
)
def test_bad_card_details_are_refused(me: Caller, bad: dict[str, object]) -> None:
    r = me.post_raw("/accounts", name="Card", subtype="credit_card", **bad)

    assert r.status_code == 422, r.text
    assert all(a["name"] != "Card" for a in me.get("/accounts"))


def test_the_api_has_no_field_for_a_full_number_or_security_code(me: Caller) -> None:
    for field in ("number", "card_number", "pan", "cvv", "cvc", "security_code"):
        r = me.post_raw("/accounts", name="Card", subtype="credit_card", **{field: "x"})
        assert r.status_code == 422, field  # extra fields are forbidden, so nothing slips in


def test_transaction_rows_show_which_card_design_paid(me: Caller) -> None:
    card = me.post("/accounts", name="Card", subtype="credit_card", card_design="sunset")
    me.txn("spend", 1200, funding_id=card["id"], category_id=me.cat["Food"])

    legs = me.get("/transactions")[0]["legs"]

    assert {leg["account_name"]: leg["card_design"] for leg in legs}["Card"] == "sunset"
    assert all(leg["card_design"] is None for leg in legs if leg["account_name"] != "Card")


def test_every_design_name_is_accepted(me: Caller) -> None:
    from app.services.ledger import CARD_DESIGNS

    card = me.post("/accounts", name="Card", subtype="credit_card")["id"]
    for design in sorted(CARD_DESIGNS):
        r = me.post_raw(f"/accounts/{card}", card_design=design)
        assert r.status_code == 200, design
