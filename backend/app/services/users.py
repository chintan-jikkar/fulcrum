"""User provisioning (CLAUDE.md §3.1, SCENARIOS.md T-05).

The one service function that does not take `user_id` first: it is how a user id comes to exist.
"""

from zoneinfo import available_timezones

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.ledger import (
    Account,
    AccountKind,
    AccountSubtype,
    Category,
    CategoryKind,
    User,
)

# Copied to every new user, then theirs to edit. Food, Transport, Subscriptions and Salary are
# the ones SCENARIOS.md §D uses.
DEFAULT_CATEGORIES: list[tuple[str, CategoryKind]] = [
    ("Food", CategoryKind.expense),
    ("Transport", CategoryKind.expense),
    ("Housing", CategoryKind.expense),
    ("Utilities", CategoryKind.expense),
    ("Subscriptions", CategoryKind.expense),
    ("Shopping", CategoryKind.expense),
    ("Health", CategoryKind.expense),
    ("Entertainment", CategoryKind.expense),
    ("Other", CategoryKind.expense),
    ("Salary", CategoryKind.income),
    ("Other income", CategoryKind.income),
]


class InvalidTimezone(ValueError):
    pass


def provision_user(session: Session, auth_sub: str, display_name: str, timezone: str) -> User:
    """Return the user for `auth_sub`, creating them on their first request.

    A new user gets their `world` and `opening` accounts and the default categories in the same
    database transaction, so no request ever sees a half-provisioned user. Two first requests at
    once both try the insert; the auth_sub unique index makes the second wait for the first to
    commit and then find its row. The caller commits.

    display_name and timezone apply only on creation; later calls never overwrite them.
    """
    if timezone not in available_timezones():
        raise InvalidTimezone(f"unknown IANA timezone: {timezone!r}")

    new_id = session.scalar(
        insert(User)
        .values(auth_sub=auth_sub, display_name=display_name, timezone=timezone)
        .on_conflict_do_nothing(index_elements=[User.auth_sub])
        .returning(User.id)
    )
    if new_id is not None:
        session.add_all(
            [
                Account(
                    user_id=new_id,
                    name="World",
                    kind=AccountKind.EXTERNAL,
                    subtype=AccountSubtype.world,
                ),
                Account(
                    user_id=new_id,
                    name="Opening balances",
                    kind=AccountKind.EXTERNAL,
                    subtype=AccountSubtype.opening,
                ),
                *(Category(user_id=new_id, name=n, kind=k) for n, k in DEFAULT_CATEGORIES),
            ]
        )
        session.flush()

    return session.scalars(select(User).where(User.auth_sub == auth_sub)).one()
