"""Transaction routes. Spend and void come first; the other templates follow the same shape."""

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy import Engine

from app.auth import current_user_id
from app.db import get_engine
from app.idempotency import idempotent
from app.models.ledger import PaymentMethod, Transaction, TransactionTemplate
from app.services import ledger

router = APIRouter(prefix="/transactions")

UserId = Annotated[uuid.UUID, Depends(current_user_id)]
Db = Annotated[Engine, Depends(get_engine)]
IdempotencyKeyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)]


class SpendIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    funding_id: uuid.UUID
    amount_minor: StrictInt  # never a float (§6)
    category_id: uuid.UUID
    occurred_on: date
    memo: str = ""
    method: PaymentMethod | None = None


class TransactionOut(BaseModel):
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


def _request(request: Request, body: str = "") -> str:
    return f"{request.method} {request.url.path}\n{body}"


@router.post("/spend", status_code=201, response_model=TransactionOut)
def spend(
    body: SpendIn, request: Request, user_id: UserId, engine: Db, key: IdempotencyKeyHeader
) -> JSONResponse:
    return idempotent(
        engine,
        user_id,
        key,
        _request(request, body.model_dump_json()),
        lambda s: (201, _out(ledger.spend(s, user_id, **dict(body)))),
    )


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
        _request(request),
        lambda s: (200, _out(ledger.void(s, user_id, transaction_id))),
    )
