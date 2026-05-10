from typing import Any

from source.shared.db import get_engine
from sqlalchemy.exc import IntegrityError

from source.shared.tables import raw_payloads, webhook_idempotency_keys


def insert_raw_payload(
    *,
    correlation_id: str,
    gateway: str,
    headers: dict[str, Any],
    body_original: Any,
    body_decrypted: Any | None = None,
    error_reason: str | None = None,
) -> int:
    statement = raw_payloads.insert().values(
        correlation_id=correlation_id,
        gateway=gateway,
        headers=headers,
        body_original=body_original,
        body_decrypted=body_decrypted,
        error_reason=error_reason,
    )

    with get_engine().begin() as connection:
        result = connection.execute(statement)

    return int(result.lastrowid)


def update_raw_payload_result(
    *,
    raw_payload_id: int,
    body_decrypted: Any | None = None,
    error_reason: str | None = None,
) -> None:
    statement = (
        raw_payloads.update()
        .where(raw_payloads.c.id == raw_payload_id)
        .values(body_decrypted=body_decrypted, error_reason=error_reason)
    )

    with get_engine().begin() as connection:
        connection.execute(statement)

def try_register_webhook_idempotency_key(
    *,
    gateway: str,
    transaction_id: str,
    event: str,
    raw_payload_id: int,
    correlation_id: str,
) -> bool:
    statement = webhook_idempotency_keys.insert().values(
        gateway=gateway,
        transaction_id=transaction_id,
        event=event,
        raw_payload_id=raw_payload_id,
        correlation_id=correlation_id,
    )

    try:
        with get_engine().begin() as connection:
            connection.execute(statement)
    except IntegrityError:
        return False

    return True

