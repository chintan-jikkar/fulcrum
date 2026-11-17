"""Splitting a bill (D-078): your share is a spend, each friend's share a lend on the same
funding account (§4 notes). Shared items are split by units; the rest of the bill is yours."""

import pytest

from app.services.ledger import RuleViolation
from app.services.split import Item, allocate
from tests.test_api import Caller


def test_allocate_by_units_the_rest_of_the_bill_is_mine() -> None:
    # 12 cases of water for $30: 2 + 2 + 3 for friends, 5 for me; the rest of the $100 is mine.
    mine, theirs = allocate(10000, [Item(3000, my_units=5, units={"t": 2, "a": 2, "s": 3})])

    assert theirs == {"t": 500, "a": 500, "s": 750}
    assert mine == 10000 - 1750


def test_allocate_rounds_friends_down_and_the_payer_keeps_the_cents() -> None:
    mine, theirs = allocate(1000, [Item(1000, my_units=1, units={"a": 1, "b": 1})])

    assert theirs == {"a": 333, "b": 333}
    assert mine == 334
    assert mine + sum(theirs.values()) == 1000  # never a cent lost or made up


def test_allocate_adds_up_across_items() -> None:
    mine, theirs = allocate(
        5000,
        [Item(1200, my_units=0, units={"a": 1, "b": 1}), Item(900, my_units=1, units={"a": 2})],
    )

    assert theirs == {"a": 600 + 600, "b": 600}
    assert mine == 5000 - 1800


@pytest.mark.parametrize(
    ("total", "items"),
    [
        (1000, []),  # nobody to split with
        (1000, [Item(1000, my_units=1, units={})]),  # an item with no friend in it
        (1000, [Item(1200, my_units=1, units={"a": 1})]),  # items cost more than the bill
        (1000, [Item(0, my_units=1, units={"a": 1})]),
        (1000, [Item(500, my_units=1, units={"a": 0})]),
        (1000, [Item(500, my_units=-1, units={"a": 1})]),
        (0, [Item(0, my_units=1, units={"a": 1})]),
    ],
)
def test_allocate_refuses_what_cannot_be_split(total: int, items: list[Item]) -> None:
    with pytest.raises(RuleViolation):
        allocate(total, items)


# --- Over HTTP --------------------------------------------------------------------------------


def _setup(me: Caller) -> tuple[str, str, str, str]:
    card = me.account("Card", "credit_card", limit_minor=500000)
    t = me.post("/counterparties", name="Tara")["id"]
    a = me.post("/counterparties", name="Avi")["id"]
    return card, t, a, me.cat["Food"]


def _body(me: Caller, card: str, t: str, a: str, food: str, **extra: object) -> dict[str, object]:
    return {
        "amount_minor": 10000,
        "occurred_on": me.today.isoformat(),
        "memo": "Walmart groceries",
        "funding_id": card,
        "category_id": food,
        "items": [
            {"amount_minor": 3000, "my_units": 5, "units": [{"counterparty_id": t, "units": 2}]},
            {"amount_minor": 1000, "my_units": 0, "units": [{"counterparty_id": a, "units": 1}]},
        ],
        **extra,
    }


def test_preview_shows_the_shares_and_writes_nothing(me: Caller) -> None:
    card, t, a, food = _setup(me)

    r = me.post_raw("/transactions/split", **_body(me, card, t, a, food, preview=True))

    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mine"]["minor"] == 10000 - 857 - 1000
    assert [(s["name"], s["amount"]["minor"]) for s in out["shares"]] == [
        ("Tara", 857),  # 3000 × 2/7 = 857.14, rounded down
        ("Avi", 1000),
    ]
    assert out["transaction_ids"] == []
    assert me.get("/transactions") == []


def test_saving_writes_my_spend_and_a_lend_per_friend(me: Caller) -> None:
    card, t, a, food = _setup(me)

    r = me.post_raw("/transactions/split", **_body(me, card, t, a, food))

    assert r.status_code == 201, r.text
    assert len(r.json()["transaction_ids"]) == 3
    rows = me.get("/transactions")
    assert sorted((x["template"], x["amount"]["minor"], x["memo"]) for x in rows) == [
        ("lend", 857, "Walmart groceries"),
        ("lend", 1000, "Walmart groceries"),
        ("spend", 8143, "Walmart groceries"),
    ]
    friends = {f["name"]: f["position"]["minor"] for f in me.get("/summary")["friends"]}
    assert friends == {"Tara": 857, "Avi": 1000}
    card_row = next(x for x in me.get("/accounts") if x["id"] == card)
    assert card_row["balance"]["minor"] == 10000  # the card paid the whole bill
    food_total = next(c for c in me.get("/summary")["month"]["categories"] if c["id"] == food)
    assert food_total["total"]["minor"] == 8143  # only my share is spending


def test_when_friends_cover_it_all_there_is_no_spend(me: Caller) -> None:
    card, t, _, food = _setup(me)
    body = _body(me, card, t, t, food)
    body["amount_minor"] = 1000
    body["items"] = [
        {"amount_minor": 1000, "my_units": 0, "units": [{"counterparty_id": t, "units": 1}]}
    ]

    r = me.post_raw("/transactions/split", **body)

    assert r.status_code == 201, r.text
    assert [x["template"] for x in me.get("/transactions")] == ["lend"]


def test_split_refusals(me: Caller) -> None:
    card, t, a, food = _setup(me)
    twice = _body(me, card, t, a, food)
    twice["items"] = [
        {
            "amount_minor": 1000,
            "my_units": 0,
            "units": [{"counterparty_id": t, "units": 1}, {"counterparty_id": t, "units": 1}],
        }
    ]
    over = _body(me, card, t, a, food)
    over["amount_minor"] = 3500  # items are 4000

    assert me.post_raw("/transactions/split", **twice).status_code == 422
    assert me.post_raw("/transactions/split", **over).status_code == 422
    assert me.get("/transactions") == []  # nothing half-written


def test_a_split_with_someone_elses_person_is_404_and_writes_nothing(
    me: Caller, api: object, engine: object
) -> None:
    from tests.test_api import Caller as C

    them = C(api, engine)  # type: ignore[arg-type]
    theirs = them.post("/counterparties", name="Raj")["id"]
    card, t, _, food = _setup(me)

    r = me.post_raw("/transactions/split", **_body(me, card, t, theirs, food))

    assert r.status_code == 404
    assert me.get("/transactions") == []
