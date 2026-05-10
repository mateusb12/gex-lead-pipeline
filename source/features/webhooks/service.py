from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from source.features.webhooks.decryption import DecryptionError, decrypt_grummer_payload
from source.features.webhooks.repository import insert_raw_payload, update_raw_payload_result
from source.features.webhooks.schemas import GrummerEncryptedEnvelope, SalesEventPayload


def receive_webhook(*, gateway: str, headers: dict[str, Any], body: Any) -> dict[str, Any]:
    correlation_id = str(uuid4())

    raw_payload_id = insert_raw_payload(
        correlation_id=correlation_id,
        gateway=gateway,
        headers=headers,
        body_original=body,
    )

    if gateway == "lous":
        return _process_lous(correlation_id=correlation_id, raw_payload_id=raw_payload_id, body=body)

    if gateway == "grummer":
        return _process_grummer(
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            headers=headers,
            body=body,
        )

    return {
        "status": "unsupported_gateway",
        "gateway": gateway,
        "correlation_id": correlation_id,
        "raw_payload_id": raw_payload_id,
    }


def _process_lous(*, correlation_id: str, raw_payload_id: int, body: Any) -> dict[str, Any]:
    try:
        sales_event = SalesEventPayload.model_validate(body)
    except ValidationError as error:
        return _handle_schema_failed(
            gateway="lous",
            pipeline="lous_plain_json",
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            error=error,
        )

    return _route_sales_event(
        gateway="lous",
        pipeline_when_approved="lead.received",
        correlation_id=correlation_id,
        raw_payload_id=raw_payload_id,
        sales_event=sales_event,
    )


def _process_grummer(
    *,
    correlation_id: str,
    raw_payload_id: int,
    headers: dict[str, Any],
    body: Any,
) -> dict[str, Any]:
    if not _is_grummer_encrypted(headers):
        error_reason = "decrypt_failed: missing X-GR-Encrypted true header"
        update_raw_payload_result(raw_payload_id=raw_payload_id, error_reason=error_reason)

        return {
            "status": "decrypt_failed",
            "pipeline": "grummer_encrypted_pipeline",
            "gateway": "grummer",
            "correlation_id": correlation_id,
            "raw_payload_id": raw_payload_id,
            "reason": "missing X-GR-Encrypted true header",
        }

    try:
        envelope = GrummerEncryptedEnvelope.model_validate(body)
    except ValidationError as error:
        error_reason = f"schema_failed: invalid grummer encrypted envelope: {error.errors()}"
        update_raw_payload_result(raw_payload_id=raw_payload_id, error_reason=error_reason)

        return {
            "status": "schema_failed",
            "pipeline": "grummer_encrypted_envelope",
            "gateway": "grummer",
            "correlation_id": correlation_id,
            "raw_payload_id": raw_payload_id,
            "reason": "encrypted payload must contain iv and ciphertext",
        }

    try:
        decrypted_payload = decrypt_grummer_payload(
            iv_base64=envelope.iv,
            ciphertext_base64=envelope.ciphertext,
        )
    except DecryptionError as error:
        error_reason = f"decrypt_failed: {error}"
        update_raw_payload_result(raw_payload_id=raw_payload_id, error_reason=error_reason)

        return {
            "status": "decrypt_failed",
            "pipeline": "grummer_encrypted_pipeline",
            "gateway": "grummer",
            "correlation_id": correlation_id,
            "raw_payload_id": raw_payload_id,
            "reason": str(error),
        }

    update_raw_payload_result(raw_payload_id=raw_payload_id, body_decrypted=decrypted_payload)

    try:
        sales_event = SalesEventPayload.model_validate(decrypted_payload)
    except ValidationError as error:
        return _handle_schema_failed(
            gateway="grummer",
            pipeline="grummer_decrypted_payload",
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            error=error,
            body_decrypted=decrypted_payload,
        )

    return _route_sales_event(
        gateway="grummer",
        pipeline_when_approved="lead.received",
        correlation_id=correlation_id,
        raw_payload_id=raw_payload_id,
        sales_event=sales_event,
    )


def _handle_schema_failed(
    *,
    gateway: str,
    pipeline: str,
    correlation_id: str,
    raw_payload_id: int,
    error: ValidationError,
    body_decrypted: Any | None = None,
) -> dict[str, Any]:
    error_reason = f"schema_failed: {error.errors()}"
    update_raw_payload_result(
        raw_payload_id=raw_payload_id,
        body_decrypted=body_decrypted,
        error_reason=error_reason,
    )

    return {
        "status": "schema_failed",
        "pipeline": pipeline,
        "gateway": gateway,
        "correlation_id": correlation_id,
        "raw_payload_id": raw_payload_id,
        "reason": "sales payload does not match expected schema",
    }


def _route_sales_event(
    *,
    gateway: str,
    pipeline_when_approved: str,
    correlation_id: str,
    raw_payload_id: int,
    sales_event: SalesEventPayload,
) -> dict[str, Any]:
    is_approved = sales_event.event == "order.approved" and sales_event.payment.status == "approved"

    return {
        "status": "validated" if is_approved else "discarded",
        "pipeline": pipeline_when_approved if is_approved else "non_approved_discard",
        "gateway": gateway,
        "correlation_id": correlation_id,
        "raw_payload_id": raw_payload_id,
        "transaction_id": sales_event.transaction_id,
        "event": sales_event.event,
        "payment_status": sales_event.payment.status,
        "customer": {
            "email": sales_event.customer.email,
            "first_name": sales_event.customer.first_name,
            "last_name": sales_event.customer.last_name,
            "phone": sales_event.customer.phone,
            "phone_is_valid": sales_event.customer.phone_is_valid,
            "country": sales_event.customer.country,
        },
        "should_publish_to_lead_queue": is_approved,
    }


def _is_grummer_encrypted(headers: dict[str, Any]) -> bool:
    value = headers.get("X-GR-Encrypted") or headers.get("x-gr-encrypted")

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() == "true"

    return False
