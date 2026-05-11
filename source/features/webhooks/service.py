import time
from typing import Any
from uuid import uuid4

from pydantic import ValidationError

from source.features.webhooks.decryption import DecryptionError, decrypt_grummer_payload
from source.features.webhooks.repository import (
    insert_lead_dead_letter,
    insert_raw_payload,
    try_register_webhook_idempotency_key,
    update_raw_payload_result,
)
from source.features.webhooks.schemas import GrummerEncryptedEnvelope, SalesEventPayload
from source.shared.rabbitmq import (
    LEAD_DEAD_DECRYPT_FAILED_QUEUE,
    LEAD_DEAD_SCHEMA_FAILED_QUEUE,
    LEAD_RECEIVED_QUEUE,
    publish_json,
)
from source.shared.structured_logging import anonymize_identifier, log_json


def receive_webhook(*, gateway: str, headers: dict[str, Any], body: Any) -> dict[str, Any]:
    started_at = time.perf_counter()
    correlation_id = str(uuid4())

    raw_payload_id = insert_raw_payload(
        correlation_id=correlation_id,
        gateway=gateway,
        headers=headers,
        body_original=body,
    )

    if gateway == "lous":
        response = _process_lous(correlation_id=correlation_id, raw_payload_id=raw_payload_id, body=body)
    elif gateway == "grummer":
        response = _process_grummer(
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            headers=headers,
            body=body,
        )
    else:
        response = {
            "status": "unsupported_gateway",
            "gateway": gateway,
            "correlation_id": correlation_id,
            "raw_payload_id": raw_payload_id,
        }

    latency_ms = round((time.perf_counter() - started_at) * 1000, 2)
    _log_webhook_result(response=response, latency_ms=latency_ms)

    return response


def _process_lous(*, correlation_id: str, raw_payload_id: int, body: Any) -> dict[str, Any]:
    try:
        sales_event = SalesEventPayload.model_validate(body)
    except ValidationError as error:
        return _reject_payload_with_schema_error(
            gateway="lous",
            pipeline="lous_plain_json",
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            error=error,
            payload=body,
        )

    return _route_validated_payload_to_output(
        gateway="lous",
        pipeline_when_approved=LEAD_RECEIVED_QUEUE,
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
        return _reject_payload_with_decrypt_error(
            gateway="grummer",
            pipeline="grummer_encrypted_pipeline",
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            payload=body,
            reason="missing X-GR-Encrypted true header",
        )

    try:
        envelope = GrummerEncryptedEnvelope.model_validate(body)
    except ValidationError as error:
        return _reject_payload_with_schema_error(
            gateway="grummer",
            pipeline="grummer_encrypted_envelope",
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            error=error,
            payload=body,
            response_reason="encrypted payload must contain iv and ciphertext",
            error_prefix="invalid grummer encrypted envelope",
        )

    try:
        decrypted_payload = decrypt_grummer_payload(
            iv_base64=envelope.iv,
            ciphertext_base64=envelope.ciphertext,
        )
    except DecryptionError as error:
        return _reject_payload_with_decrypt_error(
            gateway="grummer",
            pipeline="grummer_encrypted_pipeline",
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            payload=body,
            reason=str(error),
        )

    update_raw_payload_result(raw_payload_id=raw_payload_id, body_decrypted=decrypted_payload)

    try:
        sales_event = SalesEventPayload.model_validate(decrypted_payload)
    except ValidationError as error:
        return _reject_payload_with_schema_error(
            gateway="grummer",
            pipeline="grummer_decrypted_payload",
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            error=error,
            payload=decrypted_payload,
            body_decrypted=decrypted_payload,
        )

    return _route_validated_payload_to_output(
        gateway="grummer",
        pipeline_when_approved=LEAD_RECEIVED_QUEUE,
        correlation_id=correlation_id,
        raw_payload_id=raw_payload_id,
        sales_event=sales_event,
    )


def _reject_payload_with_decrypt_error(
    *,
    gateway: str,
    pipeline: str,
    correlation_id: str,
    raw_payload_id: int,
    payload: Any,
    reason: str,
) -> dict[str, Any]:
    error_reason = f"decrypt_failed: {reason}"
    update_raw_payload_result(raw_payload_id=raw_payload_id, error_reason=error_reason)

    _send_receiver_failure_to_dlq(
        queue_name=LEAD_DEAD_DECRYPT_FAILED_QUEUE,
        source="receiver.decrypt",
        reason="decrypt_failed",
        gateway=gateway,
        correlation_id=correlation_id,
        raw_payload_id=raw_payload_id,
        payload=payload,
        error_detail=reason,
    )

    return {
        "status": "decrypt_failed",
        "pipeline": pipeline,
        "gateway": gateway,
        "correlation_id": correlation_id,
        "raw_payload_id": raw_payload_id,
        "reason": reason,
        "published_queue": LEAD_DEAD_DECRYPT_FAILED_QUEUE,
    }


def _reject_payload_with_schema_error(
    *,
    gateway: str,
    pipeline: str,
    correlation_id: str,
    raw_payload_id: int,
    error: ValidationError,
    payload: Any,
    body_decrypted: Any | None = None,
    response_reason: str = "sales payload does not match expected schema",
    error_prefix: str | None = None,
) -> dict[str, Any]:
    error_detail = str(error.errors())
    error_reason = (
        f"schema_failed: {error_prefix}: {error_detail}"
        if error_prefix
        else f"schema_failed: {error_detail}"
    )

    update_raw_payload_result(
        raw_payload_id=raw_payload_id,
        body_decrypted=body_decrypted,
        error_reason=error_reason,
    )

    _send_receiver_failure_to_dlq(
        queue_name=LEAD_DEAD_SCHEMA_FAILED_QUEUE,
        source="receiver.schema",
        reason="schema_failed",
        gateway=gateway,
        correlation_id=correlation_id,
        raw_payload_id=raw_payload_id,
        payload=payload,
        error_detail=error_detail,
    )

    return {
        "status": "schema_failed",
        "pipeline": pipeline,
        "gateway": gateway,
        "correlation_id": correlation_id,
        "raw_payload_id": raw_payload_id,
        "reason": response_reason,
        "published_queue": LEAD_DEAD_SCHEMA_FAILED_QUEUE,
    }


def _route_validated_payload_to_output(
    *,
    gateway: str,
    pipeline_when_approved: str,
    correlation_id: str,
    raw_payload_id: int,
    sales_event: SalesEventPayload,
) -> dict[str, Any]:
    idempotency_registered = try_register_webhook_idempotency_key(
        gateway=gateway,
        transaction_id=sales_event.transaction_id,
        event=sales_event.event,
        raw_payload_id=raw_payload_id,
        correlation_id=correlation_id,
    )

    if not idempotency_registered:
        return {
            "status": "duplicate",
            "pipeline": "duplicate_webhook",
            "gateway": gateway,
            "correlation_id": correlation_id,
            "raw_payload_id": raw_payload_id,
            "transaction_id": sales_event.transaction_id,
            "event": sales_event.event,
            "payment_status": sales_event.payment.status,
            "should_publish_to_lead_queue": False,
            "published_queue": None,
        }

    is_approved = sales_event.event == "order.approved" and sales_event.payment.status == "approved"
    published_queue = None

    if is_approved:
        _enqueue_validated_lead(
            gateway=gateway,
            correlation_id=correlation_id,
            raw_payload_id=raw_payload_id,
            sales_event=sales_event,
        )
        published_queue = LEAD_RECEIVED_QUEUE

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
        "published_queue": published_queue,
    }


def _enqueue_validated_lead(
    *,
    gateway: str,
    correlation_id: str,
    raw_payload_id: int,
    sales_event: SalesEventPayload,
) -> None:
    publish_json(
        queue_name=LEAD_RECEIVED_QUEUE,
        message={
            "correlation_id": correlation_id,
            "raw_payload_id": raw_payload_id,
            "gateway": gateway,
            "transaction_id": sales_event.transaction_id,
            "transaction_time": sales_event.transaction_time,
            "event": sales_event.event,
            "customer": {
                "email": sales_event.customer.email,
                "first_name": sales_event.customer.first_name,
                "last_name": sales_event.customer.last_name,
                "phone": sales_event.customer.phone,
                "phone_is_valid": sales_event.customer.phone_is_valid,
                "country": sales_event.customer.country,
            },
            "product": {
                "id": sales_event.product.id,
                "name": sales_event.product.name,
                "niche": sales_event.product.niche,
            },
            "quantity": sales_event.quantity,
            "payment": {
                "amount_usd": sales_event.payment.amount_usd,
                "method": sales_event.payment.method,
                "status": sales_event.payment.status,
            },
        },
    )


def _send_receiver_failure_to_dlq(
    *,
    queue_name: str,
    source: str,
    reason: str,
    gateway: str,
    correlation_id: str,
    raw_payload_id: int,
    payload: Any,
    error_detail: str,
) -> None:
    message = {
        "source": source,
        "reason": reason,
        "gateway": gateway,
        "correlation_id": correlation_id,
        "raw_payload_id": raw_payload_id,
        "payload": payload,
        "error_detail": error_detail,
    }

    insert_lead_dead_letter(
        source=source,
        reason=reason,
        payload=message,
        error_detail=error_detail,
    )

    publish_json(
        queue_name=queue_name,
        message=message,
    )


def _is_grummer_encrypted(headers: dict[str, Any]) -> bool:
    value = headers.get("X-GR-Encrypted") or headers.get("x-gr-encrypted")

    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.strip().lower() == "true"

    return False


def _log_webhook_result(*, response: dict[str, Any], latency_ms: float) -> None:
    customer = response.get("customer") or {}
    customer_identifier = None

    if isinstance(customer, dict):
        customer_identifier = anonymize_identifier(customer.get("email"))

    log_json(
        "webhook_processed",
        correlation_id=response.get("correlation_id"),
        gateway=response.get("gateway"),
        status=response.get("status"),
        pipeline=response.get("pipeline"),
        event=response.get("event"),
        latency_ms=latency_ms,
        raw_payload_id=response.get("raw_payload_id"),
        customer_identifier=customer_identifier,
    )
