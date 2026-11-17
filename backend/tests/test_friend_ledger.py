"""The friends ledger: one person's transactions with a running position (§5, P3, D-076)."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine

from tests.test_api import Caller


def test_running_position_oldest_first_shown_newest_first(me: Caller) -> None:
    wallet = me.account("Wallet", "cash", opening=100000)
    bank = me.account("Bank", "bank", opening=100000)
    raj = me.post("/counterparties", name="Raj")["id"]
    day = me.today - timedelta(days=5)

    def txn(template: str, amount: int, n: int, **body: object) -> dict[str, str]:
        """A transaction n days after `day`, so the order is fixed."""
        on = (day + timedelta(days=n)).isoformat()
        out: dict[str, str] = me.post(
            f"/transactions/{template}", amount_minor=amount, occurred_on=on, **body
        )
        return out

    txn("lend", 5000, 0, counterparty_id=raj, funding_id=wallet, method="cash")
    gone = txn("lend", 900, 1, counterparty_id=raj, funding_id=wallet)
    me.post_raw(f"/transactions/{gone['id']}/void")
    txn("friend_repay", 2000, 2, counterparty_id=raj, funding_id=bank, method="bank_transfer")
    txn("borrow", 4000, 3, counterparty_id=raj, dest_id=bank, memo="Concert")

    ledger = me.get(f"/counterparties/{raj}/ledger")

    assert ledger["name"] == "Raj"
    assert ledger["position"]["minor"] == 5000 - 2000 - 4000  # you owe Raj $10
    rows = ledger["rows"]
    # Newest first, each with the change and where things stood after it.
    assert [
        (r["template"], r["change"]["minor"], r["position_after"]["minor"], r["voided"])
        for r in rows
    ] == [
        ("borrow", -4000, -1000, False),
        ("friend_repay", -2000, 3000, False),
        ("lend", 900, 5000, True),  # a void stays visible but moves nothing
        ("lend", 5000, 5000, False),
    ]
    assert [r["method"] for r in rows] == [None, "bank_transfer", None, "cash"]
    assert rows[0]["memo"] == "Concert"
    assert rows[0]["position_after"]["display"] == "-$10.00"


def test_a_new_person_has_an_empty_ledger(me: Caller) -> None:
    sam = me.post("/counterparties", name="Sam")["id"]

    ledger = me.get(f"/counterparties/{sam}/ledger")

    assert ledger["rows"] == []
    assert ledger["position"]["minor"] == 0


def test_someone_elses_person_is_404(me: Caller, api: TestClient, engine: Engine) -> None:
    them = Caller(api, engine)
    theirs = them.post("/counterparties", name="Raj")["id"]

    r = api.get(f"/counterparties/{theirs}/ledger", headers={"X-Test-User": str(me.uid)})
    missing = api.get(
        "/counterparties/00000000-0000-0000-0000-000000000000/ledger",
        headers={"X-Test-User": str(me.uid)},
    )

    assert r.status_code == 404
    assert missing.status_code == 404
