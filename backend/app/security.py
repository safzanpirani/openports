from __future__ import annotations

from fastapi import Header, HTTPException

from .config import settings


def require_admin(authorization: str | None = Header(default=None)) -> None:
    """If ADMIN_TOKEN is set, require `Authorization: Bearer <token>`.

    If ADMIN_TOKEN is not set, this is a no-op.
    """

    if not settings.ADMIN_TOKEN:
        return

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.ADMIN_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")
