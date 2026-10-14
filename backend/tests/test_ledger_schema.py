"""Database-level ledger invariants (CLAUDE.md §3.8), exercised with raw SQL.

These prove the schema alone refuses bad ledger states (SCENARIOS.md R-17 to R-20), so a service
bug cannot write one. The service layer re-checks every rule with friendlier errors.

Deferred checks (I1, I2, I5) fire at COMMIT, so those tests call conn.commit() inside
pytest.raises. Everything else fails on the statement itself.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from tests.conftest import migrate, recreate_database


def insert(conn: Connection, table: str, **values: Any) -> uuid.UUID:
    cols = ", ".join(values)
    params = ", ".join(f":{k}" for k in values)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({params}) RETURNING id"
    result: uuid.UUID = conn.execute(text(sql), values).scalar_one()
    return result


@dataclass
class Tenant:
    user: uuid.UUID
    world: uuid.UUID
    opening: uuid.UUID
    chase: uuid.UUID
    wallet: uuid.UUID
    amex: uuid.UUID
    food: uuid.UUID
    salary: uuid.UUID


def make_tenant(conn: Connection) -> Tenant:
    """One user with the accounts and categories from SCENARIOS.md §A. Fictional, as always."""
    user = insert(
        conn,
        "users",
        auth_sub=f"test|{uuid.uuid4()}",
        display_name="Test User",
        timezone="America/New_York",
    )

    def account(name: str, kind: str, subtype: str) -> uuid.UUID:
        return insert(conn, "accounts", user_id=user, name=name, kind=kind, subtype=subtype)

    def category(name: str, kind: str) -> uuid.UUID:
        return insert(conn, "categories", user_id=user, name=name, kind=kind)

    return Tenant(
        user=user,
        world=account("World", "EXTERNAL", "world"),
        opening=account("Opening", "EXTERNAL", "opening"),
        chase=account("Chase", "ASSET", "bank"),
        wallet=account("Wallet", "ASSET", "cash"),
        amex=account("Amex", "LIABILITY", "credit_card"),
        food=category("Food", "expense"),
        salary=category("Salary", "income"),
    )


def post(
    conn: Connection,
    t: Tenant,
    template: str,
    legs: list[tuple[uuid.UUID, int]],
    category: uuid.UUID | None = None,
) -> uuid.UUID:
    """Insert a transaction and its postings exactly as given. No validation: that is the point."""
    txn = insert(
        conn,
        "transactions",
        user_id=t.user,
        template=template,
        occurred_on="2026-03-01",
        category_id=category,
    )
    for account, amount in legs:
        insert(
            conn,
            "postings",
            user_id=t.user,
            transaction_id=txn,
            account_id=account,
            amount_minor=amount,
        )
    return txn


def posting_count(conn: Connection, txn: uuid.UUID) -> int:
    sql = text("SELECT count(*) FROM postings WHERE transaction_id = :t")
    count: int = conn.execute(sql, {"t": txn}).scalar_one()
    return count


# --- Valid entries commit -------------------------------------------------------------------


def test_every_template_shape_from_claude_md_section_4_commits(conn: Connection) -> None:
    t = make_tenant(conn)
    raj = insert(conn, "counterparties", user_id=t.user, name="Raj")
    recv_raj = insert(
        conn,
        "accounts",
        user_id=t.user,
        name="Raj owes me",
        kind="ASSET",
        subtype="receivable",
        counterparty_id=raj,
    )
    spend = post(conn, t, "spend", [(t.world, 4000), (t.chase, -4000)], t.food)
    post(conn, t, "spend", [(t.world, 4000), (t.amex, -4000)], t.food)
    post(conn, t, "card_payment", [(t.amex, 20000), (t.chase, -20000)])
    post(conn, t, "lend", [(recv_raj, 5000), (t.wallet, -5000)])
    post(conn, t, "friend_repay", [(t.chase, 5000), (recv_raj, -5000)])
    post(conn, t, "income", [(t.chase, 60000), (t.world, -60000)], t.salary)
    post(conn, t, "transfer", [(t.chase, 30000), (t.wallet, -30000)])
    post(conn, t, "opening", [(t.chase, 150000), (t.opening, -150000)])
    post(conn, t, "opening", [(t.opening, 20000), (t.amex, -20000)])
    refund = post(conn, t, "refund", [(t.chase, 1000), (t.world, -1000)], t.food)
    conn.execute(
        text("UPDATE transactions SET refund_of_id = :s WHERE id = :r"), {"s": spend, "r": refund}
    )
    conn.commit()

    assert posting_count(conn, spend) == 2


def test_memo_method_and_void_can_be_updated(conn: Connection) -> None:
    t = make_tenant(conn)
    txn = post(conn, t, "spend", [(t.world, 4000), (t.chase, -4000)], t.food)
    conn.commit()
    conn.execute(
        text(
            "UPDATE transactions SET memo = 'lunch', method = 'card', voided_at = now()"
            " WHERE id = :t"
        ),
        {"t": txn},
    )
    conn.commit()


# --- I1, I2: balanced pairs, checked at commit (R-17) ---------------------------------------


def test_i1_postings_must_sum_to_zero(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "spend", [(t.world, 4000), (t.chase, -3999)], t.food)
    with pytest.raises(IntegrityError, match="I1"):
        conn.commit()


def test_i1_i2_check_is_deferred_until_commit(conn: Connection) -> None:
    # A half-written transaction is fine mid-flight; only the committed state must balance.
    t = make_tenant(conn)
    txn = post(conn, t, "spend", [(t.world, 4000)], t.food)
    assert posting_count(conn, txn) == 1
    insert(
        conn, "postings", user_id=t.user, transaction_id=txn, account_id=t.chase, amount_minor=-4000
    )
    conn.commit()


def test_i2_posting_appended_to_a_committed_transaction_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    txn = post(conn, t, "transfer", [(t.chase, 5000), (t.wallet, -5000)])
    conn.commit()
    insert(conn, "postings", user_id=t.user, transaction_id=txn, account_id=t.amex, amount_minor=1)
    with pytest.raises(IntegrityError, match="I2"):
        conn.commit()


def test_i2_one_posting_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "spend", [(t.world, 4000)], t.food)
    with pytest.raises(IntegrityError, match="I2"):
        conn.commit()


def test_i2_three_balanced_postings_are_rejected_in_v1(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "transfer", [(t.chase, 3000), (t.wallet, -1000), (t.amex, -2000)])
    with pytest.raises(IntegrityError, match="I2"):
        conn.commit()


def test_i2_transaction_with_no_postings_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "transfer", [])
    with pytest.raises(IntegrityError, match="I2"):
        conn.commit()


# --- I3: non-zero amounts on distinct accounts (R-04, R-06) ---------------------------------


def test_i3_zero_amount_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    with pytest.raises(IntegrityError, match="i3_postings_amount_nonzero"):
        post(conn, t, "transfer", [(t.chase, 0), (t.wallet, 0)])


def test_i3_both_legs_on_one_account_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    with pytest.raises(IntegrityError, match="i3_postings_distinct_accounts"):
        post(conn, t, "transfer", [(t.chase, 5000), (t.chase, -5000)])


# --- I5: category iff exactly one world leg, checked at commit (R-01, R-02, R-18) -----------


def test_i5_category_on_a_card_payment_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "card_payment", [(t.amex, 20000), (t.chase, -20000)], t.food)
    with pytest.raises(IntegrityError, match="I5"):
        conn.commit()


def test_i5_spend_without_category_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "spend", [(t.world, 4000), (t.chase, -4000)])
    with pytest.raises(IntegrityError, match="I5"):
        conn.commit()


def test_i5_opening_leg_does_not_count_as_world(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "opening", [(t.chase, 150000), (t.opening, -150000)], t.salary)
    with pytest.raises(IntegrityError, match="I5"):
        conn.commit()


def test_i5_adding_a_category_later_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    txn = post(conn, t, "card_payment", [(t.amex, 20000), (t.chase, -20000)])
    conn.commit()
    conn.execute(
        text("UPDATE transactions SET category_id = :c WHERE id = :t"), {"c": t.food, "t": txn}
    )
    with pytest.raises(IntegrityError, match="I5"):
        conn.commit()


def test_i5_removing_a_category_later_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    txn = post(conn, t, "spend", [(t.world, 4000), (t.chase, -4000)], t.food)
    conn.commit()
    conn.execute(text("UPDATE transactions SET category_id = NULL WHERE id = :t"), {"t": txn})
    with pytest.raises(IntegrityError, match="I5"):
        conn.commit()


def test_i5_account_subtype_cannot_change(conn: Connection) -> None:
    # Turning a bank into `world` after the fact would silently break I5 for its history.
    t = make_tenant(conn)
    with pytest.raises(IntegrityError, match="I5"):
        conn.execute(text("UPDATE accounts SET subtype = 'cash' WHERE id = :a"), {"a": t.chase})


# --- I6: tenancy by composite foreign key (R-20) --------------------------------------------


def test_i6_posting_on_another_users_account_is_rejected(conn: Connection) -> None:
    a, b = make_tenant(conn), make_tenant(conn)
    with pytest.raises(IntegrityError, match="i6_postings_account_same_user"):
        post(conn, a, "spend", [(a.world, 4000), (b.chase, -4000)], a.food)


def test_i6_posting_under_another_users_transaction_is_rejected(conn: Connection) -> None:
    a, b = make_tenant(conn), make_tenant(conn)
    txn = insert(
        conn, "transactions", user_id=a.user, template="transfer", occurred_on="2026-03-01"
    )
    with pytest.raises(IntegrityError, match="i6_postings_transaction_same_user"):
        insert(
            conn, "postings", user_id=b.user, transaction_id=txn, account_id=b.chase, amount_minor=1
        )


def test_i6_another_users_category_is_rejected(conn: Connection) -> None:
    a, b = make_tenant(conn), make_tenant(conn)
    with pytest.raises(IntegrityError, match="i6_transactions_category_same_user"):
        post(conn, a, "spend", [(a.world, 4000), (a.chase, -4000)], b.food)


def test_i6_refund_of_another_users_spend_is_rejected(conn: Connection) -> None:
    a, b = make_tenant(conn), make_tenant(conn)
    spend = post(conn, b, "spend", [(b.world, 4000), (b.chase, -4000)], b.food)
    with pytest.raises(IntegrityError, match="i6_transactions_refund_same_user"):
        insert(
            conn,
            "transactions",
            user_id=a.user,
            template="refund",
            occurred_on="2026-03-02",
            category_id=a.food,
            refund_of_id=spend,
        )


def test_i6_another_users_counterparty_is_rejected(conn: Connection) -> None:
    a, b = make_tenant(conn), make_tenant(conn)
    mia = insert(conn, "counterparties", user_id=b.user, name="Mia")
    with pytest.raises(IntegrityError, match="i6_accounts_counterparty_same_user"):
        insert(
            conn,
            "accounts",
            user_id=a.user,
            name="Mia owes me",
            kind="ASSET",
            subtype="receivable",
            counterparty_id=mia,
        )


def test_i6_another_users_parent_category_is_rejected(conn: Connection) -> None:
    a, b = make_tenant(conn), make_tenant(conn)
    with pytest.raises(IntegrityError, match="i6_categories_parent_same_user"):
        insert(conn, "categories", user_id=a.user, name="Snacks", kind="expense", parent_id=b.food)


# --- I7: postings are append-only (R-19), except the tenant purge (§7) ----------------------


def test_i7_posting_update_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "spend", [(t.world, 4000), (t.chase, -4000)], t.food)
    conn.commit()
    with pytest.raises(IntegrityError, match="I7"):
        conn.execute(text("UPDATE postings SET amount_minor = 1 WHERE user_id = :u"), {"u": t.user})


def test_i7_posting_delete_is_rejected(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "spend", [(t.world, 4000), (t.chase, -4000)], t.food)
    conn.commit()
    with pytest.raises(IntegrityError, match="I7"):
        conn.execute(text("DELETE FROM postings WHERE user_id = :u"), {"u": t.user})


def test_i7_truncate_is_rejected(conn: Connection) -> None:
    with pytest.raises(IntegrityError, match="I7"):
        conn.execute(text("TRUNCATE postings CASCADE"))


def purge(conn: Connection, user: uuid.UUID) -> None:
    """The §7 tenant purge: lift I7 for one user, for this database transaction only."""
    conn.execute(text("SELECT set_config('fulcrum.purge_user_id', :u, true)"), {"u": str(user)})
    for table in ("postings", "transactions", "categories", "accounts", "counterparties", "users"):
        column = "id" if table == "users" else "user_id"
        conn.execute(text(f"DELETE FROM {table} WHERE {column} = :u"), {"u": user})


def test_i7_purge_deletes_one_tenant_and_nobody_else(conn: Connection) -> None:
    a, b = make_tenant(conn), make_tenant(conn)
    post(conn, a, "spend", [(a.world, 4000), (a.chase, -4000)], a.food)
    b_txn = post(conn, b, "spend", [(b.world, 4000), (b.chase, -4000)], b.food)
    conn.commit()

    purge(conn, a.user)
    with pytest.raises(IntegrityError, match="I7"):
        conn.execute(text("DELETE FROM postings WHERE user_id = :u"), {"u": b.user})
    conn.rollback()

    conn.execute(text("SELECT set_config('fulcrum.purge_user_id', :u, true)"), {"u": str(a.user)})
    with pytest.raises(IntegrityError, match="I7"):
        conn.execute(text("UPDATE postings SET amount_minor = 1 WHERE user_id = :u"), {"u": a.user})
    conn.rollback()

    purge(conn, a.user)
    conn.commit()
    gone = conn.execute(text("SELECT count(*) FROM postings WHERE user_id = :u"), {"u": a.user})
    assert gone.scalar_one() == 0
    assert posting_count(conn, b_txn) == 2


def test_i7_purge_permission_ends_with_its_transaction(conn: Connection) -> None:
    t = make_tenant(conn)
    post(conn, t, "spend", [(t.world, 4000), (t.chase, -4000)], t.food)
    conn.commit()
    conn.execute(text("SELECT set_config('fulcrum.purge_user_id', :u, true)"), {"u": str(t.user)})
    conn.commit()
    with pytest.raises(IntegrityError, match="I7"):
        conn.execute(text("DELETE FROM postings WHERE user_id = :u"), {"u": t.user})


# --- Shape rules from §3.3 the ledger depends on --------------------------------------------


def test_kind_must_match_subtype(conn: Connection) -> None:
    t = make_tenant(conn)
    with pytest.raises(IntegrityError, match="accounts_kind_matches_subtype"):
        insert(conn, "accounts", user_id=t.user, name="Bad", kind="ASSET", subtype="credit_card")


def test_one_world_and_one_opening_per_user(conn: Connection) -> None:
    t = make_tenant(conn)
    with pytest.raises(IntegrityError, match="accounts_one_outside_per_user"):
        insert(conn, "accounts", user_id=t.user, name="World 2", kind="EXTERNAL", subtype="world")


def test_person_accounts_need_a_counterparty_and_others_must_not_have_one(
    conn: Connection,
) -> None:
    t = make_tenant(conn)
    with pytest.raises(IntegrityError, match="accounts_counterparty_iff_person"):
        insert(conn, "accounts", user_id=t.user, name="Nobody", kind="ASSET", subtype="receivable")
    conn.rollback()

    t = make_tenant(conn)
    raj = insert(conn, "counterparties", user_id=t.user, name="Raj")
    with pytest.raises(IntegrityError, match="accounts_counterparty_iff_person"):
        insert(
            conn,
            "accounts",
            user_id=t.user,
            name="Bank",
            kind="ASSET",
            subtype="bank",
            counterparty_id=raj,
        )


def test_one_receivable_per_counterparty(conn: Connection) -> None:
    t = make_tenant(conn)
    raj = insert(conn, "counterparties", user_id=t.user, name="Raj")
    fields = {"user_id": t.user, "kind": "ASSET", "subtype": "receivable", "counterparty_id": raj}
    insert(conn, "accounts", name="Raj owes me", **fields)
    with pytest.raises(IntegrityError, match="accounts_one_per_counterparty"):
        insert(conn, "accounts", name="Raj owes me again", **fields)


def test_counterparty_names_are_unique_per_user_ignoring_case(conn: Connection) -> None:
    a, b = make_tenant(conn), make_tenant(conn)
    insert(conn, "counterparties", user_id=a.user, name="Raj")
    insert(conn, "counterparties", user_id=b.user, name="Raj")
    with pytest.raises(IntegrityError, match="counterparties_user_name_key"):
        insert(conn, "counterparties", user_id=a.user, name="RAJ")


def test_refund_link_only_on_refunds(conn: Connection) -> None:
    t = make_tenant(conn)
    spend = post(conn, t, "spend", [(t.world, 4000), (t.chase, -4000)], t.food)
    with pytest.raises(IntegrityError, match="transactions_refund_link_only_on_refund"):
        insert(
            conn,
            "transactions",
            user_id=t.user,
            template="spend",
            occurred_on="2026-03-02",
            category_id=t.food,
            refund_of_id=spend,
        )


# --- The migration itself -------------------------------------------------------------------


def test_migration_downgrades_cleanly_and_reapplies() -> None:
    # Re-upgrading fails on CREATE TYPE / CREATE FUNCTION if the downgrade left anything behind.
    url = recreate_database("fulcrum_migration_test")
    migrate(url, "upgrade", "head")
    migrate(url, "downgrade", "base")
    migrate(url, "upgrade", "head")
