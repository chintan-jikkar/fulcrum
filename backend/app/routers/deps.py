import uuid
from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy import Engine

from app.auth import current_user_id
from app.db import get_engine

UserId = Annotated[uuid.UUID, Depends(current_user_id)]
Db = Annotated[Engine, Depends(get_engine)]
IdempotencyKeyHeader = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)]
