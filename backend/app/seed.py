"""Fictional demo data for local development (CLAUDE.md §6: never real names or balances).

    DEV_AUTH_SUB=dev-owner uv run python -m app.seed

Fills the DEV_AUTH_SUB user's book through the same service functions the API uses, with dates
counted back from today so the current month always has activity. Does nothing if the user
already has an account.
"""

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_engine
from app.models.ledger import Account, AccountKind, AccountSubtype, Category, PaymentMethod
from app.services import figures, ledger
from app.services.users import provision_user

Sub = AccountSubtype


def seed(s: Session, user_id: uuid.UUID) -> bool:
    """Returns False, having written nothing, if the user already has accounts."""
    has_accounts = s.scalars(
        select(Account.id)
        .where(Account.user_id == user_id, Account.kind != AccountKind.EXTERNAL)
        .limit(1)
    ).first()
    if has_accounts:
        return False

    today = figures.today(s, user_id)

    def ago(days: int) -> date:
        return today - timedelta(days=days)

    rows = s.execute(select(Category.name, Category.id).where(Category.user_id == user_id))
    cat: dict[str, uuid.UUID] = {name: category_id for name, category_id in rows}

    def account(name: str, subtype: AccountSubtype, opening: int, **meta: int) -> uuid.UUID:
        acct = ledger.create_account(s, user_id, name=name, subtype=subtype, meta=meta)
        if opening:
            ledger.opening(
                s, user_id, account_id=acct.id, amount_minor=opening, occurred_on=ago(40)
            )
        return acct.id

    checking = account("Harbor Checking", Sub.bank, 240000)
    savings = account("Harbor Savings", Sub.bank, 500000)
    wallet = account("Wallet", Sub.cash, 12000)
    juniper = account("Juniper Card", Sub.credit_card, 31040, limit_minor=500000)
    atlas = account("Atlas Rewards", Sub.credit_card, 0, limit_minor=200000)
    sam = ledger.create_counterparty(s, user_id, name="Sam").id
    priya = ledger.create_counterparty(s, user_id, name="Priya").id

    def spend(days: int, amount: int, funding: uuid.UUID, category: str, memo: str) -> uuid.UUID:
        return ledger.spend(
            s,
            user_id,
            funding_id=funding,
            amount_minor=amount,
            category_id=cat[category],
            memo=memo,
            occurred_on=ago(days),
        ).id

    ledger.income(
        s,
        user_id,
        dest_id=checking,
        amount_minor=184000,
        category_id=cat["Salary"],
        memo="Paycheck",
        occurred_on=ago(28),
    )
    spend(27, 95000, checking, "Housing", "Rent")
    spend(26, 6240, juniper, "Food", "Trader Joe's")
    spend(24, 1599, juniper, "Subscriptions", "Spotify")
    spend(23, 4200, checking, "Utilities", "Electric bill")
    ledger.transfer(
        s,
        user_id,
        from_id=checking,
        to_id=wallet,
        amount_minor=10000,
        memo="ATM",
        occurred_on=ago(22),
    )
    spend(21, 1850, wallet, "Food", "Subway")
    spend(19, 3300, atlas, "Transport", "MTA OMNY")
    headphones = spend(17, 8900, juniper, "Shopping", "Best Buy headphones")
    ledger.income(
        s,
        user_id,
        dest_id=checking,
        amount_minor=184000,
        category_id=cat["Salary"],
        memo="Paycheck",
        occurred_on=ago(14),
    )
    ledger.card_payment(
        s, user_id, card_id=juniper, funding_id=checking, amount_minor=31040, occurred_on=ago(13)
    )
    spend(12, 7415, juniper, "Food", "Whole Foods")
    ledger.lend(
        s,
        user_id,
        counterparty_id=sam,
        funding_id=juniper,
        amount_minor=3200,
        memo="Sam's half of dinner",
        method=PaymentMethod.card,
        occurred_on=ago(11),
    )
    spend(11, 3200, juniper, "Food", "Dinner, my half")
    ledger.refund(
        s,
        user_id,
        funding_id=juniper,
        amount_minor=8900,
        refund_of_id=headphones,
        memo="Best Buy return",
        occurred_on=ago(9),
    )
    ledger.borrow(
        s,
        user_id,
        counterparty_id=priya,
        dest_id=wallet,
        amount_minor=4000,
        memo="Cash for the concert",
        method=PaymentMethod.cash,
        occurred_on=ago(8),
    )
    spend(8, 4000, wallet, "Entertainment", "Concert ticket")
    ledger.transfer(
        s,
        user_id,
        from_id=checking,
        to_id=savings,
        amount_minor=30000,
        memo="Savings",
        occurred_on=ago(7),
    )
    spend(6, 2450, atlas, "Transport", "Uber home")
    ledger.friend_repay(
        s,
        user_id,
        counterparty_id=sam,
        funding_id=checking,
        amount_minor=2000,
        memo="Sam paid part back",
        method=PaymentMethod.bank_transfer,
        occurred_on=ago(5),
    )
    spend(4, 5380, juniper, "Food", "Costco")
    spend(3, 1299, juniper, "Subscriptions", "Netflix")
    spend(2, 3600, checking, "Health", "CVS pharmacy")
    spend(1, 1450, wallet, "Food", "Starbucks")
    spend(0, 2875, atlas, "Food", "Chipotle")
    return True


def main() -> None:
    if settings.dev_auth_sub is None:
        raise SystemExit("Set DEV_AUTH_SUB (for example dev-owner) to choose the user to seed.")
    with Session(get_engine()) as s:
        user = provision_user(s, settings.dev_auth_sub, "Dev owner", "America/New_York")
        wrote = seed(s, user.id)
        s.commit()
    print("Seeded demo data." if wrote else "User already has accounts; nothing written.")


if __name__ == "__main__":
    main()
