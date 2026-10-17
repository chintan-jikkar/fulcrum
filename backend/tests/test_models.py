"""The SQLAlchemy models match the hand-written migrations, and idempotency keys are per user.

Migrations are the source of truth (CLAUDE.md §15). The models only describe them, so any
column the two disagree on (missing, extra, wrong type, wrong nullability) fails here.
"""

import uuid

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app.db import Base
from app.models import ledger  # noqa: F401  (registers the models on Base.metadata)
from tests.test_ledger_schema import insert

# Constraints, partial indexes and triggers live only in the migrations, on purpose: the models
# carry what the ORM needs to read and write rows, and the database enforces the rest.
COLUMN_DIFFS = {"add_table", "remove_table", "add_column", "remove_column"}
MODIFY_DIFFS = {"modify_type", "modify_nullable"}


def test_models_match_migrated_columns(conn: Connection) -> None:
    context = MigrationContext.configure(conn, opts={"compare_type": True})
    diffs = []
    for diff in compare_metadata(context, Base.metadata):
        # Column changes come as a list of tuples; table and column adds/removes as one tuple.
        for change in diff if isinstance(diff, list) else [diff]:
            if change[0] in COLUMN_DIFFS | MODIFY_DIFFS:
                diffs.append(change)
    assert diffs == []


def user(conn: Connection) -> uuid.UUID:
    return insert(
        conn,
        "users",
        auth_sub=f"test|{uuid.uuid4()}",
        display_name="Test User",
        timezone="America/New_York",
    )


def key(conn: Connection, user_id: uuid.UUID, k: str) -> None:
    conn.execute(
        text("INSERT INTO idempotency_keys (user_id, key, request_hash) VALUES (:u, :k, 'h')"),
        {"u": user_id, "k": k},
    )


def test_same_idempotency_key_is_independent_per_user(conn: Connection) -> None:
    # SCENARIOS.md T-03, at the schema level.
    key(conn, user(conn), "k-1")
    key(conn, user(conn), "k-1")
    conn.commit()


def test_same_idempotency_key_twice_for_one_user_is_rejected(conn: Connection) -> None:
    u = user(conn)
    key(conn, u, "k-1")
    with pytest.raises(IntegrityError):
        key(conn, u, "k-1")


def test_in_flight_key_has_no_response_yet(conn: Connection) -> None:
    # A row without a response marks a request still running; replaying it gets 409 (§6).
    u = user(conn)
    key(conn, u, "k-1")
    row = conn.execute(
        text("SELECT response_status, response_body FROM idempotency_keys WHERE user_id = :u"),
        {"u": u},
    ).one()
    assert tuple(row) == (None, None)


@pytest.mark.parametrize("status", [99, 600])
def test_response_status_must_be_an_http_status(conn: Connection, status: int) -> None:
    u = user(conn)
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO idempotency_keys (user_id, key, request_hash, response_status, "
                "response_body) VALUES (:u, 'k', 'h', :s, '{}')"
            ),
            {"u": u, "s": status},
        )
