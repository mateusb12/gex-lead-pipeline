from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from source.shared.config import settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(settings.database_url, pool_pre_ping=True, pool_recycle=3600, future=True)


def ping_database() -> bool:
    with get_engine().connect() as connection:
        connection.execute(text("SELECT 1"))

    return True
