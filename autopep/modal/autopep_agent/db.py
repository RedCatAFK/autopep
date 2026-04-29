from __future__ import annotations

from typing import Any

import psycopg


async def connect(database_url: str) -> Any:
    return await psycopg.AsyncConnection.connect(database_url)
