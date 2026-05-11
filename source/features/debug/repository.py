from typing import Any

from sqlalchemy import select, text

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


DEBUG_CLEANUP_TABLES = (
    "distribution_status",
    "lead_events",
    "orders",
    "leads",
    "webhook_idempotency_keys",
    "lead_dead_letter",
    "raw_payloads",
)


def clear_database_tables() -> dict[str, Any]:
    deleted_by_table: dict[str, int] = {}

    with get_engine().begin() as connection:
        for table_name in DEBUG_CLEANUP_TABLES:
            result = connection.execute(text(f"DELETE FROM `{table_name}`"))
            deleted_by_table[table_name] = int(result.rowcount or 0)
            connection.execute(text(f"ALTER TABLE `{table_name}` AUTO_INCREMENT = 1"))

    return {
        "deleted_by_table": deleted_by_table,
        "total_deleted": sum(deleted_by_table.values()),
    }
