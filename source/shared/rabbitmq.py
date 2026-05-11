import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pika

from source.shared.config import settings

LEAD_RECEIVED_QUEUE = "lead.received"
LEAD_DEAD_DECRYPT_FAILED_QUEUE = "lead.dead.decrypt_failed"
LEAD_DEAD_SCHEMA_FAILED_QUEUE = "lead.dead.schema_failed"


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


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)

    if isinstance(value, datetime | date):
        return value.isoformat()

    return str(value)
