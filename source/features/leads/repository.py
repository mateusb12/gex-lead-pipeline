from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.mysql import insert as mysql_insert

from source.features.webhooks.schemas import SalesEventPayload
from source.shared.db import get_engine
from source.shared.tables import distribution_status, lead_dead_letter

DISTRIBUTION_CHANNELS = ("SMS", "EMAIL", "CALL_CENTER", "WHATSAPP")


def persist_lead_received_message(message: dict[str, Any]) -> dict[str, Any]:
    sales_event = SalesEventPayload.model_validate(message)

    gateway = str(message["gateway"])
    correlation_id = str(message["correlation_id"])

    persisted_at = datetime.now(timezone.utc)
    transaction_time_utc = _ensure_utc(sales_event.transaction_time)
    gateway_to_db_lag_seconds = max(int((persisted_at - transaction_time_utc).total_seconds()), 0)

    lead_id, order_id, event_id = _call_sp_insert_lead(
        sales_event=sales_event,
        gateway=gateway,
        correlation_id=correlation_id,
        transaction_time=transaction_time_utc,
        persisted_at=persisted_at,
        gateway_to_db_lag_seconds=gateway_to_db_lag_seconds,
    )

    with get_engine().begin() as connection:
        _ensure_distribution_status_rows(connection=connection, order_id=order_id)

    return {
        "lead_id": lead_id,
        "order_id": order_id,
        "event_id": event_id,
        "gateway": gateway,
        "transaction_id": sales_event.transaction_id,
        "event": sales_event.event,
        "gateway_to_db_lag_seconds": gateway_to_db_lag_seconds,
        "distribution_channels": list(DISTRIBUTION_CHANNELS),
    }


def _call_sp_insert_lead(
    *,
    sales_event: SalesEventPayload,
    gateway: str,
    correlation_id: str,
    transaction_time: datetime,
    persisted_at: datetime,
    gateway_to_db_lag_seconds: int,
) -> tuple[int, int, int]:
    statement = text(
        """
        CALL sp_insert_lead(
            :email,
            :first_name,
            :last_name,
            :phone,
            :country,
            :gateway,
            :transaction_id,
            :product_id,
            :product_name,
            :product_niche,
            :quantity,
            :amount_usd,
            :payment_method,
            :payment_status,
            :correlation_id,
            :event,
            :transaction_time,
            :persisted_at,
            :gateway_to_db_lag_seconds
        )
        """
    )

    parameters = {
        "email": sales_event.customer.email,
        "first_name": sales_event.customer.first_name,
        "last_name": sales_event.customer.last_name,
        "phone": sales_event.customer.phone,
        "country": sales_event.customer.country,
        "gateway": gateway,
        "transaction_id": sales_event.transaction_id,
        "product_id": sales_event.product.id,
        "product_name": sales_event.product.name,
        "product_niche": sales_event.product.niche,
        "quantity": sales_event.quantity,
        "amount_usd": sales_event.payment.amount_usd,
        "payment_method": sales_event.payment.method,
        "payment_status": sales_event.payment.status,
        "correlation_id": correlation_id,
        "event": sales_event.event,
        "transaction_time": _to_mysql_datetime(transaction_time),
        "persisted_at": _to_mysql_datetime(persisted_at),
        "gateway_to_db_lag_seconds": gateway_to_db_lag_seconds,
    }

    engine = get_engine()
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        result = connection.execute(statement, parameters)
        row = result.mappings().one()

    return int(row["lead_id"]), int(row["order_id"]), int(row["lead_event_id"])


def _ensure_distribution_status_rows(*, connection, order_id: int) -> None:
    for channel in DISTRIBUTION_CHANNELS:
        statement = mysql_insert(distribution_status).values(
            order_id=order_id,
            channel=channel,
            status="pending",
        )

        # No-op em caso de duplicidade.
        # Isso evita sobrescrever delivered caso o evento seja reprocessado.
        statement = statement.on_duplicate_key_update(
            status=distribution_status.c.status,
        )

        connection.execute(statement)


def _ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _to_mysql_datetime(value: datetime) -> datetime:
    return _ensure_utc(value).replace(tzinfo=None)


def insert_lead_worker_dead_letter(
    *,
    source: str,
    reason: str,
    payload: dict[str, Any],
    error_detail: str,
) -> int:
    statement = lead_dead_letter.insert().values(
        source=source,
        reason=reason,
        payload=payload,
        error_detail=error_detail,
    )

    with get_engine().begin() as connection:
        result = connection.execute(statement)

    return int(result.lastrowid)
