import json
import time
from typing import Any

import pika

from source.features.leads.repository import (
    insert_lead_worker_dead_letter,
    persist_lead_received_message,
)
from source.shared.config import settings
from source.shared.rabbitmq import (
    DISTRIBUTION_QUEUES_BY_CHANNEL,
    LEAD_DEAD_CONSUMER_FAILED_QUEUE,
    LEAD_RECEIVED_QUEUE,
    publish_json,
)
from source.shared.structured_logging import anonymize_identifier, log_json

LEAD_CONSUMER_RETRY_DELAYS_SECONDS = (1, 4, 16)


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
    channel.queue_declare(queue=LEAD_DEAD_CONSUMER_FAILED_QUEUE, durable=True)
    channel.basic_qos(prefetch_count=1)

    channel.basic_consume(
        queue=LEAD_RECEIVED_QUEUE,
        on_message_callback=_consume_lead_received_from_queue,
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


def process_lead_received_message_with_retry(
    message: dict[str, Any],
    *,
    retry_delays_seconds: tuple[int, ...] = LEAD_CONSUMER_RETRY_DELAYS_SECONDS,
) -> dict[str, Any]:
    attempt = 1

    while True:
        try:
            result = process_lead_received_message(message)
            return {
                **result,
                "attempts": attempt,
            }

        except Exception as exc:
            if attempt > len(retry_delays_seconds):
                raise

            delay_seconds = retry_delays_seconds[attempt - 1]

            log_json(
                "lead_worker_retry_scheduled",
                status="retry_scheduled",
                correlation_id=message.get("correlation_id"),
                gateway=message.get("gateway"),
                event=message.get("event"),
                transaction_id=message.get("transaction_id"),
                attempt=attempt,
                next_attempt=attempt + 1,
                delay_seconds=delay_seconds,
                error=type(exc).__name__,
                error_detail=str(exc),
            )

            time.sleep(delay_seconds)
            attempt += 1


def _consume_lead_received_from_queue(channel, method, properties, body: bytes) -> None:
    message: dict[str, Any] | None = None

    try:
        message = json.loads(body.decode("utf-8"))
        result = process_lead_received_message_with_retry(message)

        _log_lead_worker_result(message=message, result=result, status="processed")

        channel.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as exc:  # noqa: BLE001
        error_detail = str(exc)
        dlq_payload = _build_failed_message_payload(
            message=message,
            body=body,
            error=exc,
        )

        try:
            _send_lead_worker_failure_to_dlq(
                payload=dlq_payload,
                error_detail=error_detail,
            )

            log_json(
                "lead_worker_sent_to_dlq",
                status="sent_to_dlq",
                correlation_id=dlq_payload.get("correlation_id"),
                gateway=dlq_payload.get("gateway"),
                event=dlq_payload.get("event"),
                transaction_id=dlq_payload.get("transaction_id"),
                queue_name=LEAD_DEAD_CONSUMER_FAILED_QUEUE,
                error=type(exc).__name__,
                error_detail=error_detail,
            )

            channel.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as dlq_exc:  # noqa: BLE001
            log_json(
                "lead_worker_dlq_failed",
                status="dlq_failed",
                correlation_id=dlq_payload.get("correlation_id"),
                gateway=dlq_payload.get("gateway"),
                event=dlq_payload.get("event"),
                transaction_id=dlq_payload.get("transaction_id"),
                error=type(dlq_exc).__name__,
                error_detail=str(dlq_exc),
                original_error=type(exc).__name__,
                original_error_detail=error_detail,
            )

            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def _build_failed_message_payload(
    *,
    message: dict[str, Any] | None,
    body: bytes,
    error: Exception,
) -> dict[str, Any]:
    if message is None:
        return {
            "source": "lead.worker",
            "reason": "consumer_failed",
            "raw_body": body.decode("utf-8", errors="replace"),
            "error": type(error).__name__,
            "error_detail": str(error),
            "attempts": len(LEAD_CONSUMER_RETRY_DELAYS_SECONDS) + 1,
        }

    return {
        "source": "lead.worker",
        "reason": "consumer_failed",
        "correlation_id": message.get("correlation_id"),
        "raw_payload_id": message.get("raw_payload_id"),
        "gateway": message.get("gateway"),
        "transaction_id": message.get("transaction_id"),
        "event": message.get("event"),
        "payload": message,
        "error": type(error).__name__,
        "error_detail": str(error),
        "attempts": len(LEAD_CONSUMER_RETRY_DELAYS_SECONDS) + 1,
    }


def _send_lead_worker_failure_to_dlq(
    *,
    payload: dict[str, Any],
    error_detail: str,
) -> None:
    insert_lead_worker_dead_letter(
        source="lead.worker",
        reason="consumer_failed",
        payload=payload,
        error_detail=error_detail,
    )

    publish_json(
        queue_name=LEAD_DEAD_CONSUMER_FAILED_QUEUE,
        message=payload,
    )


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
        attempts=result.get("attempts"),
        gateway_to_db_lag_seconds=result.get("gateway_to_db_lag_seconds"),
        customer_identifier=customer_identifier,
    )


if __name__ == "__main__":
    main()
