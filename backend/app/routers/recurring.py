"""Subscriptions and reminders (CLAUDE.md §12, D-079). The rules live in services/recurring.py."""

import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brands import BrandOut, brand_out, merchant_of
from app.idempotency import idempotent
from app.models.ledger import Account, Category, RecurringCadence, RecurringRule
from app.money import Money, money
from app.routers.deps import Db, IdempotencyKeyHeader, UserId
from app.routers.transactions import request_id
from app.services import figures, recurring

router = APIRouter(tags=["recurring"])


class RuleOut(BaseModel):
    id: uuid.UUID
    name: str
    amount: Money
    brand: BrandOut | None  # Netflix's logo for "Netflix" (D-066)
    funding_id: uuid.UUID
    funding_name: str
    category_id: uuid.UUID
    category_name: str
    cadence: RecurringCadence
    next_due_on: date
    days_until_due: int  # negative when the date has passed without a confirm or skip
    remind_days: int
    remind: bool  # active and within remind_days of the date, or past it
    is_active: bool


class RuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    amount_minor: StrictInt
    funding_id: uuid.UUID
    category_id: uuid.UUID
    cadence: RecurringCadence
    next_due_on: date
    remind_days: StrictInt = 2


class RuleEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    amount_minor: StrictInt | None = None
    funding_id: uuid.UUID | None = None
    category_id: uuid.UUID | None = None
    cadence: RecurringCadence | None = None
    next_due_on: date | None = None
    remind_days: StrictInt | None = None


class ConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: StrictInt | None = None  # when this bill differed from the usual
    occurred_on: date | None = None  # defaults to the due date


def _rules(s: Session, user_id: uuid.UUID, rule_id: uuid.UUID | None = None) -> list[RuleOut]:
    q = (
        select(RecurringRule, Account.name, Category.name)
        .join(Account, Account.id == RecurringRule.funding_id)
        .join(Category, Category.id == RecurringRule.category_id)
        .where(RecurringRule.user_id == user_id)
        .order_by(RecurringRule.next_due_on, RecurringRule.name)
    )
    if rule_id is not None:
        q = q.where(RecurringRule.id == rule_id)
    today = figures.today(s, user_id)
    out = []
    for rule, funding, category in s.execute(q):
        days = (rule.next_due_on - today).days
        out.append(
            RuleOut(
                id=rule.id,
                name=rule.name,
                amount=money(rule.amount_minor),
                brand=brand_out(merchant_of(rule.name)),
                funding_id=rule.funding_id,
                funding_name=funding,
                category_id=rule.category_id,
                category_name=category,
                cadence=rule.cadence,
                next_due_on=rule.next_due_on,
                days_until_due=days,
                remind_days=rule.remind_days,
                remind=rule.is_active and days <= rule.remind_days,
                is_active=rule.is_active,
            )
        )
    return out


def _one(s: Session, user_id: uuid.UUID, rule: RecurringRule) -> Any:
    return _rules(s, user_id, rule.id)[0].model_dump(mode="json")


@router.get("/recurring")
def list_rules(user_id: UserId, engine: Db) -> list[RuleOut]:
    """Every rule, cancelled ones included, soonest first."""
    with Session(engine) as s:
        return _rules(s, user_id)


@router.get("/reminders/upcoming")
def upcoming(user_id: UserId, engine: Db) -> list[RuleOut]:
    """What to remind the user of now: active rules within their window or past due (§12).
    The phone app (P6) turns this into notifications."""
    with Session(engine) as s:
        return [r for r in _rules(s, user_id) if r.remind]


@router.post("/recurring", status_code=201, response_model=RuleOut)
def create_rule(
    body: RuleIn, request: Request, user_id: UserId, engine: Db, key: IdempotencyKeyHeader
) -> JSONResponse:
    def work(s: Session) -> tuple[int, Any]:
        return 201, _one(s, user_id, recurring.create(s, user_id, **dict(body)))

    return idempotent(engine, user_id, key, request_id(request, body), work)


@router.post("/recurring/{rule_id}", response_model=RuleOut)
def edit_rule(
    rule_id: uuid.UUID,
    body: RuleEdit,
    request: Request,
    user_id: UserId,
    engine: Db,
    key: IdempotencyKeyHeader,
) -> JSONResponse:
    def work(s: Session) -> tuple[int, Any]:
        rule = recurring.edit(s, user_id, rule_id, **body.model_dump(exclude_none=True))
        return 200, _one(s, user_id, rule)

    return idempotent(engine, user_id, key, request_id(request, body), work)


@router.post("/recurring/{rule_id}/confirm", response_model=RuleOut)
def confirm_rule(
    rule_id: uuid.UUID,
    request: Request,
    user_id: UserId,
    engine: Db,
    key: IdempotencyKeyHeader,
    body: ConfirmIn | None = None,
) -> JSONResponse:
    """It was charged: write the spend and move to the next date."""
    edits = body or ConfirmIn()

    def work(s: Session) -> tuple[int, Any]:
        rule = recurring.confirm(s, user_id, rule_id, **edits.model_dump(exclude_none=True))
        return 200, _one(s, user_id, rule)

    return idempotent(engine, user_id, key, request_id(request, edits), work)


def _add_action(action: str) -> None:
    def post(
        rule_id: uuid.UUID,
        request: Request,
        user_id: UserId,
        engine: Db,
        key: IdempotencyKeyHeader,
    ) -> JSONResponse:
        def work(s: Session) -> tuple[int, Any]:
            if action == "skip":
                rule = recurring.skip(s, user_id, rule_id)
            else:
                rule = recurring.set_active(s, user_id, rule_id, action == "resume")
            return 200, _one(s, user_id, rule)

        return idempotent(engine, user_id, key, request_id(request), work)

    router.add_api_route(
        f"/recurring/{{rule_id}}/{action}",
        post,
        methods=["POST"],
        response_model=RuleOut,
        name=f"{action}_rule",
    )


for _action in ("skip", "cancel", "resume"):
    _add_action(_action)
