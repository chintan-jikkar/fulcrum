from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    # Match the migrations: every string column is text, every timestamp timestamptz (§6).
    type_annotation_map = {str: Text(), datetime: DateTime(timezone=True)}
