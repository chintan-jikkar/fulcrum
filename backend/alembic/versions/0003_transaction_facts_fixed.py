"""A transaction's facts never change, and a void is final (CLAUDE.md §6; SCENARIOS R-14, R-15).

Postings are already append-only (I7), so amounts and accounts cannot move. This closes the rest:
on a transaction only memo, method and category_id may change (category still subject to the
deferred I5 check), and voided_at may go from null to a time exactly once.

Errors start "R-14:" or "R-15:" after the scenario they enforce, in the spirit of D-037.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-19
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION transactions_facts_fixed() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF (NEW.id, NEW.user_id, NEW.template, NEW.occurred_on, NEW.refund_of_id,
                NEW.created_at)
               IS DISTINCT FROM
               (OLD.id, OLD.user_id, OLD.template, OLD.occurred_on, OLD.refund_of_id,
                OLD.created_at) THEN
                RAISE EXCEPTION 'R-14: transaction % can only change memo, method and '
                    'category; void it and re-enter', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.voided_at IS NOT NULL AND NEW.voided_at IS DISTINCT FROM OLD.voided_at THEN
                RAISE EXCEPTION 'R-15: transaction % is void, and a void is final', OLD.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END $$;

        CREATE TRIGGER transactions_facts_fixed
            BEFORE UPDATE ON transactions
            FOR EACH ROW EXECUTE FUNCTION transactions_facts_fixed();
    """)


def downgrade() -> None:
    op.execute("""
        DROP TRIGGER transactions_facts_fixed ON transactions;
        DROP FUNCTION transactions_facts_fixed();
    """)
