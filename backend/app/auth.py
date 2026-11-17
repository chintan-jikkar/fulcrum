import uuid
from typing import Annotated

from fastapi import Depends, HTTPException
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_engine
from app.services.users import provision_user


def current_user_id(engine: Annotated[Engine, Depends(get_engine)]) -> uuid.UUID:
    """The caller's user id. Every route that touches a tenant's data depends on this.

    No auth provider is chosen yet (O-1), so this refuses everyone unless DEV_AUTH_SUB names a
    local development user (D-058). P2 replaces the body with JWT verification.
    """
    if settings.dev_auth_sub is None:
        raise HTTPException(status_code=401, detail="authentication is not configured")
    with Session(engine) as s:
        user_id = provision_user(s, settings.dev_auth_sub, "Dev owner", "America/New_York").id
        s.commit()
        return user_id
