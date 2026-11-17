"""Category management (P3, §3.4, D-080).

Categories are labels outside the ledger: renaming or moving one never touches a posting, and
archiving one only stops it being picked (I8). Its kind is fixed once made, because the
transactions already on it were checked against that kind. One level of nesting, parent and
child of the same kind."""

from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.test_api import Caller


def _cat(me: Caller, name: str) -> dict[str, Any]:
    return next(c for c in me.get("/categories") if c["name"] == name)


def test_add_a_category_and_a_subcategory(me: Caller) -> None:
    pets = me.post("/categories", name="Pets", kind="expense")
    vet = me.post("/categories", name="Vet", kind="expense", parent_id=pets["id"])

    assert (pets["kind"], pets["parent_id"], pets["is_archived"]) == ("expense", None, False)
    assert vet["parent_id"] == pets["id"]
    assert _cat(me, "Vet") == vet


def test_spending_in_a_subcategory_rolls_up_to_its_parent(me: Caller) -> None:
    wallet = me.account("Wallet", "cash", opening=10000)
    pets = me.post("/categories", name="Pets", kind="expense")
    vet = me.post("/categories", name="Vet", kind="expense", parent_id=pets["id"])

    me.txn("spend", 4500, funding_id=wallet, category_id=vet["id"])

    totals = {c["name"]: c["total"]["minor"] for c in me.get("/summary")["month"]["categories"]}
    assert totals["Pets"] == 4500


def test_rename_keeps_the_transactions_on_it(me: Caller) -> None:
    wallet = me.account("Wallet", "cash", opening=10000)
    me.txn("spend", 1200, funding_id=wallet, category_id=me.cat["Food"])

    r = me.post_raw(f"/categories/{me.cat['Food']}", name="Groceries")

    assert r.status_code == 200, r.text
    assert me.get("/transactions")[0]["category"] == {"id": me.cat["Food"], "name": "Groceries"}


def test_move_under_a_parent_and_back_to_the_top(me: Caller) -> None:
    pets = me.post("/categories", name="Pets", kind="expense")
    food = me.cat["Food"]

    moved = me.post_raw(f"/categories/{food}", parent_id=pets["id"]).json()
    assert moved["parent_id"] == pets["id"]

    top = me.post_raw(f"/categories/{food}", parent_id=None).json()
    assert top["parent_id"] is None


def test_archive_stops_new_use_but_keeps_history(me: Caller) -> None:
    wallet = me.account("Wallet", "cash", opening=10000)
    me.txn("spend", 1200, funding_id=wallet, category_id=me.cat["Food"])

    archived = me.post_raw(f"/categories/{me.cat['Food']}/archive")
    assert archived.json()["is_archived"] is True

    refused = me.post_raw(
        "/transactions/spend",
        amount_minor=100,
        funding_id=wallet,
        category_id=me.cat["Food"],
        occurred_on=me.today.isoformat(),
    )
    assert (refused.status_code, refused.json()["code"]) == (422, "I8")
    assert me.get("/transactions")[0]["category"]["name"] == "Food"  # history stays

    back = me.post_raw(f"/categories/{me.cat['Food']}/unarchive")
    assert back.json()["is_archived"] is False


def test_archiving_a_parent_archives_its_subcategories(me: Caller) -> None:
    pets = me.post("/categories", name="Pets", kind="expense")
    me.post("/categories", name="Vet", kind="expense", parent_id=pets["id"])

    me.post_raw(f"/categories/{pets['id']}/archive")

    assert _cat(me, "Vet")["is_archived"] is True


def test_a_subcategory_of_an_archived_parent_cannot_come_back_alone(me: Caller) -> None:
    pets = me.post("/categories", name="Pets", kind="expense")
    vet = me.post("/categories", name="Vet", kind="expense", parent_id=pets["id"])
    me.post_raw(f"/categories/{pets['id']}/archive")

    r = me.post_raw(f"/categories/{vet['id']}/unarchive")

    assert (r.status_code, r.json()["code"]) == (422, "category")


@pytest.mark.parametrize(
    "case",
    [
        "empty name",
        "same name same kind",
        "parent of other kind",
        "grandchild",
        "parent with children moved under another",
        "own parent",
        "archived parent",
        "kind change",
        "bad kind",
    ],
)
def test_bad_category_changes_are_refused(me: Caller, case: str) -> None:
    pets = me.post("/categories", name="Pets", kind="expense")
    vet = me.post("/categories", name="Vet", kind="expense", parent_id=pets["id"])
    before = me.get("/categories")

    match case:
        case "empty name":
            r = me.post_raw("/categories", name="  ", kind="expense")
        case "same name same kind":
            r = me.post_raw("/categories", name="food", kind="expense")  # Food exists
        case "parent of other kind":
            r = me.post_raw("/categories", name="Tips", kind="income", parent_id=pets["id"])
        case "grandchild":
            r = me.post_raw("/categories", name="Shots", kind="expense", parent_id=vet["id"])
        case "parent with children moved under another":
            r = me.post_raw(f"/categories/{pets['id']}", parent_id=me.cat["Food"])
        case "own parent":
            r = me.post_raw(f"/categories/{me.cat['Food']}", parent_id=me.cat["Food"])
        case "archived parent":
            me.post_raw(f"/categories/{me.cat['Health']}/archive")
            before = me.get("/categories")
            r = me.post_raw("/categories", name="Gym", kind="expense", parent_id=me.cat["Health"])
        case "kind change":
            r = me.post_raw(f"/categories/{me.cat['Food']}", kind="income")
        case "bad kind":
            r = me.post_raw("/categories", name="X", kind="transfer")

    assert r.status_code == 422, r.text
    assert me.get("/categories") == before


def test_the_same_name_is_fine_for_the_other_kind(me: Caller) -> None:
    # Gifts given (expense) and gifts received (income) can share a name.
    r = me.post_raw("/categories", name="Gifts", kind="income")
    r2 = me.post_raw("/categories", name="Gifts", kind="expense")

    assert (r.status_code, r2.status_code) == (201, 201)


def test_another_tenants_category_is_404(me: Caller, api: TestClient, engine: Engine) -> None:
    them = Caller(api, engine)
    theirs = them.cat["Food"]

    assert me.post_raw(f"/categories/{theirs}", name="Mine now").status_code == 404
    assert me.post_raw(f"/categories/{theirs}/archive").status_code == 404
    as_parent = me.post_raw("/categories", name="X", kind="expense", parent_id=theirs)
    assert as_parent.status_code == 404
    assert _cat(them, "Food")["is_archived"] is False
