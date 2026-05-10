import hashlib
import json
from typing import Any


def anonymize_identifier(value: str | None) -> str | None:
    if not value:
        return None

    normalized = value.strip().lower().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:16]


def log_json(event_type: str, **fields: Any) -> None:
    payload = {
        "event_type": event_type,
        **fields,
    }

    print(json.dumps(payload, ensure_ascii=False, default=str))
