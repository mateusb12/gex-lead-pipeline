from source.features.leads import worker


LEAD_RECEIVED_MESSAGE = {
    "correlation_id": "test-correlation-id",
    "raw_payload_id": 123,
    "gateway": "lous",
    "transaction_id": "ORD-WORKER-001",
    "transaction_time": "2026-05-11T15:00:00+00:00",
    "event": "order.approved",
    "customer": {
        "email": "worker@example.com",
        "first_name": "Worker",
        "last_name": "Customer",
        "phone": "+18005551234",
        "phone_is_valid": True,
        "country": "US",
    },
    "product": {
        "id": "PROD-001",
        "name": "Fit Burn",
        "niche": "weight_loss",
    },
    "quantity": 1,
    "payment": {
        "amount_usd": "99.90",
        "method": "credit_card",
        "status": "approved",
    },
}


def test_worker_persiste_lead_received_e_publica_quatro_eventos_de_distribuicao(monkeypatch):
    published_messages = []

    def fake_persist_lead_received_message(message):
        assert message["transaction_id"] == "ORD-WORKER-001"

        return {
            "lead_id": 10,
            "order_id": 20,
            "event_id": 30,
            "gateway": "lous",
            "transaction_id": "ORD-WORKER-001",
            "event": "order.approved",
            "gateway_to_db_lag_seconds": 5,
            "distribution_channels": ["SMS", "EMAIL", "CALL_CENTER", "WHATSAPP"],
        }

    def fake_publish_json(**kwargs):
        published_messages.append(kwargs)

    monkeypatch.setattr(worker, "persist_lead_received_message", fake_persist_lead_received_message)
    monkeypatch.setattr(worker, "publish_json", fake_publish_json)

    result = worker.process_lead_received_message(LEAD_RECEIVED_MESSAGE)

    assert result["lead_id"] == 10
    assert result["order_id"] == 20
    assert result["published_distribution_queues"] == [
        "dist.sms",
        "dist.email",
        "dist.callcenter",
        "dist.whatsapp",
    ]

    assert [item["queue_name"] for item in published_messages] == [
        "dist.sms",
        "dist.email",
        "dist.callcenter",
        "dist.whatsapp",
    ]

    assert {item["message"]["channel"] for item in published_messages} == {
        "SMS",
        "EMAIL",
        "CALL_CENTER",
        "WHATSAPP",
    }

    assert all(item["message"]["order_id"] == 20 for item in published_messages)
