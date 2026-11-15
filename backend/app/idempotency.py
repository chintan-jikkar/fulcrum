"""Idempotency-Key handling for every POST (CLAUDE.md §6; D-017, D-042, D-056).

A request first claims its key in its own committed transaction, so a replay that arrives while
it is still running sees the claim and gets 409. The work and the stored response then commit
together: the response exists if and only if the work does.
"""

import hashlib
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from fastapi.responses import JSONResponse
from sqlalchemy import Engine, delete, func, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.ledger import IdempotencyKey
from app.services.ledger import Conflict, LedgerError, NotFound, RuleViolation

RETENTION = timedelta(days=7)

Work = Callable[[Session], tuple[int, Any]]


def _error(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def _ledger_error(e: LedgerError) -> tuple[int, dict[str, str]]:
    # D-047: the class gives the status, `rule` gives the machine-readable code.
    if isinstance(e, NotFound):
        return 404, _error("not_found", str(e))
    if isinstance(e, Conflict):
        return 409, _error("conflict", str(e))
    if isinstance(e, RuleViolation):
        return 422, _error(e.rule, str(e))
    raise e


def idempotent(
    engine: Engine, user_id: uuid.UUID, key: str, request: str, work: Work
) -> JSONResponse:
    """Run `work` at most once for this user's `key` and return its response, stored for replays.

    `request` identifies the request (method, path and body); the same key with a different one
    is 409. `work` gets a session, does its writes without committing, and returns
    (status, JSON body). A LedgerError becomes the response and is stored like any other.
    """
    mine = (IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
    request_hash = hashlib.sha256(request.encode()).hexdigest()

    with Session(engine) as s:
        # Expired keys go first, so a key older than the retention window is new again.
        s.execute(
            delete(IdempotencyKey).where(
                IdempotencyKey.user_id == user_id,
                IdempotencyKey.created_at < func.now() - RETENTION,
            )
        )
        # A concurrent claim of the same key makes this insert wait for that claim's commit.
        claimed = s.scalar(
            insert(IdempotencyKey)
            .values(user_id=user_id, key=key, request_hash=request_hash)
            .on_conflict_do_nothing()
            .returning(IdempotencyKey.key)
        )
        s.commit()
        if claimed is None:
            row = s.get(IdempotencyKey, (user_id, key))
            if row is not None and row.request_hash != request_hash:
                return JSONResponse(
                    _error("idempotency_key_reused", "this key was used for a different request"),
                    409,
                )
            if row is None or row.response_status is None:
                return JSONResponse(
                    _error("idempotency_in_flight", "the first request is still running"), 409
                )
            return JSONResponse(row.response_body, row.response_status)

    with Session(engine) as s:
        try:
            try:
                status, body = work(s)
            except LedgerError as e:
                s.rollback()
                status, body = _ledger_error(e)
            s.execute(
                update(IdempotencyKey)
                .where(*mine)
                .values(response_status=status, response_body=body)
            )
            s.commit()
        except BaseException:
            # A crash wrote nothing, so free the key for a retry. Only while it is still in
            # flight: if the commit did land, the stored response stays and the retry replays it.
            # ponytail: a killed process leaves its key in flight, 409 for up to 7 days; the
            # client retries with a new key, which is safe because nothing was written.
            s.rollback()
            s.execute(delete(IdempotencyKey).where(*mine, IdempotencyKey.response_status.is_(None)))
            s.commit()
            raise
    return JSONResponse(body, status)
