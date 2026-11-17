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


# --- The issuing bank: picked by the user when the card's name does not say it (D-077) -------


def test_the_issuer_names_the_card_when_its_name_does_not(me: Caller) -> None:
    card = me.post(
        "/accounts", name="Unlimited Cash Rewards", subtype="credit_card", issuer="bankofamerica"
    )

    assert card["brand"]["key"] == "bankofamerica"


def test_a_picked_issuer_wins_over_the_name(me: Caller) -> None:
    card = me.account("Freedom", "credit_card")  # "freedom" alone reads as Chase
    assert next(a for a in me.get("/accounts") if a["id"] == card)["brand"]["key"] == "chase"

    edited = me.post_raw(f"/accounts/{card}", issuer="bankofamerica")

    assert edited.status_code == 200, edited.text
    assert edited.json()["brand"]["key"] == "bankofamerica"


def test_issuer_must_be_a_bank_and_not_on_cash(me: Caller) -> None:
    wallet = me.account("Wallet", "cash")
    card = me.account("Card", "credit_card")
    bank = me.account("Checking", "bank")

    cases = {
        "a merchant": me.post_raw(f"/accounts/{card}", issuer="netflix"),
        "a network": me.post_raw(f"/accounts/{card}", issuer="visa"),
        "made up": me.post_raw(f"/accounts/{card}", issuer="nope"),
        "on cash": me.post_raw(f"/accounts/{wallet}", issuer="chase"),
    }
    assert {k: (r.status_code, r.json()["code"]) for k, r in cases.items()} == {
        k: (422, "account") for k in cases
    }
    # A bank account may name its bank too.
    assert me.post_raw(f"/accounts/{bank}", issuer="td").json()["brand"]["key"] == "td"


def test_the_issuer_list_is_banks_only(me: Caller) -> None:
    issuers = me.get("/brands/issuers")

    keys = [b["key"] for b in issuers]
    assert "chase" in keys and "bankofamerica" in keys
    assert "visa" not in keys and "netflix" not in keys
    assert set(issuers[0]) == {"key", "name", "color", "mark"}
