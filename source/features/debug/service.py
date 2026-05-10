import json
from datetime import datetime
from typing import Any

from source.features.debug.repository import list_raw_payloads


def _decode_json(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, dict | list):
        return value

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    return value


def _serialize_datetime(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()

    return value


def get_raw_payloads(limit: int = 10) -> dict[str, Any]:
    safe_limit = max(1, min(limit, 100))
    rows = list_raw_payloads(limit=safe_limit)

    payloads = []
    for row in rows:
        payloads.append(
            {
                "id": row["id"],
                "correlation_id": row["correlation_id"],
                "gateway": row["gateway"],
                "received_at": _serialize_datetime(row["received_at"]),
                "headers": _decode_json(row["headers"]),
                "body_original": _decode_json(row["body_original"]),
                "body_decrypted": _decode_json(row["body_decrypted"]),
                "error_reason": row["error_reason"],
            }
        )

    return {"count": len(payloads), "items": payloads}
