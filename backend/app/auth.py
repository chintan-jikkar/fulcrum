import uuid

from fastapi import HTTPException


def current_user_id() -> uuid.UUID:
    """The caller's user id. Every route that touches a tenant's data depends on this.

    No auth provider is chosen yet (O-1), so this refuses everyone. P2 replaces the body with
    JWT verification and `provision_user`.
    """
    raise HTTPException(status_code=401, detail="authentication is not configured")
