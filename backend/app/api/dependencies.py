"""Shared FastAPI dependencies.

Route handlers take these annotated types instead of importing settings or
the database module directly, which keeps them trivially overridable in
tests via ``app.dependency_overrides``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from pymongo.asynchronous.database import AsyncDatabase

from app.core.config import Settings, get_settings
from app.core.database import get_database


def get_db() -> AsyncDatabase:
    """Provide the application database to a route handler."""
    return get_database()


SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[AsyncDatabase, Depends(get_db)]
