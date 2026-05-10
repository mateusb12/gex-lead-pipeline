from uuid import UUID

from source.features.webhooks import service


VALID_LOUS_BODY = {
    "transaction_id": "ORD-TEST-001",
    "transaction_time": "2026-05-10T17:49:30.715553+00:00",
    "event": "order.approved",
    "customer": {
        "email": "test@example.com",
        "first_name": "Test",
        "last_name": "Customer",
        "phone": "+18005551234",
        "country": "US",
    },
    "product": {
        "id": "PROD-001",
        "name": "Fit Burn",
        "niche": "weight_loss",
    },
    "quantity": 1,
    "payment": {
        "status": "approved",
        "amount_usd": 99.90,
        "method": "credit_card",
    },
}


def test_receive_webhook_routes_lous_valid_payload(monkeypatch):
    captured_insert = {}

    def fake_insert_raw_payload(**kwargs):
        captured_insert.update(kwargs)
        return 456

    monkeypatch.setattr(service, "insert_raw_payload", fake_insert_raw_payload)
    monkeypatch.setattr(service, "update_raw_payload_result", lambda **kwargs: None)

    response = service.receive_webhook(
        gateway="lous",
        headers={"content-type": "application/json"},
        body=VALID_LOUS_BODY,
    )

    UUID(response["correlation_id"])

    assert response["status"] == "validated"
    assert response["pipeline"] == "lead.received"
    assert response["gateway"] == "lous"
    assert response["raw_payload_id"] == 456
    assert response["should_publish_to_lead_queue"] is True

    assert captured_insert["gateway"] == "lous"
    assert captured_insert["body_original"] == VALID_LOUS_BODY


def test_receive_webhook_routes_lous_invalid_payload_to_schema_failed(monkeypatch):
    captured_update = {}

    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 123)

    def fake_update_raw_payload_result(**kwargs):
        captured_update.update(kwargs)

    monkeypatch.setattr(service, "update_raw_payload_result", fake_update_raw_payload_result)

    response = service.receive_webhook(
        gateway="lous",
        headers={"content-type": "application/json"},
        body={"hello": "world"},
    )

    assert response["status"] == "schema_failed"
    assert response["pipeline"] == "lous_plain_json"
    assert response["raw_payload_id"] == 123
    assert captured_update["raw_payload_id"] == 123
    assert captured_update["error_reason"].startswith("schema_failed")


def test_receive_webhook_routes_grummer_envelope_to_decrypt_stub(monkeypatch):
    captured_update = {}

    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 789)

    def fake_update_raw_payload_result(**kwargs):
        captured_update.update(kwargs)

    monkeypatch.setattr(service, "update_raw_payload_result", fake_update_raw_payload_result)

    response = service.receive_webhook(
        gateway="grummer",
        headers={"x-gr-encrypted": "true"},
        body={"iv": "abc", "ciphertext": "def"},
    )

    assert response["status"] == "decrypt_stubbed"
    assert response["pipeline"] == "grummer_encrypted_pipeline"
    assert response["raw_payload_id"] == 789
    assert captured_update["body_decrypted"]["stub"] is True
    assert captured_update["error_reason"] == "decrypt_stubbed"


def test_receive_webhook_routes_invalid_grummer_envelope_to_schema_failed(monkeypatch):
    captured_update = {}

    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 999)

    def fake_update_raw_payload_result(**kwargs):
        captured_update.update(kwargs)

    monkeypatch.setattr(service, "update_raw_payload_result", fake_update_raw_payload_result)

    response = service.receive_webhook(
        gateway="grummer",
        headers={"x-gr-encrypted": "true"},
        body={"hello": "world"},
    )

    assert response["status"] == "schema_failed"
    assert response["pipeline"] == "grummer_encrypted_envelope"
    assert response["raw_payload_id"] == 999
    assert captured_update["error_reason"].startswith("schema_failed")
