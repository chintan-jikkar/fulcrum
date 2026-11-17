"""Transaction routes: one POST per template (§4), void, and the list the UI shows."""

import uuid
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brands import BrandOut, brand_out, merchant_of
from app.idempotency import idempotent
from app.models.ledger import (
    Account,
    AccountKind,
    AccountSubtype,
    Category,
    PaymentMethod,
    Posting,
    Transaction,
    TransactionTemplate,
)
from app.money import Money, money
from app.routers.deps import Db, IdempotencyKeyHeader, UserId
from app.services import ledger

router = APIRouter(prefix="/transactions", tags=["transactions"])


# --- Request bodies: the field names are the service functions' keyword arguments -------------


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: StrictInt  # never a float (§6)
    occurred_on: date
    memo: str = ""


class OpeningIn(_In):
    account_id: uuid.UUID


class _WithMethod(_In):
    method: PaymentMethod | None = None


class SpendIn(_WithMethod):
    funding_id: uuid.UUID
    category_id: uuid.UUID


class IncomeIn(_WithMethod):
    dest_id: uuid.UUID
    category_id: uuid.UUID


class RefundIn(_WithMethod):
    funding_id: uuid.UUID
    category_id: uuid.UUID | None = None
    refund_of_id: uuid.UUID | None = None


class TransferIn(_WithMethod):
    from_id: uuid.UUID
    to_id: uuid.UUID


class CardPaymentIn(_WithMethod):
    card_id: uuid.UUID
    funding_id: uuid.UUID


class FriendOutIn(_WithMethod):
    """lend, friend_repay, repay_friend: money moves between a person and `funding`."""

    counterparty_id: uuid.UUID
    funding_id: uuid.UUID


class BorrowIn(_WithMethod):
    counterparty_id: uuid.UUID
    dest_id: uuid.UUID


BODIES: dict[TransactionTemplate, type[_In]] = {
    TransactionTemplate.spend: SpendIn,
    TransactionTemplate.income: IncomeIn,
    TransactionTemplate.refund: RefundIn,
    TransactionTemplate.transfer: TransferIn,
    TransactionTemplate.card_payment: CardPaymentIn,
    TransactionTemplate.lend: FriendOutIn,
    TransactionTemplate.friend_repay: FriendOutIn,
    TransactionTemplate.borrow: BorrowIn,
    TransactionTemplate.repay_friend: FriendOutIn,
    TransactionTemplate.opening: OpeningIn,
}


class TransactionOut(BaseModel):
    """What a write returns: the transaction row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    template: TransactionTemplate
    occurred_on: date
    memo: str
    category_id: uuid.UUID | None
    method: PaymentMethod | None
    refund_of_id: uuid.UUID | None
    voided_at: datetime | None
    created_at: datetime


def _out(txn: Transaction) -> Any:
    return TransactionOut.model_validate(txn).model_dump(mode="json")


def request_id(request: Request, body: BaseModel | None = None) -> str:
    """What makes two requests the same for idempotency: method, path and validated body."""
    return f"{request.method} {request.url.path}\n{body.model_dump_json() if body else ''}"


def _add_template_route(template: TransactionTemplate, body_model: type[_In]) -> None:
    def post(
        body: body_model,  # type: ignore[valid-type]
        request: Request,
        user_id: UserId,
        engine: Db,
        key: IdempotencyKeyHeader,
    ) -> JSONResponse:
        def work(s: Session) -> tuple[int, Any]:
            # Looked up at call time so the service stays the single place the rules live.
            return 201, _out(getattr(ledger, template)(s, user_id, **dict(body)))

        return idempotent(engine, user_id, key, request_id(request, body), work)

    router.post(f"/{template}", status_code=201, response_model=TransactionOut, name=template)(post)


for _template, _body in BODIES.items():
    _add_template_route(_template, _body)


@router.post("/{transaction_id}/void", response_model=TransactionOut)
def void(
    transaction_id: uuid.UUID,
    request: Request,
    user_id: UserId,
    engine: Db,
    key: IdempotencyKeyHeader,
) -> JSONResponse:
    return idempotent(
        engine,
        user_id,
        key,
        request_id(request),
        lambda s: (200, _out(ledger.void(s, user_id, transaction_id))),
    )


# --- The list -------------------------------------------------------------------------------


class CategoryRef(BaseModel):
    id: uuid.UUID
    name: str


class Leg(BaseModel):
    account_id: uuid.UUID
    account_name: str
    subtype: AccountSubtype
    amount: Money  # signed; positive is a debit


class TransactionRow(BaseModel):
    id: uuid.UUID
    template: TransactionTemplate
    occurred_on: date
    memo: str
    method: PaymentMethod | None
    category: CategoryRef | None
    refund_of_id: uuid.UUID | None
    voided_at: datetime | None
    brand: BrandOut | None  # a known merchant in the memo (D-066)
    amount: Money  # X, always positive
    net: Money  # change in net worth: negative for a spend, zero for a transfer
    legs: list[Leg]


@router.get("")
def list_transactions(user_id: UserId, engine: Db, limit: int = 200) -> list[TransactionRow]:
    """Newest first, voided ones included (§6: a void stays visible in history)."""
    with Session(engine) as s:
        txns = s.scalars(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.occurred_on.desc(), Transaction.created_at.desc())
            .limit(max(1, min(limit, 1000)))
        ).all()
        legs: dict[uuid.UUID, list[tuple[Account, int]]] = {t.id: [] for t in txns}
        q = (
            select(Posting.transaction_id, Account, Posting.amount_minor)
            .join(Account, Account.id == Posting.account_id)
            .where(Posting.user_id == user_id, Posting.transaction_id.in_(legs))
            .order_by(Posting.amount_minor.desc())
        )
        for txn_id, acct, amount in s.execute(q):
            legs[txn_id].append((acct, amount))
        names = dict(
            s.execute(select(Category.id, Category.name).where(Category.user_id == user_id)).all()
        )
        return [
            TransactionRow(
                id=t.id,
                template=t.template,
                occurred_on=t.occurred_on,
                memo=t.memo,
                method=t.method,
                category=(
                    CategoryRef(id=t.category_id, name=names[t.category_id])
                    if t.category_id
                    else None
                ),
                refund_of_id=t.refund_of_id,
                voided_at=t.voided_at,
                brand=brand_out(merchant_of(t.memo)),
                amount=money(max(n for _, n in legs[t.id])),
                net=money(sum(n for a, n in legs[t.id] if a.kind is not AccountKind.EXTERNAL)),
                legs=[
                    Leg(account_id=a.id, account_name=a.name, subtype=a.subtype, amount=money(n))
                    for a, n in legs[t.id]
                ],
            )
            for t in txns
        ]
