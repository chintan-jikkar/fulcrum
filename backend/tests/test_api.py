"""The HTTP API the web app reads and writes (CLAUDE.md §4, §5, §6; D-058 to D-060).

One tenant runs the §4 worked examples through the routes, and every figure the screens show is
checked against a hand calculation. Idempotency has its own file.
"""

import uuid
from datetime import date
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.config import settings
from app.money import display, percent
from app.services import figures
from app.services.users import provision_user
from tests.test_idempotency import client_for


class Caller:
    """One tenant talking to the API, with a fresh Idempotency-Key on every POST."""

    def __init__(self, api: TestClient, engine: Engine) -> None:
        self.api = api
        with Session(engine) as s:
            self.uid = provision_user(s, f"api|{uuid.uuid4()}", "Api", "America/New_York").id
            s.commit()
            self.today = figures.today(s, self.uid)
        self.cat = {c["name"]: c["id"] for c in self.get("/categories")}

    def get(self, path: str) -> Any:
        r = self.api.get(path, headers={"X-Test-User": str(self.uid)})
        assert r.status_code == 200, r.text
        return r.json()

    def post_raw(self, path: str, **body: Any) -> httpx.Response:
        headers = {"X-Test-User": str(self.uid), "Idempotency-Key": str(uuid.uuid4())}
        response: httpx.Response = self.api.post(path, json=body, headers=headers)
        return response

    def post(self, path: str, **body: Any) -> Any:
        r = self.post_raw(path, **body)
        assert r.status_code == 201, r.text
        return r.json()

    def txn(self, template: str, amount: int, **body: Any) -> Any:
        return self.post(
            f"/transactions/{template}",
            amount_minor=amount,
            occurred_on=self.today.isoformat(),
            **body,
        )

    def account(self, name: str, subtype: str, opening: int = 0, **extra: Any) -> str:
        account_id: str = self.post("/accounts", name=name, subtype=subtype, **extra)["id"]
        if opening:
            self.txn("opening", opening, account_id=account_id)
        return account_id


@pytest.mark.parametrize(
    ("minor", "want"),
    [
        (0, "$0.00"),
        (5, "$0.05"),
        (4000, "$40.00"),
        (123456, "$1,234.56"),
        (100000000, "$1,000,000.00"),
        (-4000, "-$40.00"),
        (-5, "-$0.05"),
    ],
)
def test_display(minor: int, want: str) -> None:
    assert display(minor) == want


@pytest.mark.parametrize(
    ("bps", "want"), [(0, "0.00%"), (20, "0.20%"), (3050, "30.50%"), (10000, "100.00%")]
)
def test_percent(bps: int, want: str) -> None:
    assert percent(bps) == want


def test_every_template_over_http_gives_the_hand_calculated_figures(me: Caller) -> None:
    chase = me.account("Chase", "bank", opening=150000)
    wallet = me.account("Wallet", "cash", opening=40000)
    amex = me.account("Amex", "credit_card", limit_minor=500000)
    raj = me.post("/counterparties", name="Raj")["id"]
    food, salary = me.cat["Food"], me.cat["Salary"]

    me.txn("spend", 4000, funding_id=chase, category_id=food)
    me.txn("spend", 4000, funding_id=amex, category_id=food)
    me.txn("card_payment", 2000, card_id=amex, funding_id=chase)
    me.txn("lend", 5000, counterparty_id=raj, funding_id=wallet, method="cash")
    me.txn("friend_repay", 3000, counterparty_id=raj, funding_id=chase, method="bank_transfer")
    me.txn("income", 60000, dest_id=chase, category_id=salary)
    me.txn("transfer", 30000, from_id=wallet, to_id=chase)
    me.txn("refund", 1000, funding_id=amex, category_id=food)
    me.txn("borrow", 2500, counterparty_id=raj, dest_id=wallet)
    me.txn("repay_friend", 1500, counterparty_id=raj, funding_id=wallet)
    me.txn("spend", 1000, funding_id=wallet, category_id=me.cat["Transport"])

    # chase 150000 - 4000 - 2000 + 3000 + 60000 + 30000
    # wallet 40000 - 5000 - 30000 + 2500 - 1500 - 1000
    # amex owed 4000 - 2000 - 1000; Raj owes 5000 - 3000; I owe Raj 2500 - 1500
    accounts = {a["name"]: a for a in me.get("/accounts")}
    assert {n: a["balance"]["minor"] for n, a in accounts.items()} == {
        "Chase": 237000,
        "Wallet": 5000,
        "Amex": 1000,
        "Raj owes me": 2000,
        "I owe Raj": 1000,
    }
    assert accounts["Chase"]["balance"]["display"] == "$2,370.00"
    assert accounts["Chase"]["credit"] is None
    assert accounts["Amex"]["kind"] == "LIABILITY"
    assert accounts["Amex"]["credit"] == {
        "limit": {"minor": 500000, "display": "$5,000.00"},
        "available": {"minor": 499000, "display": "$4,990.00"},
        "utilization_bps": 20,
        "utilization_display": "0.20%",
    }

    s = me.get("/summary")
    assert s["as_of"] == me.today.isoformat()
    # 237000 + 5000 + 2000 - 1000 - 1000
    assert s["net_worth"] == {"minor": 242000, "display": "$2,420.00"}
    assert s["credit"]["owed"]["minor"] == 1000
    assert s["credit"]["utilization_bps"] == 20
    assert s["credit"]["utilization_display"] == "0.20%"
    assert s["month"]["start"] == me.today.replace(day=1).isoformat()
    assert s["month"]["expense"]["minor"] == 8000  # 4000 + 4000 - 1000 refund + 1000
    assert s["month"]["income"]["minor"] == 60000
    # share_bps is the share of that kind's month total: 7000/8000, 1000/8000, 60000/60000.
    assert [(c["name"], c["total"]["minor"], c["share_bps"]) for c in s["month"]["categories"]] == [
        ("Salary", 60000, 10000),
        ("Food", 7000, 8750),
        ("Transport", 1000, 1250),
    ]
    ten = {"minor": 1000, "display": "$10.00"}
    assert s["friends"] == [{"counterparty_id": raj, "name": "Raj", "position": ten, "amount": ten}]


def test_what_you_owe_a_friend_is_negative_with_a_positive_amount(me: Caller) -> None:
    wallet = me.account("Wallet", "cash")
    raj = me.post("/counterparties", name="Raj")["id"]
    me.txn("borrow", 2500, counterparty_id=raj, dest_id=wallet)

    (friend,) = me.get("/summary")["friends"]

    assert friend["position"] == {"minor": -2500, "display": "-$25.00"}
    assert friend["amount"] == {"minor": 2500, "display": "$25.00"}


def test_transaction_list_shows_amount_effect_and_void(me: Caller) -> None:
    chase = me.account("Chase", "bank", opening=150000)
    wallet = me.account("Wallet", "cash")
    spend = me.txn("spend", 4000, funding_id=chase, category_id=me.cat["Food"], memo="Groceries")
    me.txn("transfer", 2500, from_id=chase, to_id=wallet)
    r = me.post_raw(f"/transactions/{spend['id']}/void")
    assert r.status_code == 200

    rows = me.get("/transactions")

    assert [r["template"] for r in rows] == ["transfer", "spend", "opening"]  # newest first
    transfer, spent, opening = rows
    assert spent["id"] == spend["id"]
    assert spent["memo"] == "Groceries"
    assert spent["amount"] == {"minor": 4000, "display": "$40.00"}
    assert spent["net"] == {"minor": -4000, "display": "-$40.00"}  # effect on net worth
    assert spent["category"] == {"id": me.cat["Food"], "name": "Food"}
    assert spent["voided_at"] is not None
    assert {(leg["account_name"], leg["amount"]["minor"]) for leg in spent["legs"]} == {
        ("World", 4000),
        ("Chase", -4000),
    }
    assert transfer["net"]["minor"] == 0
    assert transfer["category"] is None
    assert transfer["voided_at"] is None
    assert opening["net"]["minor"] == 150000


def test_t02_another_tenants_ids_are_404_and_lists_are_private(
    api: TestClient, engine: Engine
) -> None:
    a, b = Caller(api, engine), Caller(api, engine)
    theirs = b.account("Chase", "bank", opening=150000)
    b.post("/counterparties", name="Raj")

    r = a.post_raw(
        "/transactions/spend",
        funding_id=theirs,
        amount_minor=4000,
        category_id=a.cat["Food"],
        occurred_on=a.today.isoformat(),
    )

    assert r.status_code == 404
    assert r.json()["code"] == "not_found"
    assert a.get("/accounts") == []
    assert a.get("/transactions") == []
    assert a.get("/counterparties") == []
    assert a.get("/summary")["net_worth"]["minor"] == 0
    assert b.get("/summary")["net_worth"]["minor"] == 150000


def test_rejections_carry_the_rule_as_code(me: Caller) -> None:
    chase = me.account("Chase", "bank")
    amex = me.account("Amex", "credit_card")
    me.post("/counterparties", name="Raj")

    cases = {
        "I3": me.post_raw(
            "/transactions/transfer",
            from_id=chase,
            to_id=chase,
            amount_minor=100,
            occurred_on=me.today.isoformat(),
        ),
        "template": me.post_raw(  # R-07: a card is not a transfer target
            "/transactions/transfer",
            from_id=chase,
            to_id=amex,
            amount_minor=100,
            occurred_on=me.today.isoformat(),
        ),
        "account": me.post_raw("/accounts", name="Raj owes me", subtype="receivable"),
    }
    assert {code: (r.status_code, r.json()["code"]) for code, r in cases.items()} == {
        code: (422, code) for code in cases
    }
    assert me.post_raw("/counterparties", name="raj").status_code == 409  # same name, any case
    assert me.get("/transactions") == []


def test_a_float_amount_is_rejected(me: Caller) -> None:
    chase = me.account("Chase", "bank")

    r = me.post_raw(
        "/transactions/spend",
        funding_id=chase,
        amount_minor=40.0,
        category_id=me.cat["Food"],
        occurred_on=me.today.isoformat(),
    )

    assert r.status_code == 422
    assert me.get("/transactions") == []


def test_reads_need_a_caller(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "dev_auth_sub", None)
    with client_for(engine, fake_auth=False) as real:
        for path in ("/accounts", "/summary", "/transactions", "/categories", "/counterparties"):
            assert real.get(path).status_code == 401, path


def test_dev_sign_in_provisions_one_user(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    sub = f"dev|{uuid.uuid4()}"
    monkeypatch.setattr(settings, "dev_auth_sub", sub)
    with client_for(engine, fake_auth=False) as real:
        first = real.get("/categories")
        second = real.get("/categories")

    assert first.status_code == 200
    assert "Food" in {c["name"] for c in first.json()}
    assert second.json() == first.json()
    with engine.connect() as c:
        count = c.execute(text("SELECT count(*) FROM users WHERE auth_sub = :s"), {"s": sub})
        assert count.scalar_one() == 1


def test_month_bounds() -> None:
    from app.routers.book import month_bounds

    assert month_bounds(date(2026, 2, 14)) == (date(2026, 2, 1), date(2026, 2, 28))
    assert month_bounds(date(2028, 2, 29)) == (date(2028, 2, 1), date(2028, 2, 29))
    assert month_bounds(date(2026, 12, 31)) == (date(2026, 12, 1), date(2026, 12, 31))


def test_brands_on_accounts_rows_and_the_month(me: Caller) -> None:
    chase = me.account("Chase Checking", "bank", opening=100000)
    me.account("Harbor Savings", "bank")
    food, subs = me.cat["Food"], me.cat["Subscriptions"]
    me.txn("spend", 4000, funding_id=chase, category_id=food, memo="Trader Joe's")
    me.txn("spend", 2500, funding_id=chase, category_id=food, memo="TRADER JOES #552")
    me.txn("refund", 500, funding_id=chase, category_id=food, memo="Trader Joe's return")
    me.txn("spend", 1549, funding_id=chase, category_id=subs, memo="Netflix")
    me.txn("spend", 900, funding_id=chase, category_id=food, memo="Bagels")
    voided = me.txn("spend", 7000, funding_id=chase, category_id=food, memo="Netflix")
    me.post_raw(f"/transactions/{voided['id']}/void")

    accounts = {a["name"]: a["brand"] for a in me.get("/accounts")}
    assert accounts["Chase Checking"] == {
        "key": "chase",
        "name": "Chase",
        "color": "#117aca",
        "mark": "C",
    }
    assert accounts["Harbor Savings"] is None

    rows = {r["memo"]: r["brand"] for r in me.get("/transactions")}
    assert rows["TRADER JOES #552"]["key"] == "traderjoes"
    assert rows["Bagels"] is None

    # 4000 + 2500 - 500 refund; Netflix 1549, the voided one left out; Bagels has no brand.
    merchants = me.get("/summary")["month"]["merchants"]
    assert [(m["key"], m["total"]["minor"], m["count"]) for m in merchants] == [
        ("traderjoes", 6000, 3),
        ("netflix", 1549, 1),
    ]
