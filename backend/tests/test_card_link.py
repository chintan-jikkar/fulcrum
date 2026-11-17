"""A card is tied to the bank account that pays it off (§3.3 linked_bank_id, D-075)."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.test_api import Caller


def test_a_card_can_be_tied_to_a_bank_when_added(me: Caller) -> None:
    bank = me.account("Harbor Checking", "bank", opening=100000)

    card = me.post("/accounts", name="Card", subtype="credit_card", linked_bank_id=bank)

    assert card["credit"]["linked_bank_id"] == bank
    assert card["credit"]["linked_bank_name"] == "Harbor Checking"
    listed = next(a for a in me.get("/accounts") if a["id"] == card["id"])
    assert listed["credit"]["linked_bank_id"] == bank


def test_the_paying_bank_can_be_changed_later(me: Caller) -> None:
    first = me.account("First", "bank")
    second = me.account("Second", "bank")
    card = me.post("/accounts", name="Card", subtype="credit_card", linked_bank_id=first)

    moved = me.post_raw(f"/accounts/{card['id']}", linked_bank_id=second)

    assert moved.status_code == 200, moved.text
    assert moved.json()["credit"]["linked_bank_name"] == "Second"


def test_an_unlinked_card_says_so(me: Caller) -> None:
    card = me.post("/accounts", name="Card", subtype="credit_card")

    assert card["credit"]["linked_bank_id"] is None
    assert card["credit"]["linked_bank_name"] is None


def test_only_a_bank_can_pay_a_card(me: Caller) -> None:
    wallet = me.account("Wallet", "cash")
    other_card = me.account("Other card", "credit_card")
    bank = me.account("Bank", "bank")
    card = me.account("Card", "credit_card")

    cases = {
        "cash": me.post_raw(f"/accounts/{card}", linked_bank_id=wallet),
        "another card": me.post_raw(f"/accounts/{card}", linked_bank_id=other_card),
        "itself": me.post_raw(f"/accounts/{card}", linked_bank_id=card),
        "on a bank": me.post_raw(f"/accounts/{bank}", linked_bank_id=bank),
    }

    assert {k: (r.status_code, r.json()["code"]) for k, r in cases.items()} == {
        k: (422, "account") for k in cases
    }


def test_another_tenants_bank_is_404(me: Caller, api: TestClient, engine: Engine) -> None:
    them = Caller(api, engine)
    their_bank = them.account("Theirs", "bank")
    card = me.account("Card", "credit_card")

    r = me.post_raw(f"/accounts/{card}", linked_bank_id=their_bank)
    added = me.post_raw("/accounts", name="New", subtype="credit_card", linked_bank_id=their_bank)

    assert r.status_code == 404
    assert added.status_code == 404
