from datetime import datetime

from sqlalchemy import DateTime, Text, create_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# create_engine is lazy: nothing connects until first use, so importing this needs no database.
engine = create_engine(settings.database_url, pool_pre_ping=True)


class Base(DeclarativeBase):
    # Match the migrations: every string column is text, every timestamp timestamptz (§6).
    type_annotation_map = {str: Text(), datetime: DateTime(timezone=True)}
