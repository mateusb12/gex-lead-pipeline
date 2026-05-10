from uuid import UUID

import pytest

from source.features.webhooks import service




@pytest.fixture(autouse=True)
def mock_idempotency(monkeypatch):
    monkeypatch.setattr(service, "try_register_webhook_idempotency_key", lambda **kwargs: True)


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


def test_webhook_lous_valido_segue_para_fila_de_leads(monkeypatch):
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


def test_webhook_lous_invalido_vai_para_schema_failed(monkeypatch):
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


def test_webhook_grummer_decriptado_valido_segue_para_fila_de_leads(monkeypatch):
    captured_update = {}

    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 789)

    def fake_update_raw_payload_result(**kwargs):
        captured_update.update(kwargs)

    monkeypatch.setattr(service, "update_raw_payload_result", fake_update_raw_payload_result)
    monkeypatch.setattr(service, "decrypt_grummer_payload", lambda **kwargs: VALID_LOUS_BODY)

    response = service.receive_webhook(
        gateway="grummer",
        headers={"x-gr-encrypted": "true"},
        body={"iv": "abc", "ciphertext": "def"},
    )

    assert response["status"] == "validated"
    assert response["pipeline"] == "lead.received"
    assert response["gateway"] == "grummer"
    assert response["raw_payload_id"] == 789
    assert response["transaction_id"] == VALID_LOUS_BODY["transaction_id"]
    assert captured_update["body_decrypted"] == VALID_LOUS_BODY


def test_webhook_grummer_com_envelope_invalido_vai_para_schema_failed(monkeypatch):
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


def test_webhook_aceita_quantity_dentro_de_product_no_payload_do_benchmark(monkeypatch):
    body = {
        "transaction_id": "ORD-TEST-BENCHMARK-001",
        "transaction_time": "2026-05-10T17:49:30.715553+00:00",
        "event": "order.approved",
        "customer": {
            "email": "benchmark@example.com",
            "first_name": "Benchmark",
            "last_name": "Customer",
            "phone": "+18005551234",
            "country": "US",
        },
        "product": {
            "id": "PROD-001",
            "name": "Fit Burn",
            "niche": "weight_loss",
            "quantity": 1,
        },
        "payment": {
            "status": "approved",
            "amount_usd": 99.90,
            "method": "credit_card",
        },
    }

    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 321)
    monkeypatch.setattr(service, "update_raw_payload_result", lambda **kwargs: None)

    response = service.receive_webhook(
        gateway="lous",
        headers={"content-type": "application/json"},
        body=body,
    )

    assert response["status"] == "validated"
    assert response["pipeline"] == "lead.received"
    assert response["transaction_id"] == "ORD-TEST-BENCHMARK-001"
    assert response["should_publish_to_lead_queue"] is True


def test_webhook_normaliza_campos_criticos_do_cliente(monkeypatch):
    body = {
        **VALID_LOUS_BODY,
        "customer": {
            "email": "  TEST.NORMALIZED@Example.COM  ",
            "first_name": "",
            "last_name": " Customer ",
            "phone": "+1 (800) 555-1234",
            "country": "us",
        },
    }

    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 654)
    monkeypatch.setattr(service, "update_raw_payload_result", lambda **kwargs: None)

    response = service.receive_webhook(
        gateway="lous",
        headers={"content-type": "application/json"},
        body=body,
    )

    assert response["status"] == "validated"
    assert response["customer"] == {
        "email": "test.normalized@example.com",
        "first_name": "Customer",
        "last_name": "Customer",
        "phone": "+18005551234",
        "phone_is_valid": True,
        "country": "US",
    }


def test_webhook_sinaliza_telefone_invalido_mas_mantem_lead(monkeypatch):
    body = {
        **VALID_LOUS_BODY,
        "customer": {
            **VALID_LOUS_BODY["customer"],
            "phone": "abc-123",
        },
    }

    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 655)
    monkeypatch.setattr(service, "update_raw_payload_result", lambda **kwargs: None)

    response = service.receive_webhook(
        gateway="lous",
        headers={"content-type": "application/json"},
        body=body,
    )

    assert response["status"] == "validated"
    assert response["should_publish_to_lead_queue"] is True
    assert response["customer"]["phone"] == "123"
    assert response["customer"]["phone_is_valid"] is False


def test_webhook_com_email_invalido_vai_para_schema_failed(monkeypatch):
    captured_update = {}

    body = {
        **VALID_LOUS_BODY,
        "customer": {
            **VALID_LOUS_BODY["customer"],
            "email": "invalid-email",
        },
    }

    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 656)

    def fake_update_raw_payload_result(**kwargs):
        captured_update.update(kwargs)

    monkeypatch.setattr(service, "update_raw_payload_result", fake_update_raw_payload_result)

    response = service.receive_webhook(
        gateway="lous",
        headers={"content-type": "application/json"},
        body=body,
    )

    assert response["status"] == "schema_failed"
    assert response["pipeline"] == "lous_plain_json"
    assert captured_update["error_reason"].startswith("schema_failed")
    assert "invalid email format" in captured_update["error_reason"]


def test_webhook_duplicado_retorna_duplicate_sem_republicar(monkeypatch):
    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 777)
    monkeypatch.setattr(service, "update_raw_payload_result", lambda **kwargs: None)
    monkeypatch.setattr(service, "try_register_webhook_idempotency_key", lambda **kwargs: False)

    response = service.receive_webhook(
        gateway="lous",
        headers={"content-type": "application/json"},
        body=VALID_LOUS_BODY,
    )

    assert response["status"] == "duplicate"
    assert response["pipeline"] == "duplicate_webhook"
    assert response["should_publish_to_lead_queue"] is False
    assert response["transaction_id"] == VALID_LOUS_BODY["transaction_id"]
    assert response["event"] == VALID_LOUS_BODY["event"]


def test_log_estruturado_nao_expoe_email_ou_telefone(monkeypatch, capsys):
    monkeypatch.setattr(service, "insert_raw_payload", lambda **kwargs: 778)
    monkeypatch.setattr(service, "update_raw_payload_result", lambda **kwargs: None)

    response = service.receive_webhook(
        gateway="lous",
        headers={"content-type": "application/json"},
        body=VALID_LOUS_BODY,
    )

    captured = capsys.readouterr().out

    assert response["status"] == "validated"
    assert '"event_type": "webhook_processed"' in captured
    assert response["correlation_id"] in captured
    assert "customer_identifier" in captured
    assert VALID_LOUS_BODY["customer"]["email"] not in captured
    assert VALID_LOUS_BODY["customer"]["phone"] not in captured
