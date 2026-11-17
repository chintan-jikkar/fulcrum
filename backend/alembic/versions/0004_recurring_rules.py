"""Recurring rules: subscriptions and other repeating charges (CLAUDE.md §12, D-079).

A rule is a stored spend (name as memo, amount, funding account, expense category) plus a
cadence and the next date it is due. It proposes and never posts by itself: the user confirms
each charge, which writes an ordinary spend through the ledger, or skips it. `anchor_day` keeps
a monthly rule on its day (the 31st falls back to a short month's last day, then returns).

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE recurring_cadence AS ENUM ('weekly', 'monthly', 'yearly');

        CREATE TABLE recurring_rules (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       uuid NOT NULL REFERENCES users (id),
            name          text NOT NULL,
            amount_minor  bigint NOT NULL,
            funding_id    uuid NOT NULL,
            category_id   uuid NOT NULL,
            cadence       recurring_cadence NOT NULL,
            anchor_day    smallint NOT NULL,
            next_due_on   date NOT NULL,
            remind_days   smallint NOT NULL DEFAULT 2,
            is_active     boolean NOT NULL DEFAULT true,
            created_at    timestamptz NOT NULL DEFAULT now(),
            UNIQUE (id, user_id),
            -- I6: the funding account and category are the same user's.
            CONSTRAINT i6_recurring_funding_same_user
                FOREIGN KEY (funding_id, user_id) REFERENCES accounts (id, user_id),
            CONSTRAINT i6_recurring_category_same_user
                FOREIGN KEY (category_id, user_id) REFERENCES categories (id, user_id),
            CONSTRAINT recurring_name_not_blank CHECK (btrim(name) <> ''),
            CONSTRAINT recurring_amount_positive CHECK (amount_minor > 0),
            CONSTRAINT recurring_anchor_is_a_day CHECK (anchor_day BETWEEN 1 AND 31),
            CONSTRAINT recurring_remind_window CHECK (remind_days BETWEEN 0 AND 14)
        );
    """)


def downgrade() -> None:
    op.execute("DROP TABLE recurring_rules; DROP TYPE recurring_cadence;")
