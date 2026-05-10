import json
from typing import Any

from sqlalchemy import text

from source.shared.db import get_engine


def _to_json_param(value: Any) -> str | None:
    if value is None:
        return None

    return json.dumps(value, ensure_ascii=False)


def insert_raw_payload(
    *,
    correlation_id: str,
    gateway: str,
    headers: dict[str, Any],
    body_original: Any,
    body_decrypted: Any | None = None,
    error_reason: str | None = None,
) -> int:
    query = text(
        """
        INSERT INTO raw_payloads (
            correlation_id,
            gateway,
            headers,
            body_original,
            body_decrypted,
            error_reason
        )
        VALUES (
            :correlation_id,
            :gateway,
            :headers,
            :body_original,
            :body_decrypted,
            :error_reason
        )
        """
    )

    params = {
        "correlation_id": correlation_id,
        "gateway": gateway,
        "headers": _to_json_param(headers),
        "body_original": _to_json_param(body_original),
        "body_decrypted": _to_json_param(body_decrypted),
        "error_reason": error_reason,
    }

    with get_engine().begin() as connection:
        result = connection.execute(query, params)

    return int(result.lastrowid)


def update_raw_payload_result(
    *,
    raw_payload_id: int,
    body_decrypted: Any | None = None,
    error_reason: str | None = None,
) -> None:
    query = text(
        """
        UPDATE raw_payloads
        SET
            body_decrypted = :body_decrypted,
            error_reason = :error_reason
        WHERE id = :raw_payload_id
        """
    )

    params = {
        "raw_payload_id": raw_payload_id,
        "body_decrypted": _to_json_param(body_decrypted),
        "error_reason": error_reason,
    }

    with get_engine().begin() as connection:
        connection.execute(query, params)
