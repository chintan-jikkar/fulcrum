import uuid

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from app.models.ledger import Transaction
from app.seed import seed
from app.services import figures
from app.services.users import provision_user


def test_seed_fills_an_empty_book_once(engine: Engine) -> None:
    with Session(engine) as s:
        uid = provision_user(s, f"seed|{uuid.uuid4()}", "Seed", "America/New_York").id

        assert seed(s, uid) is True
        s.commit()  # the deferred database checks (I1, I2, I5) run on everything written
        count = select(func.count()).select_from(Transaction).where(Transaction.user_id == uid)
        written = s.scalar(count)
        # Openings 240000 + 500000 + 12000 - 31040, income 2 x 184000, spend 152758, refund 8900.
        assert figures.net_worth(s, uid) == 945102

        assert seed(s, uid) is False
        s.commit()
        assert s.scalar(count) == written == 29
