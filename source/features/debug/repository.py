from typing import Any

from sqlalchemy import text

from source.shared.db import get_engine


def list_raw_payloads(limit: int = 10) -> list[dict[str, Any]]:
    query = text(
        """
        SELECT
            id,
            correlation_id,
            gateway,
            received_at,
            headers,
            body_original,
            body_decrypted,
            error_reason
        FROM raw_payloads
        ORDER BY id DESC
        LIMIT :limit
        """
    )

    with get_engine().connect() as connection:
        result = connection.execute(query, {"limit": limit})
        return [dict(row) for row in result.mappings()]
