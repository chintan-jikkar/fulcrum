"""Ledger core: users, counterparties, accounts, categories, transactions, postings.

Enforces CLAUDE.md §3.8 invariants I1, I2, I3, I5, I6 and I7 in the database. The rest
(I4, I8, I9, I10) live in the service layer, which also re-checks everything here.

Every invariant error names its invariant: triggers raise "I<n>: ..." and constraints are named
i<n>_..., so the service layer can map a database error back to the rule it broke.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TYPES = """
CREATE TYPE account_kind AS ENUM ('ASSET', 'LIABILITY', 'EXTERNAL');
CREATE TYPE account_subtype AS ENUM
    ('cash', 'bank', 'credit_card', 'receivable', 'payable', 'world', 'opening');
CREATE TYPE category_kind AS ENUM ('expense', 'income');
CREATE TYPE transaction_template AS ENUM
    ('spend', 'income', 'refund', 'transfer', 'card_payment',
     'lend', 'friend_repay', 'borrow', 'repay_friend', 'opening');
CREATE TYPE payment_method AS ENUM ('cash', 'bank_transfer', 'card', 'other');
"""

# I6: every table but users has UNIQUE (id, user_id), and every cross-table reference is a
# composite foreign key on (x_id, user_id). A row can only point at rows of its own user. The
# FKs are MATCH SIMPLE, so a NULL x_id (no category, no parent, ...) skips the check, as intended.
TABLES = """
CREATE TABLE users (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_sub      text NOT NULL UNIQUE,
    display_name  text NOT NULL,
    timezone      text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE counterparties (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     uuid NOT NULL REFERENCES users (id),
    name        text NOT NULL,
    contact     text,
    is_active   boolean NOT NULL DEFAULT true,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id)
);
CREATE UNIQUE INDEX counterparties_user_name_key ON counterparties (user_id, lower(name));

CREATE TABLE accounts (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id          uuid NOT NULL REFERENCES users (id),
    name             text NOT NULL,
    kind             account_kind NOT NULL,
    subtype          account_subtype NOT NULL,
    currency         char(3) NOT NULL DEFAULT 'USD',
    counterparty_id  uuid,
    is_active        boolean NOT NULL DEFAULT true,
    meta             jsonb NOT NULL DEFAULT '{}',
    created_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CONSTRAINT i6_accounts_counterparty_same_user
        FOREIGN KEY (counterparty_id, user_id) REFERENCES counterparties (id, user_id),
    -- §3.3: kind is fixed by subtype. Balances and net worth read kind, so it cannot drift.
    CONSTRAINT accounts_kind_matches_subtype CHECK (kind = CASE
        WHEN subtype IN ('cash', 'bank', 'receivable') THEN 'ASSET'::account_kind
        WHEN subtype IN ('credit_card', 'payable') THEN 'LIABILITY'::account_kind
        ELSE 'EXTERNAL'::account_kind
    END),
    CONSTRAINT accounts_counterparty_iff_person
        CHECK ((counterparty_id IS NOT NULL) = (subtype IN ('receivable', 'payable')))
);
-- Exactly one world and one opening per user (at most one here; provisioning creates both).
CREATE UNIQUE INDEX accounts_one_outside_per_user
    ON accounts (user_id, subtype) WHERE subtype IN ('world', 'opening');
-- One receivable and one payable per counterparty, so "created on first use" cannot race.
CREATE UNIQUE INDEX accounts_one_per_counterparty
    ON accounts (counterparty_id, subtype) WHERE counterparty_id IS NOT NULL;

CREATE TABLE categories (
    id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id      uuid NOT NULL REFERENCES users (id),
    name         text NOT NULL,
    icon         text,
    color        text,
    kind         category_kind NOT NULL,
    parent_id    uuid,
    is_archived  boolean NOT NULL DEFAULT false,
    UNIQUE (id, user_id),
    CONSTRAINT i6_categories_parent_same_user
        FOREIGN KEY (parent_id, user_id) REFERENCES categories (id, user_id),
    CONSTRAINT categories_not_own_parent CHECK (parent_id <> id)
);

CREATE TABLE transactions (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id       uuid NOT NULL REFERENCES users (id),
    template      transaction_template NOT NULL,
    occurred_on   date NOT NULL,
    memo          text NOT NULL DEFAULT '',
    category_id   uuid,
    method        payment_method,
    refund_of_id  uuid,
    voided_at     timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (id, user_id),
    CONSTRAINT i6_transactions_category_same_user
        FOREIGN KEY (category_id, user_id) REFERENCES categories (id, user_id),
    CONSTRAINT i6_transactions_refund_same_user
        FOREIGN KEY (refund_of_id, user_id) REFERENCES transactions (id, user_id),
    CONSTRAINT transactions_refund_link_only_on_refund
        CHECK (refund_of_id IS NULL OR template = 'refund')
);

CREATE TABLE postings (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         uuid NOT NULL,
    transaction_id  uuid NOT NULL,
    account_id      uuid NOT NULL,
    amount_minor    bigint NOT NULL,  -- positive = debit
    CONSTRAINT i6_postings_transaction_same_user
        FOREIGN KEY (transaction_id, user_id) REFERENCES transactions (id, user_id),
    CONSTRAINT i6_postings_account_same_user
        FOREIGN KEY (account_id, user_id) REFERENCES accounts (id, user_id),
    CONSTRAINT i3_postings_amount_nonzero CHECK (amount_minor <> 0),
    -- Also serves as the index for looking up a transaction's postings.
    CONSTRAINT i3_postings_distinct_accounts UNIQUE (transaction_id, account_id)
);
CREATE INDEX postings_account_id_idx ON postings (account_id);
"""

# I1, I2, I5 depend on a transaction and all its postings together, so no single INSERT can be
# checked on its own. Constraint triggers marked INITIALLY DEFERRED queue a check per touched
# row and run it at COMMIT, when the whole transaction is in place.
LEDGER_CHECKS = """
CREATE FUNCTION ledger_check_transaction(txn uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE
    has_category boolean;
    leg_count    bigint;
    leg_sum      numeric;
    world_legs   bigint;
BEGIN
    SELECT category_id IS NOT NULL INTO has_category FROM transactions WHERE id = txn;
    IF NOT FOUND THEN
        RETURN;  -- removed by the tenant purge in this same database transaction
    END IF;

    SELECT count(*), coalesce(sum(p.amount_minor), 0), count(*) FILTER (WHERE a.subtype = 'world')
      INTO leg_count, leg_sum, world_legs
      FROM postings p JOIN accounts a ON a.id = p.account_id
     WHERE p.transaction_id = txn;

    IF leg_count <> 2 THEN
        RAISE EXCEPTION 'I2: transaction % has % postings; v1 requires exactly 2', txn, leg_count
            USING ERRCODE = 'check_violation';
    END IF;
    IF leg_sum <> 0 THEN
        RAISE EXCEPTION 'I1: postings of transaction % sum to %, not 0', txn, leg_sum
            USING ERRCODE = 'check_violation';
    END IF;
    IF has_category <> (world_legs = 1) THEN
        RAISE EXCEPTION 'I5: transaction % has % world legs, so it must % a category',
            txn, world_legs, CASE WHEN world_legs = 1 THEN 'have' ELSE 'not have' END
            USING ERRCODE = 'check_violation';
    END IF;
END $$;

CREATE FUNCTION ledger_check_transaction_trigger() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'transactions' THEN
        PERFORM ledger_check_transaction(NEW.id);
    ELSIF TG_OP = 'DELETE' THEN
        PERFORM ledger_check_transaction(OLD.transaction_id);
    ELSE
        PERFORM ledger_check_transaction(NEW.transaction_id);
    END IF;
    RETURN NULL;
END $$;

CREATE CONSTRAINT TRIGGER i1_i2_i5_transactions
    AFTER INSERT OR UPDATE OF category_id ON transactions
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_check_transaction_trigger();

-- UPDATE and DELETE are already refused by I7; checking them too costs nothing.
CREATE CONSTRAINT TRIGGER i1_i2_i5_postings
    AFTER INSERT OR UPDATE OR DELETE ON postings
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION ledger_check_transaction_trigger();

-- I5 counts world legs by account subtype, and balances read kind, so an account's type is
-- fixed once created. Changing a bank into `world` would rewrite the meaning of its history.
CREATE FUNCTION accounts_type_is_fixed() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'I5: account % kind, subtype and counterparty cannot change', OLD.id
        USING ERRCODE = 'check_violation';
END $$;

CREATE TRIGGER accounts_type_is_fixed
    BEFORE UPDATE OF kind, subtype, counterparty_id ON accounts
    FOR EACH ROW
    WHEN (OLD.kind IS DISTINCT FROM NEW.kind
          OR OLD.subtype IS DISTINCT FROM NEW.subtype
          OR OLD.counterparty_id IS DISTINCT FROM NEW.counterparty_id)
    EXECUTE FUNCTION accounts_type_is_fixed();
"""

# I7: postings never change. The one exception is the user-initiated tenant purge (§7, D-015),
# which runs SELECT set_config('fulcrum.purge_user_id', '<user id>', true) inside its own
# database transaction. That lifts the block for DELETEs of that user's rows only, and the
# setting expires when the transaction ends. UPDATE is never allowed.
#
# This guards against application bugs, not against the database owner, who can drop triggers.
APPEND_ONLY = """
CREATE FUNCTION postings_append_only() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.user_id::text = current_setting('fulcrum.purge_user_id', true) THEN
            RETURN OLD;
        END IF;
    END IF;
    RAISE EXCEPTION 'I7: postings are append-only; % refused', TG_OP
        USING ERRCODE = 'check_violation';
END $$;

CREATE TRIGGER i7_postings_append_only
    BEFORE UPDATE OR DELETE ON postings
    FOR EACH ROW EXECUTE FUNCTION postings_append_only();

CREATE TRIGGER i7_postings_no_truncate
    BEFORE TRUNCATE ON postings
    FOR EACH STATEMENT EXECUTE FUNCTION postings_append_only();
"""


def upgrade() -> None:
    op.execute(TYPES)
    op.execute(TABLES)
    op.execute(LEDGER_CHECKS)
    op.execute(APPEND_ONLY)


def downgrade() -> None:
    # Dropping the tables drops their triggers; the functions and types go after.
    op.execute("""
        DROP TABLE postings, transactions, categories, accounts, counterparties, users;
        DROP FUNCTION postings_append_only(), accounts_type_is_fixed(),
                      ledger_check_transaction_trigger(), ledger_check_transaction(uuid);
        DROP TYPE payment_method, transaction_template, category_kind,
                  account_subtype, account_kind;
    """)
