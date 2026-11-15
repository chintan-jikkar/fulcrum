"""Idempotency over HTTP (CLAUDE.md §6; D-017, D-042; SCENARIOS.md R-11, R-12, R-21, T-03, P-8).

Requests go through the real app and the real database. Only the caller's identity is faked: the
`X-Test-User` header stands in for the JWT until O-1 is settled.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date
from typing import Annotated, Any

import httpx
import pytest
from fastapi import Header
from fastapi.testclient import TestClient
from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session

from app.auth import current_user_id
from app.db import get_engine
from app.main import app
from app.models.ledger import AccountSubtype, Category
from app.services import ledger
from app.services.users import provision_user

SPEND = "/transactions/spend"


def _header_user(x_test_user: Annotated[uuid.UUID, Header()]) -> uuid.UUID:
    return x_test_user


@contextmanager
def client_for(engine: Engine, *, fake_auth: bool = True, **kw: Any) -> Iterator[TestClient]:
    app.dependency_overrides[get_engine] = lambda: engine
    if fake_auth:
        app.dependency_overrides[current_user_id] = _header_user
    try:
        yield TestClient(app, **kw)
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
def api(engine: Engine) -> Iterator[TestClient]:
    with client_for(engine) as c:
        yield c


@dataclass
class Tenant:
    uid: uuid.UUID
    chase: uuid.UUID  # bank, opened with 150000
    spare: uuid.UUID  # bank, never opened, so it can be archived
    food: uuid.UUID


def make_tenant(engine: Engine) -> Tenant:
    with Session(engine) as s:
        uid = provision_user(s, f"idem|{uuid.uuid4()}", "Idem", "America/New_York").id
        bank = AccountSubtype.bank
        chase = ledger.create_account(s, uid, name="Chase", subtype=bank, meta={}).id
        spare = ledger.create_account(s, uid, name="Spare", subtype=bank, meta={}).id
        ledger.opening(s, uid, account_id=chase, amount_minor=150000, occurred_on=date(2026, 2, 28))
        food = s.scalars(
            select(Category.id).where(Category.user_id == uid, Category.name == "Food")
        ).one()
        s.commit()
        return Tenant(uid, chase, spare, food)


@pytest.fixture
def a(engine: Engine) -> Tenant:
    return make_tenant(engine)


@pytest.fixture
def b(engine: Engine) -> Tenant:
    return make_tenant(engine)


def spend_body(t: Tenant, amount: int = 4000, funding: uuid.UUID | None = None) -> dict[str, Any]:
    return {
        "funding_id": str(funding or t.chase),
        "amount_minor": amount,
        "category_id": str(t.food),
        "occurred_on": "2026-03-01",
    }


def post(
    api: TestClient, t: Tenant, path: str, key: str | None, json: dict[str, Any] | None = None
) -> httpx.Response:
    headers = {"X-Test-User": str(t.uid)}
    if key is not None:
        headers["Idempotency-Key"] = key
    response: httpx.Response = api.post(path, json=json, headers=headers)
    return response


def snapshot(engine: Engine, t: Tenant) -> dict[str, list[tuple[Any, ...]]]:
    """Every row the tenant owns in the tables a POST can touch."""
    with engine.connect() as c:
        return {
            table: [
                tuple(r)
                for r in c.execute(
                    text(f"SELECT * FROM {table} WHERE user_id = :u ORDER BY 1, 2"), {"u": t.uid}
                )
            ]
            for table in ("transactions", "postings", "idempotency_keys", "accounts")
        }


def spends(engine: Engine, t: Tenant) -> int:
    q = text("SELECT count(*) FROM transactions WHERE user_id = :u AND template = 'spend'")
    with engine.connect() as c:
        count: int = c.execute(q, {"u": t.uid}).scalar_one()
        return count


def chase_balance(engine: Engine, t: Tenant) -> int:
    with Session(engine) as s:
        return ledger.balance_raw(s, t.uid, t.chase)


# --- R-11, R-12 ------------------------------------------------------------------------------


def test_r11_same_key_same_body_writes_one_transaction(
    api: TestClient, engine: Engine, a: Tenant
) -> None:
    first = post(api, a, SPEND, "k1", spend_body(a))
    assert first.status_code == 201
    body = first.json()
    assert body["template"] == "spend"
    assert body["occurred_on"] == "2026-03-01"
    assert body["category_id"] == str(a.food)
    assert body["voided_at"] is None
    before = snapshot(engine, a)

    second = post(api, a, SPEND, "k1", spend_body(a))

    assert (second.status_code, second.json()) == (201, body)
    assert snapshot(engine, a) == before
    assert spends(engine, a) == 1
    assert chase_balance(engine, a) == 146000


def test_r12_same_key_different_body_is_409_and_writes_nothing(
    api: TestClient, engine: Engine, a: Tenant
) -> None:
    assert post(api, a, SPEND, "k1", spend_body(a, 4000)).status_code == 201
    before = snapshot(engine, a)

    r = post(api, a, SPEND, "k1", spend_body(a, 5000))

    assert r.status_code == 409
    assert r.json()["code"] == "idempotency_key_reused"
    assert snapshot(engine, a) == before


def test_same_key_on_another_path_is_409(api: TestClient, engine: Engine, a: Tenant) -> None:
    # Two voids have the same (empty) body, so only the path tells them apart.
    one = post(api, a, SPEND, "s1", spend_body(a)).json()["id"]
    two = post(api, a, SPEND, "s2", spend_body(a)).json()["id"]
    assert post(api, a, f"/transactions/{one}/void", "k1").status_code == 200
    before = snapshot(engine, a)

    r = post(api, a, f"/transactions/{two}/void", "k1")

    assert r.status_code == 409
    assert r.json()["code"] == "idempotency_key_reused"
    assert snapshot(engine, a) == before  # `two` is still not void


def test_post_without_a_key_is_rejected(api: TestClient, engine: Engine, a: Tenant) -> None:
    before = snapshot(engine, a)

    r = post(api, a, SPEND, None, spend_body(a))

    assert r.status_code == 422
    assert snapshot(engine, a) == before


def test_unauthenticated_post_is_401(engine: Engine, a: Tenant) -> None:
    before = snapshot(engine, a)
    with client_for(engine, fake_auth=False) as real:
        r = post(real, a, SPEND, "k1", spend_body(a))

    assert r.status_code == 401
    assert snapshot(engine, a) == before


# --- R-21 ------------------------------------------------------------------------------------


def test_r21_second_void_with_a_new_key_is_409(api: TestClient, engine: Engine, a: Tenant) -> None:
    txn_id = post(api, a, SPEND, "k1", spend_body(a)).json()["id"]

    first = post(api, a, f"/transactions/{txn_id}/void", "v1")
    assert first.status_code == 200
    assert first.json()["id"] == txn_id
    assert first.json()["voided_at"] is not None
    assert chase_balance(engine, a) == 150000

    second = post(api, a, f"/transactions/{txn_id}/void", "v2")
    assert second.status_code == 409
    assert second.json()["code"] == "conflict"

    replay = post(api, a, f"/transactions/{txn_id}/void", "v1")
    assert (replay.status_code, replay.json()) == (200, first.json())


# --- T-03 ------------------------------------------------------------------------------------


def test_t03_two_tenants_share_a_key_independently(
    api: TestClient, engine: Engine, a: Tenant, b: Tenant
) -> None:
    ra = post(api, a, SPEND, "shared", spend_body(a, 4000))
    rb = post(api, b, SPEND, "shared", spend_body(b, 5000))

    assert (ra.status_code, rb.status_code) == (201, 201)
    assert ra.json()["id"] != rb.json()["id"]
    assert post(api, a, SPEND, "shared", spend_body(a, 4000)).json() == ra.json()
    assert post(api, b, SPEND, "shared", spend_body(b, 5000)).json() == rb.json()
    assert (chase_balance(engine, a), chase_balance(engine, b)) == (146000, 145000)
    assert (spends(engine, a), spends(engine, b)) == (1, 1)


# --- The stored response, the in-flight state, retention ---------------------------------------


def test_a_rejection_is_stored_and_replayed(api: TestClient, engine: Engine, a: Tenant) -> None:
    with Session(engine) as s:
        ledger.archive_account(s, a.uid, a.spare)
        s.commit()
    first = post(api, a, SPEND, "k1", spend_body(a, funding=a.spare))
    assert first.status_code == 422
    assert first.json()["code"] == "I4"

    # The same request would now succeed, so only the stored response can still say 422.
    with Session(engine) as s:
        ledger.unarchive_account(s, a.uid, a.spare)
        s.commit()
    replay = post(api, a, SPEND, "k1", spend_body(a, funding=a.spare))

    assert (replay.status_code, replay.json()) == (422, first.json())
    assert spends(engine, a) == 0


def test_replay_while_the_first_request_is_running_is_409(engine: Engine, a: Tenant) -> None:
    results: list[httpx.Response] = []
    with client_for(engine) as api, engine.connect() as blocker:
        # The spend reads its funding account FOR SHARE, so this lock holds it mid-request.
        blocker.execute(text("SELECT 1 FROM accounts WHERE id = :id FOR UPDATE"), {"id": a.chase})
        first = threading.Thread(
            target=lambda: results.append(post(api, a, SPEND, "k1", spend_body(a)))
        )
        first.start()
        try:
            deadline = time.monotonic() + 10
            while not snapshot(engine, a)["idempotency_keys"]:
                assert time.monotonic() < deadline, "the first request never claimed its key"
                time.sleep(0.02)

            during = post(api, a, SPEND, "k1", spend_body(a))
        finally:
            blocker.rollback()
            first.join(timeout=10)

        assert during.status_code == 409
        assert during.json()["code"] == "idempotency_in_flight"
        assert results[0].status_code == 201
        after = post(api, a, SPEND, "k1", spend_body(a))
        assert (after.status_code, after.json()) == (201, results[0].json())
        assert spends(engine, a) == 1


@pytest.mark.parametrize(("age_days", "status"), [(6, 409), (8, 201)])
def test_keys_are_kept_for_seven_days(
    api: TestClient, engine: Engine, a: Tenant, age_days: int, status: int
) -> None:
    assert post(api, a, SPEND, "k1", spend_body(a, 4000)).status_code == 201
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE idempotency_keys SET created_at = now() - make_interval(days => :d) "
                "WHERE user_id = :u"
            ),
            {"d": age_days, "u": a.uid},
        )

    r = post(api, a, SPEND, "k1", spend_body(a, 5000))

    assert r.status_code == status
    assert spends(engine, a) == (2 if status == 201 else 1)


def test_a_crashed_request_frees_its_key(
    engine: Engine, a: Tenant, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: Any, **kw: Any) -> None:
        raise RuntimeError("simulated crash")

    with client_for(engine, raise_server_exceptions=False) as api:
        with monkeypatch.context() as m:
            m.setattr(ledger, "spend", boom)
            assert post(api, a, SPEND, "k1", spend_body(a)).status_code == 500
        assert spends(engine, a) == 0

        retry = post(api, a, SPEND, "k1", spend_body(a))

    assert retry.status_code == 201
    assert spends(engine, a) == 1


# --- P-8 -------------------------------------------------------------------------------------

# A spend of zero or less is rejected (I3). A void picks from the transactions made so far, so it
# also hits already-void ones (409); with none made yet it targets an unknown id (404).
OPS = st.lists(
    st.one_of(
        st.tuples(st.just("spend"), st.integers(-1, 10**6)),
        st.tuples(st.just("void"), st.integers(0, 100)),
    ),
    max_size=12,
)


@settings(max_examples=20, deadline=None)
@given(OPS)
def test_p8_replaying_any_request_changes_nothing(
    engine: Engine, ops: list[tuple[str, int]]
) -> None:
    t = make_tenant(engine)
    made: list[str] = []
    sent: list[tuple[str, str, dict[str, Any] | None, httpx.Response]] = []
    with client_for(engine) as api:
        for verb, n in ops:
            key = str(uuid.uuid4())
            if verb == "spend":
                path, body = SPEND, spend_body(t, n)
            else:
                target = made[n % len(made)] if made else str(uuid.uuid4())
                path, body = f"/transactions/{target}/void", None
            first = post(api, t, path, key, body)
            assert first.status_code in (200, 201, 404, 409, 422)
            if verb == "spend" and first.status_code == 201:
                made.append(first.json()["id"])
            sent.append((path, key, body, first))
            before = snapshot(engine, t)

            replay = post(api, t, path, key, body)

            assert (replay.status_code, replay.json()) == (first.status_code, first.json())
            assert snapshot(engine, t) == before

        # Old keys still answer the same after everything that came later.
        before = snapshot(engine, t)
        for path, key, body, first in sent:
            replay = post(api, t, path, key, body)
            assert (replay.status_code, replay.json()) == (first.status_code, first.json())
        assert snapshot(engine, t) == before
