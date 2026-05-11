import json
import random
import time
import requests
from typing import Any

from source.features.distribution.repository import insert_sms_dead_letter_in_db, mark_sms_as_delivered_in_db
from source.shared.config import settings
from source.shared.rabbitmq import DIST_DEAD_SMS_QUEUE, DIST_SMS_QUEUE, publish_json, start_consumer
from source.shared.structured_logging import anonymize_identifier, log_json, safe_log_error_detail

RETRY_DELAYS_SECONDS = (1, 4, 16)
RANDOM_FAILURE_RATE = 0.10
POST_TIMEOUT_SECONDS = 10


def main() -> None:
    start_consumer(
        queue_name=DIST_SMS_QUEUE,
        on_message_callback=_consume_sms_from_queue,
        extra_queues=(DIST_DEAD_SMS_QUEUE,),
    )


def deliver_sms_distribution_message_with_retry(message: dict[str, Any]) -> dict[str, Any]:
    attempt = 1

    while True:
        try:
            result = deliver_sms_distribution_message(message)

            return {
                **result,
                "attempts": attempt,
            }

        except Exception:
            if attempt > len(RETRY_DELAYS_SECONDS):
                raise

            delay = RETRY_DELAYS_SECONDS[attempt - 1]

            log_json(
                "sms_retry_scheduled",
                status="retry_scheduled",
                correlation_id=message.get("correlation_id"),
                gateway=message.get("gateway"),
                event=message.get("event"),
                transaction_id=message.get("transaction_id"),
                order_id=message.get("order_id"),
                attempt=attempt,
                next_attempt=attempt + 1,
                delay_seconds=delay,
            )

            time.sleep(delay)
            attempt += 1


def deliver_sms_distribution_message(message: dict[str, Any]) -> dict[str, Any]:
    if message.get("channel") != "SMS":
        raise ValueError(f"unsupported distribution channel={message.get('channel')}")

    if random.random() < RANDOM_FAILURE_RATE:
        raise RuntimeError("simulated sms provider failure")

    status_code = _post_sms_payload_to_webhook_site(message)
    delivered = mark_sms_as_delivered_in_db(order_id=int(message["order_id"]))

    log_json(
        "sms_delivered",
        status="delivered",
        correlation_id=message.get("correlation_id"),
        gateway=message.get("gateway"),
        event=message.get("event"),
        transaction_id=message.get("transaction_id"),
        order_id=message.get("order_id"),
        channel="SMS",
        webhook_status_code=status_code,
        db_to_channel_lag_seconds=delivered["db_to_channel_lag_seconds"],
        customer_identifier=anonymize_identifier((message.get("customer") or {}).get("email")),
    )

    return {
        **delivered,
        "webhook_status_code": status_code,
    }


def _post_sms_payload_to_webhook_site(message: dict[str, Any]) -> int:
    if not settings.sms_webhook_url:
        raise RuntimeError("SMS_WEBHOOK_URL is not configured")

    customer = message.get("customer") or {}
    product = message.get("product") or {}

    payload = {
        "correlation_id": message.get("correlation_id"),
        "gateway": message.get("gateway"),
        "transaction_id": message.get("transaction_id"),
        "event": message.get("event"),
        "lead_id": message.get("lead_id"),
        "order_id": message.get("order_id"),
        "channel": "SMS",
        "to": customer.get("phone"),
        "message": f"Thanks for your order of {product.get('name', 'your product')}.",
    }

    response = requests.post(
        settings.sms_webhook_url,
        json=payload,
        timeout=POST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    return int(response.status_code)


def _consume_sms_from_queue(channel, method, properties, body: bytes) -> None:
    started_at = time.perf_counter()
    message: dict[str, Any] | None = None

    try:
        message = json.loads(body.decode("utf-8"))
        result = deliver_sms_distribution_message_with_retry(message)

        log_json(
            "sms_processed",
            status="processed",
            correlation_id=message.get("correlation_id"),
            gateway=message.get("gateway"),
            event=message.get("event"),
            transaction_id=message.get("transaction_id"),
            order_id=message.get("order_id"),
            channel="SMS",
            attempts=result["attempts"],
            latency_ms=round((time.perf_counter() - started_at) * 1000, 2),
        )

        channel.basic_ack(delivery_tag=method.delivery_tag)

    except Exception as exc:  # noqa: BLE001
        error_detail = safe_log_error_detail(exc)
        dlq_payload = _build_sms_dead_letter_payload(message=message, body=body, error_detail=error_detail)

        try:
            insert_sms_dead_letter_in_db(payload=dlq_payload, error_detail=error_detail)
            publish_json(queue_name=DIST_DEAD_SMS_QUEUE, message=dlq_payload)

            log_json(
                "sms_sent_to_dlq",
                status="sent_to_dlq",
                correlation_id=dlq_payload.get("correlation_id"),
                gateway=dlq_payload.get("gateway"),
                event=dlq_payload.get("event"),
                transaction_id=dlq_payload.get("transaction_id"),
                order_id=dlq_payload.get("order_id"),
                channel="SMS",
                queue_name=DIST_DEAD_SMS_QUEUE,
                error_detail=error_detail,
            )

            channel.basic_ack(delivery_tag=method.delivery_tag)

        except Exception as dlq_exc:  # noqa: BLE001
            log_json(
                "sms_dlq_failed",
                status="dlq_failed",
                error_detail=safe_log_error_detail(dlq_exc),
            )

            channel.basic_nack(delivery_tag=method.delivery_tag, requeue=False)


def _build_sms_dead_letter_payload(
    *,
    message: dict[str, Any] | None,
    body: bytes,
    error_detail: str,
) -> dict[str, Any]:
    payload = message or {
        "raw_body": body.decode("utf-8", errors="replace"),
    }

    return {
        "source": "distribution.sms",
        "reason": "sms_delivery_failed",
        "correlation_id": payload.get("correlation_id"),
        "gateway": payload.get("gateway"),
        "event": payload.get("event"),
        "transaction_id": payload.get("transaction_id"),
        "order_id": payload.get("order_id"),
        "payload": payload,
        "error_detail": error_detail,
    }


if __name__ == "__main__":
    main()
