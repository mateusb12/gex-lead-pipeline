import hashlib
import re
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

    print(json.dumps(payload, ensure_ascii=False, default=str), flush=True)


def safe_log_error_detail(error: Exception | str, *, max_length: int = 300) -> str:
    message = str(error).splitlines()[0]

    message = re.sub(
        r"[^@\s]+@[^@\s]+\.[^@\s]+",
        "[redacted_email]",
        message,
    )

    message = re.sub(
        r"\+?\d[\d\s().-]{7,}\d",
        "[redacted_phone]",
        message,
    )

    if len(message) > max_length:
        return message[:max_length] + "..."

    return message
