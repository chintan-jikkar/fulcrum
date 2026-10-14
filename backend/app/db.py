from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# create_engine is lazy: nothing connects until first use, so importing this needs no database.
engine = create_engine(settings.database_url, pool_pre_ping=True)


class Base(DeclarativeBase):
    pass
