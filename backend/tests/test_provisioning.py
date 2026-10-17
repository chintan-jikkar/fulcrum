"""User provisioning (CLAUDE.md §3.1, SCENARIOS.md T-05).

A user's first authenticated request creates their row, their `world` and `opening` accounts and
the default categories, all in one database transaction. Any later request, including one racing
the first, finds that user and creates nothing.
"""

import threading
import uuid

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models.ledger import Account, AccountSubtype, Category, CategoryKind, User
from app.services.users import DEFAULT_CATEGORIES, InvalidTimezone, provision_user


def new_sub() -> str:
    return f"test|{uuid.uuid4()}"


def provision(engine: Engine, sub: str, timezone: str = "America/New_York") -> uuid.UUID:
    with Session(engine) as s:
        user = provision_user(s, sub, "Test User", timezone)
        s.commit()
        return user.id


def outside_accounts(s: Session, user_id: uuid.UUID) -> list[AccountSubtype]:
    rows = s.scalars(
        select(Account.subtype)
        .where(Account.user_id == user_id, Account.kind == "EXTERNAL")
        .order_by(Account.subtype)
    )
    return list(rows)


def categories(s: Session, user_id: uuid.UUID) -> list[tuple[str, CategoryKind]]:
    # Sorted in Python: the database's collation may order names differently.
    rows = s.execute(select(Category.name, Category.kind).where(Category.user_id == user_id))
    return sorted((name, kind) for name, kind in rows)


def test_first_request_creates_user_world_opening_and_default_categories(engine: Engine) -> None:
    user_id = provision(engine, new_sub())

    with Session(engine) as s:
        assert outside_accounts(s, user_id) == [AccountSubtype.world, AccountSubtype.opening]
        assert categories(s, user_id) == sorted(DEFAULT_CATEGORIES)
        # Only the two outside accounts: real accounts are the user's to add.
        count = s.scalar(select(func.count()).where(Account.user_id == user_id))
        assert count == 2


def test_defaults_cover_the_golden_month_categories() -> None:
    names = {name for name, _ in DEFAULT_CATEGORIES}
    assert {"Food", "Transport", "Subscriptions", "Salary"} <= names
    assert ("Salary", CategoryKind.income) in DEFAULT_CATEGORIES


def test_second_request_returns_same_user_and_creates_nothing(engine: Engine) -> None:
    sub = new_sub()
    first = provision(engine, sub)
    second = provision(engine, sub, timezone="Europe/London")

    assert second == first
    with Session(engine) as s:
        assert outside_accounts(s, first) == [AccountSubtype.world, AccountSubtype.opening]
        assert len(categories(s, first)) == len(DEFAULT_CATEGORIES)
        # A later request never rewrites the profile set at first sign-in.
        user = s.get_one(User, first)
        assert user.timezone == "America/New_York"


def test_racing_first_requests_provision_exactly_once(engine: Engine) -> None:
    """Two first requests at once: the second waits on the auth_sub unique index, then finds
    the user the first one committed."""
    sub = new_sub()
    results: list[uuid.UUID] = []

    with Session(engine) as first:
        first_id = provision_user(first, sub, "Test User", "America/New_York").id

        racer = threading.Thread(target=lambda: results.append(provision(engine, sub)))
        racer.start()
        racer.join(timeout=0.5)
        assert racer.is_alive(), "the racer should block until the first request commits"

        first.commit()
    racer.join(timeout=10)

    assert results == [first_id]
    with Session(engine) as s:
        users = s.scalar(select(func.count()).where(User.auth_sub == sub))
        assert users == 1
        assert outside_accounts(s, first_id) == [AccountSubtype.world, AccountSubtype.opening]
        assert len(categories(s, first_id)) == len(DEFAULT_CATEGORIES)


def test_racer_provisions_if_the_first_request_rolls_back(engine: Engine) -> None:
    sub = new_sub()
    results: list[uuid.UUID] = []

    with Session(engine) as first:
        provision_user(first, sub, "Test User", "America/New_York")
        racer = threading.Thread(target=lambda: results.append(provision(engine, sub)))
        racer.start()
        racer.join(timeout=0.5)
        first.rollback()
    racer.join(timeout=10)

    assert len(results) == 1
    with Session(engine) as s:
        assert outside_accounts(s, results[0]) == [AccountSubtype.world, AccountSubtype.opening]


def test_each_user_gets_their_own_outside_accounts_and_categories(engine: Engine) -> None:
    a = provision(engine, new_sub())
    b = provision(engine, new_sub())

    with Session(engine) as s:
        a_accounts = set(s.scalars(select(Account.id).where(Account.user_id == a)))
        b_accounts = set(s.scalars(select(Account.id).where(Account.user_id == b)))
        assert len(a_accounts) == len(b_accounts) == 2
        assert not a_accounts & b_accounts


@pytest.mark.parametrize("timezone", ["", "Mars/Olympus_Mons", "../../etc/passwd", "EST5EDT "])
def test_unknown_timezone_is_rejected_and_nothing_is_written(engine: Engine, timezone: str) -> None:
    sub = new_sub()
    with Session(engine) as s, pytest.raises(InvalidTimezone):
        provision_user(s, sub, "Test User", timezone)

    with Session(engine) as s:
        assert s.scalar(select(func.count()).where(User.auth_sub == sub)) == 0
