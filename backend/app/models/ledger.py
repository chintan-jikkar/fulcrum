"""SQLAlchemy models for the ledger tables (CLAUDE.md §3).

The migrations in alembic/versions are the source of truth; these classes only describe them for
the ORM. Constraints, partial indexes and triggers (I1-I3, I5-I7, D-034) live in the migrations
alone and are not repeated here. tests/test_models.py fails if a column drifts.

Composite foreign keys (I6) are not declared either: nothing here uses ORM relationships yet,
and the database rejects a cross-tenant reference whether or not the model knows about it.
"""

import uuid
from datetime import date, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CHAR, BigInteger, Enum, ForeignKey, SmallInteger, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Postgres enum types are created by migration 0001. Member names equal their database values.


class AccountKind(StrEnum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EXTERNAL = "EXTERNAL"


class AccountSubtype(StrEnum):
    cash = "cash"
    bank = "bank"
    credit_card = "credit_card"
    receivable = "receivable"
    payable = "payable"
    world = "world"
    opening = "opening"


class CategoryKind(StrEnum):
    expense = "expense"
    income = "income"


class TransactionTemplate(StrEnum):
    spend = "spend"
    income = "income"
    refund = "refund"
    transfer = "transfer"
    card_payment = "card_payment"
    lend = "lend"
    friend_repay = "friend_repay"
    borrow = "borrow"
    repay_friend = "repay_friend"
    opening = "opening"


class PaymentMethod(StrEnum):
    cash = "cash"
    bank_transfer = "bank_transfer"
    card = "card"
    other = "other"


def _id() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, server_default=func.gen_random_uuid())


def _user_id() -> Mapped[uuid.UUID]:
    return mapped_column(ForeignKey("users.id"))


def _created_at() -> Mapped[datetime]:
    return mapped_column(server_default=func.now())


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = _id()
    auth_sub: Mapped[str] = mapped_column(unique=True)
    display_name: Mapped[str]
    timezone: Mapped[str]  # IANA name; defines "today" and month boundaries
    created_at: Mapped[datetime] = _created_at()


class Counterparty(Base):
    __tablename__ = "counterparties"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _user_id()
    name: Mapped[str]
    contact: Mapped[str | None]
    is_active: Mapped[bool] = mapped_column(server_default="true")
    created_at: Mapped[datetime] = _created_at()


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _user_id()
    name: Mapped[str]
    kind: Mapped[AccountKind] = mapped_column(Enum(AccountKind, name="account_kind"))
    subtype: Mapped[AccountSubtype] = mapped_column(Enum(AccountSubtype, name="account_subtype"))
    currency: Mapped[str] = mapped_column(CHAR(3), server_default="USD")
    counterparty_id: Mapped[uuid.UUID | None]
    is_active: Mapped[bool] = mapped_column(server_default="true")
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = _created_at()


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _user_id()
    name: Mapped[str]
    icon: Mapped[str | None]
    color: Mapped[str | None]
    kind: Mapped[CategoryKind] = mapped_column(Enum(CategoryKind, name="category_kind"))
    parent_id: Mapped[uuid.UUID | None]
    is_archived: Mapped[bool] = mapped_column(server_default="false")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID] = _user_id()
    template: Mapped[TransactionTemplate] = mapped_column(
        Enum(TransactionTemplate, name="transaction_template")
    )
    occurred_on: Mapped[date]  # local calendar date, no timezone
    memo: Mapped[str] = mapped_column(server_default="")
    category_id: Mapped[uuid.UUID | None]
    method: Mapped[PaymentMethod | None] = mapped_column(Enum(PaymentMethod, name="payment_method"))
    refund_of_id: Mapped[uuid.UUID | None]
    voided_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = _created_at()


class Posting(Base):
    __tablename__ = "postings"

    id: Mapped[uuid.UUID] = _id()
    user_id: Mapped[uuid.UUID]
    transaction_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    amount_minor: Mapped[int] = mapped_column(BigInteger)  # signed; positive = debit


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    key: Mapped[str] = mapped_column(primary_key=True)
    request_hash: Mapped[str]
    response_status: Mapped[int | None] = mapped_column(SmallInteger)  # null while in flight
    response_body: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created_at()
