import json
from typing import Any

import pika

from source.features.leads.repository import persist_lead_received_message
from source.shared.config import settings
from source.shared.rabbitmq import (
    DISTRIBUTION_QUEUES_BY_CHANNEL,
    LEAD_RECEIVED_QUEUE,
    publish_json,
)
from source.shared.structured_logging import anonymize_identifier, log_json


def main() -> None:
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            heartbeat=30,
            blocked_connection_timeout=30,
        )
    )

    channel = connection.channel()
    channel.queue_declare(queue=LEAD_RECEIVED_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(
        queue=LEAD_RECEIVED_QUEUE,
        on_message_callback=_consume_lead_received,
    )

    print(f"lead worker started. consuming queue={LEAD_RECEIVED_QUEUE}")
    channel.start_consuming()


def process_lead_received_message(message: dict[str, Any]) -> dict[str, Any]:
    persisted = persist_lead_received_message(message)

    for channel_name, queue_name in DISTRIBUTION_QUEUES_BY_CHANNEL.items():
        publish_json(
            queue_name=queue_name,
            message={
                "correlation_id": message["correlation_id"],
                "raw_payload_id": message["raw_payload_id"],
                "gateway": message["gateway"],
                "transaction_id": message["transaction_id"],
                "event": message["event"],
                "lead_id": persisted["lead_id"],
                "order_id": persisted["order_id"],
                "channel": channel_name,
                "customer": message["customer"],
                "product": message["product"],
                "payment": message["payment"],
            },
        )

    return {
        **persisted,
        "published_distribution_queues": list(DISTRIBUTION_QUEUES_BY_CHANNEL.values()),
    }


def _consume_lead_received(channel, method, properties, body: bytes) -> None:
    try:
        message = json.loads(body.decode("utf-8"))
        result = process_lead_received_message(message)

        _log_lead_worker_result(message=message, result=result, status="processed")

        channel.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as exc:  # noqa: BLE001
        # Retry/backoff e DLQ do consumer entram no próximo item da etapa 2.
        # Por enquanto rejeita sem requeue para não gerar loop infinito.
        log_json(
            "lead_worker_failed",
            status="failed",
            error=type(exc).__name__,
            error_detail=str(exc),
        )
        channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def _log_lead_worker_result(*, message: dict[str, Any], result: dict[str, Any], status: str) -> None:
    customer = message.get("customer") or {}
    customer_identifier = None

    if isinstance(customer, dict):
        customer_identifier = anonymize_identifier(customer.get("email"))

    log_json(
        "lead_received_processed",
        status=status,
        correlation_id=message.get("correlation_id"),
        gateway=message.get("gateway"),
        event=message.get("event"),
        transaction_id=message.get("transaction_id"),
        order_id=result.get("order_id"),
        lead_id=result.get("lead_id"),
        gateway_to_db_lag_seconds=result.get("gateway_to_db_lag_seconds"),
        customer_identifier=customer_identifier,
    )


if __name__ == "__main__":
    main()
