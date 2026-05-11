import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pika

from source.shared.config import settings

LEAD_RECEIVED_QUEUE = "lead.received"
LEAD_DEAD_DECRYPT_FAILED_QUEUE = "lead.dead.decrypt_failed"
LEAD_DEAD_SCHEMA_FAILED_QUEUE = "lead.dead.schema_failed"
LEAD_DEAD_CONSUMER_FAILED_QUEUE = "lead.dead.consumer_failed"

DIST_DEAD_SMS_QUEUE = "dist.dead.sms"

DIST_SMS_QUEUE = "dist.sms"
DIST_EMAIL_QUEUE = "dist.email"
DIST_CALLCENTER_QUEUE = "dist.callcenter"
DIST_WHATSAPP_QUEUE = "dist.whatsapp"

DISTRIBUTION_QUEUES_BY_CHANNEL = {
    "SMS": DIST_SMS_QUEUE,
    "EMAIL": DIST_EMAIL_QUEUE,
    "CALL_CENTER": DIST_CALLCENTER_QUEUE,
    "WHATSAPP": DIST_WHATSAPP_QUEUE,
}


def publish_json(*, queue_name: str, message: dict[str, Any]) -> None:
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            heartbeat=30,
            blocked_connection_timeout=30,
        )
    )

    try:
        channel = connection.channel()
        channel.queue_declare(queue=queue_name, durable=True)

        channel.basic_publish(
            exchange="",
            routing_key=queue_name,
            body=json.dumps(message, ensure_ascii=False, default=_json_default).encode("utf-8"),
            properties=pika.BasicProperties(
                content_type="application/json",
                delivery_mode=2,
            ),
        )
    finally:
        connection.close()


def start_consumer(
    *,
    queue_name: str,
    on_message_callback,
    extra_queues: tuple[str, ...] = (),
) -> None:
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(
            host=settings.rabbitmq_host,
            port=settings.rabbitmq_port,
            heartbeat=30,
            blocked_connection_timeout=30,
        )
    )

    channel = connection.channel()

    for queue in (queue_name, *extra_queues):
        channel.queue_declare(queue=queue, durable=True)

    channel.basic_qos(prefetch_count=1)
    channel.basic_consume(queue=queue_name, on_message_callback=on_message_callback)

    print(f"consumer started. consuming queue={queue_name}", flush=True)
    channel.start_consuming()


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, datetime | date):
        return value.isoformat()

    return str(value)
