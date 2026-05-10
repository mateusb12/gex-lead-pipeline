from typing import Any

from sqlalchemy import select

from source.shared.db import get_engine
from source.shared.tables import raw_payloads


def list_raw_payloads(limit: int = 10) -> list[dict[str, Any]]:
    statement = (
        select(
            raw_payloads.c.id,
            raw_payloads.c.correlation_id,
            raw_payloads.c.gateway,
            raw_payloads.c.received_at,
            raw_payloads.c.headers,
            raw_payloads.c.body_original,
            raw_payloads.c.body_decrypted,
            raw_payloads.c.error_reason,
        )
        .order_by(raw_payloads.c.id.desc())
        .limit(limit)
    )

    with get_engine().connect() as connection:
        result = connection.execute(statement)
        return [dict(row) for row in result.mappings().all()]
