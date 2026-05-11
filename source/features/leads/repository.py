from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert

from source.features.webhooks.schemas import SalesEventPayload
from source.shared.db import get_engine
from source.shared.tables import distribution_status, lead_events, leads, orders

DISTRIBUTION_CHANNELS = ("SMS", "EMAIL", "CALL_CENTER", "WHATSAPP")


def persist_lead_received_message(message: dict[str, Any]) -> dict[str, Any]:
    sales_event = SalesEventPayload.model_validate(message)

    gateway = str(message["gateway"])
    correlation_id = str(message["correlation_id"])

    persisted_at = datetime.now(timezone.utc)
    transaction_time_utc = _ensure_utc(sales_event.transaction_time)
    gateway_to_db_lag_seconds = max(int((persisted_at - transaction_time_utc).total_seconds()), 0)

    with get_engine().begin() as connection:
        lead_id = _upsert_lead(connection=connection, sales_event=sales_event)
        order_id = _upsert_order(
            connection=connection,
            lead_id=lead_id,
            gateway=gateway,
            sales_event=sales_event,
        )
        event_id = _upsert_lead_event(
            connection=connection,
            order_id=order_id,
            correlation_id=correlation_id,
            sales_event=sales_event,
            transaction_time=transaction_time_utc,
            persisted_at=persisted_at,
            gateway_to_db_lag_seconds=gateway_to_db_lag_seconds,
        )
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


def _upsert_lead(*, connection, sales_event: SalesEventPayload) -> int:
    statement = mysql_insert(leads).values(
        email=sales_event.customer.email,
        first_name=sales_event.customer.first_name,
        last_name=sales_event.customer.last_name,
        phone=sales_event.customer.phone,
        country=sales_event.customer.country,
    )

    statement = statement.on_duplicate_key_update(
        first_name=statement.inserted.first_name,
        last_name=statement.inserted.last_name,
        phone=statement.inserted.phone,
        country=statement.inserted.country,
    )

    connection.execute(statement)

    return int(
        connection.execute(
            select(leads.c.id).where(leads.c.email == sales_event.customer.email)
        ).scalar_one()
    )


def _upsert_order(*, connection, lead_id: int, gateway: str, sales_event: SalesEventPayload) -> int:
    statement = mysql_insert(orders).values(
        lead_id=lead_id,
        gateway=gateway,
        transaction_id=sales_event.transaction_id,
        product_id=sales_event.product.id,
        product_name=sales_event.product.name,
        product_niche=sales_event.product.niche,
        quantity=sales_event.quantity,
        amount_usd=sales_event.payment.amount_usd,
        payment_method=sales_event.payment.method,
        payment_status=sales_event.payment.status,
    )

    statement = statement.on_duplicate_key_update(
        lead_id=statement.inserted.lead_id,
        product_id=statement.inserted.product_id,
        product_name=statement.inserted.product_name,
        product_niche=statement.inserted.product_niche,
        quantity=statement.inserted.quantity,
        amount_usd=statement.inserted.amount_usd,
        payment_method=statement.inserted.payment_method,
        payment_status=statement.inserted.payment_status,
    )

    connection.execute(statement)

    return int(
        connection.execute(
            select(orders.c.id).where(
                orders.c.gateway == gateway,
                orders.c.transaction_id == sales_event.transaction_id,
            )
        ).scalar_one()
    )


def _upsert_lead_event(
    *,
    connection,
    order_id: int,
    correlation_id: str,
    sales_event: SalesEventPayload,
    transaction_time: datetime,
    persisted_at: datetime,
    gateway_to_db_lag_seconds: int,
) -> int:
    statement = mysql_insert(lead_events).values(
        order_id=order_id,
        correlation_id=correlation_id,
        event=sales_event.event,
        transaction_time=_to_mysql_datetime(transaction_time),
        persisted_at=_to_mysql_datetime(persisted_at),
        gateway_to_db_lag_seconds=gateway_to_db_lag_seconds,
    )

    statement = statement.on_duplicate_key_update(
        correlation_id=statement.inserted.correlation_id,
        transaction_time=statement.inserted.transaction_time,
        persisted_at=statement.inserted.persisted_at,
        gateway_to_db_lag_seconds=statement.inserted.gateway_to_db_lag_seconds,
    )

    connection.execute(statement)

    return int(
        connection.execute(
            select(lead_events.c.id).where(
                lead_events.c.order_id == order_id,
                lead_events.c.event == sales_event.event,
            )
        ).scalar_one()
    )


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
