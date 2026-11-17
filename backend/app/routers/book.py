"""Accounts, people, categories and the summary figures (§3, §5)."""

import calendar
import uuid
from datetime import date
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.brands import BrandOut, bank_of, brand_out, merchant_of
from app.idempotency import idempotent
from app.models.ledger import (
    Account,
    AccountKind,
    AccountSubtype,
    Category,
    CategoryKind,
    Counterparty,
    User,
)
from app.money import Money, money, percent
from app.routers.deps import Db, IdempotencyKeyHeader, UserId
from app.routers.transactions import request_id
from app.services import figures, ledger, users

router = APIRouter(tags=["book"])

SUBTYPE_ORDER = list(AccountSubtype)


def month_bounds(day: date) -> tuple[date, date]:
    """First and last day of the calendar month containing `day`."""
    return day.replace(day=1), day.replace(day=calendar.monthrange(day.year, day.month)[1])


# --- Accounts -------------------------------------------------------------------------------


class CardCredit(BaseModel):
    limit: Money | None
    available: Money | None
    utilization_bps: int | None
    utilization_display: str | None
    due_day: int | None
    statement_day: int | None
    next_due_on: date | None  # today in the user's timezone counts as not yet passed
    days_until_due: int | None  # 0 means due today
    design: str | None  # the drawn design the user picked for this card (D-072)


class AccountOut(BaseModel):
    id: uuid.UUID
    name: str
    subtype: AccountSubtype
    kind: AccountKind
    is_active: bool
    counterparty_id: uuid.UUID | None
    balance: Money  # an asset's balance, or what a liability owes (§3.9)
    last4: str | None  # the only part of a card or account number Parity keeps (D-071)
    credit: CardCredit | None  # active credit cards only
    brand: BrandOut | None  # a known bank in the name (D-066)


class _Details(BaseModel):
    """Display details (D-071). extra="forbid" means a full card number or security code sent
    by mistake is refused outright, never stored."""

    model_config = ConfigDict(extra="forbid")

    limit_minor: StrictInt | None = None
    last4: str | None = None
    due_day: StrictInt | None = None
    statement_day: StrictInt | None = None
    card_design: str | None = None


class AccountIn(_Details):
    name: str
    subtype: AccountSubtype


def _opt(minor: int | None) -> Money | None:
    return None if minor is None else money(minor)


def _pct(bps: int | None) -> str | None:
    return None if bps is None else percent(bps)


def _account_out(acct: Account, raw: int, credit: figures.Credit | None, today: date) -> AccountOut:
    due_day = acct.meta.get("due_day")
    due = None if due_day is None else figures.next_due(today, due_day)
    return AccountOut(
        id=acct.id,
        name=acct.name,
        subtype=acct.subtype,
        kind=acct.kind,
        is_active=acct.is_active,
        counterparty_id=acct.counterparty_id,
        brand=brand_out(bank_of(acct.name)) if acct.counterparty_id is None else None,
        balance=money(-raw if acct.kind is AccountKind.LIABILITY else raw),
        last4=acct.meta.get("last4"),
        credit=None
        if credit is None
        else CardCredit(
            limit=_opt(credit.limit_minor),
            available=_opt(credit.available),
            utilization_bps=credit.utilization_bps,
            utilization_display=_pct(credit.utilization_bps),
            due_day=due_day,
            statement_day=acct.meta.get("statement_day"),
            next_due_on=due,
            days_until_due=None if due is None else (due - today).days,
            design=acct.meta.get("card_design"),
        ),
    )


@router.get("/accounts")
def list_accounts(user_id: UserId, engine: Db) -> list[AccountOut]:
    """Every account the user sees, with today's balance. World and opening never appear."""
    with Session(engine) as s:
        raw = figures.balances(s, user_id)
        cards, _ = figures.credit(s, user_id)
        accounts = s.scalars(
            select(Account).where(Account.user_id == user_id, Account.kind != AccountKind.EXTERNAL)
        ).all()
        accounts = sorted(accounts, key=lambda a: (SUBTYPE_ORDER.index(a.subtype), a.name))
        today = figures.today(s, user_id)
        return [_account_out(a, raw[a.id], cards.get(a.id), today) for a in accounts]


@router.post("/accounts", status_code=201, response_model=AccountOut)
def create_account(
    body: AccountIn, request: Request, user_id: UserId, engine: Db, key: IdempotencyKeyHeader
) -> JSONResponse:
    def work(s: Session) -> tuple[int, Any]:
        meta = body.model_dump(exclude_none=True, exclude={"name", "subtype"})
        acct = ledger.create_account(s, user_id, name=body.name, subtype=body.subtype, meta=meta)
        cards, _ = figures.credit(s, user_id)
        out = _account_out(acct, 0, cards.get(acct.id), figures.today(s, user_id))
        return 201, out.model_dump(mode="json")

    return idempotent(engine, user_id, key, request_id(request, body), work)


class AccountEdit(_Details):
    name: str | None = None


def _account_now(s: Session, user_id: uuid.UUID, acct: Account) -> dict[str, Any]:
    cards, _ = figures.credit(s, user_id)
    raw = figures.balances(s, user_id)[acct.id]
    return _account_out(acct, raw, cards.get(acct.id), figures.today(s, user_id)).model_dump(
        mode="json"
    )


@router.post("/accounts/{account_id}", response_model=AccountOut)
def edit_account(
    account_id: uuid.UUID,
    body: AccountEdit,
    request: Request,
    user_id: UserId,
    engine: Db,
    key: IdempotencyKeyHeader,
) -> JSONResponse:
    """Rename an account, or change a card's limit (the settings screen)."""

    def work(s: Session) -> tuple[int, Any]:
        acct = ledger.edit_account(s, user_id, account_id, **body.model_dump(exclude_none=True))
        return 200, _account_now(s, user_id, acct)

    return idempotent(engine, user_id, key, request_id(request, body), work)


def _add_archive_route(action: str) -> None:
    def post(
        account_id: uuid.UUID,
        request: Request,
        user_id: UserId,
        engine: Db,
        key: IdempotencyKeyHeader,
    ) -> JSONResponse:
        def work(s: Session) -> tuple[int, Any]:
            acct = getattr(ledger, f"{action}_account")(s, user_id, account_id)
            return 200, _account_now(s, user_id, acct)

        return idempotent(engine, user_id, key, request_id(request), work)

    router.add_api_route(
        f"/accounts/{{account_id}}/{action}",
        post,
        methods=["POST"],
        response_model=AccountOut,
        name=f"{action}_account",
    )


for _action in ("archive", "unarchive"):
    _add_archive_route(_action)


# --- Profile ----------------------------------------------------------------------------------


class Profile(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    display_name: str
    timezone: str


class ProfileEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    timezone: str | None = None


@router.get("/me")
def get_profile(user_id: UserId, engine: Db) -> Profile:
    with Session(engine) as s:
        return Profile.model_validate(s.get_one(User, user_id))


@router.post("/me", response_model=Profile)
def edit_profile(
    body: ProfileEdit, request: Request, user_id: UserId, engine: Db, key: IdempotencyKeyHeader
) -> JSONResponse:
    def work(s: Session) -> tuple[int, Any]:
        user = users.update_profile(s, user_id, **body.model_dump())
        return 200, Profile.model_validate(user).model_dump(mode="json")

    return idempotent(engine, user_id, key, request_id(request, body), work)


# --- People and categories ------------------------------------------------------------------


class CounterpartyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class CounterpartyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str


@router.get("/counterparties")
def list_counterparties(user_id: UserId, engine: Db) -> list[CounterpartyOut]:
    with Session(engine) as s:
        q = select(Counterparty).where(Counterparty.user_id == user_id).order_by(Counterparty.name)
        return [CounterpartyOut.model_validate(p) for p in s.scalars(q)]


@router.post("/counterparties", status_code=201, response_model=CounterpartyOut)
def create_counterparty(
    body: CounterpartyIn, request: Request, user_id: UserId, engine: Db, key: IdempotencyKeyHeader
) -> JSONResponse:
    def work(s: Session) -> tuple[int, Any]:
        person = ledger.create_counterparty(s, user_id, name=body.name)
        return 201, CounterpartyOut.model_validate(person).model_dump(mode="json")

    return idempotent(engine, user_id, key, request_id(request, body), work)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    kind: CategoryKind
    parent_id: uuid.UUID | None
    is_archived: bool


@router.get("/categories")
def list_categories(user_id: UserId, engine: Db) -> list[CategoryOut]:
    with Session(engine) as s:
        q = select(Category).where(Category.user_id == user_id).order_by(Category.name)
        return [CategoryOut.model_validate(c) for c in s.scalars(q)]


# --- Summary --------------------------------------------------------------------------------


class CreditSummary(BaseModel):
    limit: Money | None
    owed: Money
    available: Money | None
    utilization_bps: int | None
    utilization_display: str | None


class CategoryTotal(BaseModel):
    id: uuid.UUID
    name: str
    kind: CategoryKind
    parent_id: uuid.UUID | None
    total: Money
    share_bps: int  # share of the month's total for its kind, 0 to 10000; the UI's bar width


class MerchantTotal(BaseModel):
    key: str
    name: str
    color: str
    mark: str
    total: Money  # spend less refunds this month
    count: int  # transactions, refunds included


class MonthSummary(BaseModel):
    start: date
    end: date
    expense: Money
    income: Money
    categories: list[CategoryTotal]  # largest first
    merchants: list[MerchantTotal]  # known brands only, largest first


class FriendPosition(BaseModel):
    counterparty_id: uuid.UUID
    name: str
    position: Money  # positive: they owe you
    amount: Money  # the same without the sign, for "you owe $25.00"


class Summary(BaseModel):
    as_of: date
    net_worth: Money
    credit: CreditSummary
    month: MonthSummary
    friends: list[FriendPosition]


def _share(part: int, whole: int) -> int:
    """part / whole in basis points, rounded half up, kept within 0 to 10000. Refunds can push
    a category below zero or the whole below one of its parts; the bar just stops at the ends."""
    if whole <= 0:
        return 0
    return min(figures.utilization_bps(part, whole) or 0, 10000)


def _merchants(rows: list[tuple[str, int]]) -> list[MerchantTotal]:
    totals: dict[str, tuple[Any, int, int]] = {}
    for memo, amount in rows:
        brand = merchant_of(memo)
        if brand:
            _, total, count = totals.get(brand.key, (brand, 0, 0))
            totals[brand.key] = (brand, total + amount, count + 1)
    return sorted(
        (
            MerchantTotal(
                key=b.key, name=b.name, color=b.color, mark=b.mark, total=money(t), count=n
            )
            for b, t, n in totals.values()
        ),
        key=lambda m: (-m.total.minor, m.name),
    )


@router.get("/summary")
def summary(user_id: UserId, engine: Db) -> Summary:
    """The dashboard figures as of today in the user's timezone (§5)."""
    with Session(engine) as s:
        today = figures.today(s, user_id)
        start, end = month_bounds(today)
        _, total = figures.credit(s, user_id, today)
        totals = figures.category_totals(s, user_id, start=start, end=end)
        categories = s.scalars(select(Category).where(Category.id.in_(totals.by_category))).all()
        positions = figures.friend_positions(s, user_id, today)
        people = s.scalars(
            select(Counterparty).where(Counterparty.user_id == user_id).order_by(Counterparty.name)
        ).all()
        return Summary(
            as_of=today,
            net_worth=money(figures.net_worth(s, user_id, today)),
            credit=CreditSummary(
                limit=_opt(total.limit_minor),
                owed=money(total.owed),
                available=_opt(total.available),
                utilization_bps=total.utilization_bps,
                utilization_display=_pct(total.utilization_bps),
            ),
            month=MonthSummary(
                start=start,
                end=end,
                expense=money(totals.expense),
                income=money(totals.income),
                categories=sorted(
                    (
                        CategoryTotal(
                            id=c.id,
                            name=c.name,
                            kind=c.kind,
                            parent_id=c.parent_id,
                            total=money(totals.by_category[c.id]),
                            share_bps=_share(
                                totals.by_category[c.id],
                                totals.expense if c.kind is CategoryKind.expense else totals.income,
                            ),
                        )
                        for c in categories
                    ),
                    key=lambda c: (-c.total.minor, c.name),
                ),
                merchants=_merchants(figures.expense_by_memo(s, user_id, start=start, end=end)),
            ),
            friends=[
                FriendPosition(
                    counterparty_id=p.id,
                    name=p.name,
                    position=money(positions[p.id]),
                    amount=money(abs(positions[p.id])),
                )
                for p in people
            ],
        )
