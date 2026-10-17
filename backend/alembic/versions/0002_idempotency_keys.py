"""Idempotency keys (CLAUDE.md §3.7, §6; D-017).

One row per (user, Idempotency-Key). The row is written when a POST starts, with no response;
the response is stored when it finishes. A replay of a row with no response is still in flight
and gets 409. Keys are scoped per user, so two tenants can never see each other's responses.

Retention is 7 days; the cleanup job arrives with the idempotency middleware.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE idempotency_keys (
            user_id          uuid NOT NULL REFERENCES users (id),
            key              text NOT NULL,
            request_hash     text NOT NULL,
            response_status  smallint,  -- null while the first request is still running
            response_body    jsonb,
            created_at       timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, key),
            CONSTRAINT idempotency_keys_status_is_http
                CHECK (response_status BETWEEN 100 AND 599)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE idempotency_keys")
