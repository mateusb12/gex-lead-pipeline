from typing import Any
from uuid import uuid4

from source.features.webhooks.repository import insert_raw_payload


def receive_webhook(*, gateway: str, headers: dict[str, Any], body: Any) -> dict[str, Any]:
    correlation_id = str(uuid4())

    raw_payload_id = insert_raw_payload(
        correlation_id=correlation_id, gateway=gateway, headers=headers, body_original=body
    )

    return {
        "status": "received",
        "gateway": gateway,
        "correlation_id": correlation_id,
        "raw_payload_id": raw_payload_id,
        "stub": True,
        "body_keys": list(body.keys()) if isinstance(body, dict) else [],
    }
