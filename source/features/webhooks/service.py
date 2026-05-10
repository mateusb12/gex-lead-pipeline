from typing import Any
from uuid import uuid4

from pydantic import ValidationError

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
        return _process_grummer(correlation_id=correlation_id, raw_payload_id=raw_payload_id, body=body)

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
        error_reason = f"schema_failed: {error.errors()}"
        update_raw_payload_result(raw_payload_id=raw_payload_id, error_reason=error_reason)

        return {
            "status": "schema_failed",
            "pipeline": "lous_plain_json",
            "gateway": "lous",
            "correlation_id": correlation_id,
            "raw_payload_id": raw_payload_id,
            "reason": "sales payload does not match expected schema",
        }

    is_approved = sales_event.event == "order.approved" and sales_event.payment.status == "approved"

    return {
        "status": "validated" if is_approved else "discarded",
        "pipeline": "lead.received" if is_approved else "non_approved_discard",
        "gateway": "lous",
        "correlation_id": correlation_id,
        "raw_payload_id": raw_payload_id,
        "transaction_id": sales_event.transaction_id,
        "event": sales_event.event,
        "payment_status": sales_event.payment.status,
        "should_publish_to_lead_queue": is_approved,
    }


def _process_grummer(*, correlation_id: str, raw_payload_id: int, body: Any) -> dict[str, Any]:
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

    decrypted_stub = _decrypt_grummer_payload_stub(envelope)
    update_raw_payload_result(raw_payload_id=raw_payload_id, body_decrypted=decrypted_stub, error_reason="decrypt_stubbed")

    return {
        "status": "decrypt_stubbed",
        "pipeline": "grummer_encrypted_pipeline",
        "gateway": "grummer",
        "correlation_id": correlation_id,
        "raw_payload_id": raw_payload_id,
        "next_step": "real AES decrypt, then SalesEventPayload validation",
    }


def _decrypt_grummer_payload_stub(envelope: GrummerEncryptedEnvelope) -> dict[str, Any]:
    print("decriptografando...")

    return {
        "stub": True,
        "message": "AES decrypt not implemented yet",
        "iv_length": len(envelope.iv),
        "ciphertext_length": len(envelope.ciphertext),
    }
