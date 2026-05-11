from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from source.shared.db import get_engine
from source.shared.tables import distribution_status, lead_dead_letter

SMS_CHANNEL = "SMS"


def mark_sms_as_delivered_in_db(*, order_id: int) -> dict[str, Any]:
    delivered_at = datetime.now(timezone.utc)

    with get_engine().begin() as connection:
        row = connection.execute(
            select(distribution_status.c.id, distribution_status.c.created_at)
            .where(
                distribution_status.c.order_id == order_id,
                distribution_status.c.channel == SMS_CHANNEL,
            )
            .with_for_update()
        ).mappings().one_or_none()

        if row is None:
            raise ValueError(f"SMS distribution_status not found for order_id={order_id}")

        created_at = _as_utc(row["created_at"])
        lag_seconds = max(int((delivered_at - created_at).total_seconds()), 0)

        connection.execute(
            distribution_status.update()
            .where(distribution_status.c.id == row["id"])
            .values(
                status="delivered",
                delivered_at=_as_mysql_datetime(delivered_at),
                db_to_channel_lag_seconds=lag_seconds,
            )
        )

    return {
        "order_id": order_id,
        "channel": SMS_CHANNEL,
        "status": "delivered",
        "db_to_channel_lag_seconds": lag_seconds,
    }


def insert_sms_dead_letter_in_db(*, payload: dict[str, Any], error_detail: str) -> int:
    statement = lead_dead_letter.insert().values(
        source="distribution.sms",
        reason="sms_delivery_failed",
        payload=payload,
        error_detail=error_detail,
    )

    with get_engine().begin() as connection:
        result = connection.execute(statement)

    return int(result.lastrowid)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _as_mysql_datetime(value: datetime) -> datetime:
    return _as_utc(value).replace(tzinfo=None)
