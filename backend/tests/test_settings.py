"""The settings screen's routes: the profile, and editing, archiving and restoring accounts."""

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.test_api import Caller


def test_profile_reads_and_updates(me: Caller) -> None:
    assert me.get("/me") == {"display_name": "Api", "timezone": "America/New_York"}

    r = me.post_raw("/me", display_name="  Alex  ", timezone="Asia/Kolkata")

    assert r.status_code == 200, r.text
    assert r.json() == {"display_name": "Alex", "timezone": "Asia/Kolkata"}
    assert me.get("/me") == r.json()
    # "Today" now follows the new zone.
    assert me.get("/summary")["as_of"] is not None


def test_profile_rejects_a_bad_timezone_or_empty_name(me: Caller) -> None:
    bad_zone = me.post_raw("/me", timezone="Mars/Olympus")
    empty = me.post_raw("/me", display_name="   ")

    assert (bad_zone.status_code, bad_zone.json()["code"]) == (422, "timezone")
    assert (empty.status_code, empty.json()["code"]) == (422, "profile")
    assert me.get("/me")["display_name"] == "Api"


def test_rename_an_account_and_change_a_card_limit(me: Caller) -> None:
    chase = me.account("Chase", "bank", opening=1000)
    amex = me.account("Amex", "credit_card", limit_minor=500000)
    me.txn("spend", 100000, funding_id=amex, category_id=me.cat["Food"])

    renamed = me.post_raw(f"/accounts/{chase}", name="  Chase Checking ")
    limit = me.post_raw(f"/accounts/{amex}", limit_minor=200000)

    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["name"] == "Chase Checking"
    assert renamed.json()["balance"]["minor"] == 1000
    assert limit.status_code == 200, limit.text
    # 100000 owed of 200000
    assert limit.json()["credit"]["utilization_bps"] == 5000
    assert limit.json()["credit"]["available"]["minor"] == 100000


def test_account_edit_rejections(me: Caller) -> None:
    chase = me.account("Chase", "bank")
    raj = me.post("/counterparties", name="Raj")["id"]
    wallet = me.account("Wallet", "cash", opening=5000)
    me.txn("lend", 1000, counterparty_id=raj, funding_id=wallet, method="cash")
    person = next(a["id"] for a in me.get("/accounts") if a["name"] == "Raj owes me")

    cases = {
        "empty name": me.post_raw(f"/accounts/{chase}", name=" "),
        "limit on a bank": me.post_raw(f"/accounts/{chase}", limit_minor=1000),
        "zero limit": me.post_raw(f"/accounts/{chase}", limit_minor=0),
        "person account": me.post_raw(f"/accounts/{person}", name="Raj"),
    }

    assert {k: (r.status_code, r.json()["code"]) for k, r in cases.items()} == {
        k: (422, "account") for k in cases
    }


def test_archive_needs_a_zero_balance_and_restore_brings_it_back(me: Caller) -> None:
    wallet = me.account("Wallet", "cash", opening=5000)
    empty = me.account("Old card", "credit_card")

    refused = me.post_raw(f"/accounts/{wallet}/archive")
    archived = me.post_raw(f"/accounts/{empty}/archive")

    assert (refused.status_code, refused.json()["code"]) == (422, "I9")
    assert archived.status_code == 200, archived.text
    assert archived.json()["is_active"] is False
    restored = me.post_raw(f"/accounts/{empty}/unarchive")
    assert restored.json()["is_active"] is True


def test_another_tenants_account_is_404(api: TestClient, engine: Engine) -> None:
    a, b = Caller(api, engine), Caller(api, engine)
    theirs = b.account("Chase", "bank")

    for path, body in (
        (f"/accounts/{theirs}", {"name": "Mine"}),
        (f"/accounts/{theirs}/archive", {}),
        (f"/accounts/{theirs}/unarchive", {}),
    ):
        r = a.post_raw(path, **body)
        assert r.status_code == 404, path
    assert b.get("/accounts")[0]["name"] == "Chase"
