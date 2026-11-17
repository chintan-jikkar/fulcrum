from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.engine import make_url

from app.config import settings

if TYPE_CHECKING:
    from tests.test_api import Caller

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"


def recreate_database(name: str) -> str:
    """Drop and recreate an empty database on the DATABASE_URL server. Returns its URL."""
    base = make_url(settings.database_url)
    admin = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    return base.set(database=name).render_as_string(hide_password=False)


def migrate(url: str, direction: str, revision: str) -> None:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url)
    getattr(command, direction)(config, revision)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    # A fresh database per run, so tests may commit and never need cleanup. Each test makes its
    # own users, so committed rows from one test cannot affect another.
    url = recreate_database(f"{make_url(settings.database_url).database}_test")
    migrate(url, "upgrade", "head")
    eng = create_engine(url)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    with engine.connect() as c:
        yield c
        c.rollback()


# The HTTP tenant fixtures, shared by test_api and test_settings.
@pytest.fixture
def api(engine: Engine) -> Iterator[TestClient]:
    from tests.test_idempotency import client_for

    with client_for(engine) as c:
        yield c


@pytest.fixture
def me(api: TestClient, engine: Engine) -> "Caller":
    from tests.test_api import Caller

    return Caller(api, engine)
