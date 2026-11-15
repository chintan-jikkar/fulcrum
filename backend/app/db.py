from datetime import datetime
from functools import cache

from sqlalchemy import DateTime, Engine, Text, create_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


class Base(DeclarativeBase):
    # Match the migrations: every string column is text, every timestamp timestamptz (§6).
    type_annotation_map = {str: Text(), datetime: DateTime(timezone=True)}


@cache
def get_engine() -> Engine:
    return create_engine(settings.database_url)
