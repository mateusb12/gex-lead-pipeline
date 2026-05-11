import pytest

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


def test_worker_reprocessa_com_backoff_antes_de_confirmar_sucesso(monkeypatch):
    calls = []
    sleeps = []

    def fake_process_lead_received_message(message):
        calls.append(message)

        if len(calls) < 3:
            raise RuntimeError("temporary database error")

        return {
            "lead_id": 10,
            "order_id": 20,
            "event_id": 30,
            "gateway": "lous",
            "transaction_id": "ORD-WORKER-001",
            "event": "order.approved",
            "gateway_to_db_lag_seconds": 5,
            "published_distribution_queues": [
                "dist.sms",
                "dist.email",
                "dist.callcenter",
                "dist.whatsapp",
            ],
        }

    def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(worker, "process_lead_received_message", fake_process_lead_received_message)
    monkeypatch.setattr(worker.time, "sleep", fake_sleep)

    result = worker.process_lead_received_message_with_retry(
        LEAD_RECEIVED_MESSAGE,
        retry_delays_seconds=(1, 4, 16),
    )

    assert result["attempts"] == 3
    assert len(calls) == 3
    assert sleeps == [1, 4]


def test_worker_envia_erro_para_dlq_depois_de_esgotar_retries(monkeypatch):
    calls = []
    sleeps = []

    def fake_process_lead_received_message(message):
        calls.append(message)
        raise RuntimeError("permanent database error")

    def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(worker, "process_lead_received_message", fake_process_lead_received_message)
    monkeypatch.setattr(worker.time, "sleep", fake_sleep)

    with pytest.raises(RuntimeError, match="permanent database error"):
        worker.process_lead_received_message_with_retry(
            LEAD_RECEIVED_MESSAGE,
            retry_delays_seconds=(1, 4, 16),
        )

    assert len(calls) == 4
    assert sleeps == [1, 4, 16]


def test_worker_publica_mensagem_falhada_na_dlq_do_consumer(monkeypatch):
    inserted_dead_letters = []
    published_messages = []

    def fake_insert_lead_worker_dead_letter(**kwargs):
        inserted_dead_letters.append(kwargs)
        return 1

    def fake_publish_json(**kwargs):
        published_messages.append(kwargs)

    monkeypatch.setattr(worker, "insert_lead_worker_dead_letter", fake_insert_lead_worker_dead_letter)
    monkeypatch.setattr(worker, "publish_json", fake_publish_json)

    payload = {
        "source": "lead.worker",
        "reason": "consumer_failed",
        "correlation_id": "test-correlation-id",
        "payload": LEAD_RECEIVED_MESSAGE,
        "error_detail": "permanent database error",
    }

    worker._send_lead_worker_failure_to_dlq(
        payload=payload,
        error_detail="permanent database error",
    )

    assert inserted_dead_letters[0]["source"] == "lead.worker"
    assert inserted_dead_letters[0]["reason"] == "consumer_failed"
    assert inserted_dead_letters[0]["payload"] == payload

    assert published_messages[0]["queue_name"] == "lead.dead.consumer_failed"
    assert published_messages[0]["message"] == payload


class FakeMethod:
    delivery_tag = "fake-delivery-tag"


class FakeRabbitChannel:
    def __init__(self):
        self.acked = []
        self.nacked = []

    def basic_ack(self, *, delivery_tag):
        self.acked.append(delivery_tag)

    def basic_nack(self, *, delivery_tag, requeue):
        self.nacked.append({
            "delivery_tag": delivery_tag,
            "requeue": requeue,
        })


def test_consumer_da_ack_quando_processa_com_sucesso(monkeypatch):
    channel = FakeRabbitChannel()

    def fake_process_with_retry(message):
        assert message["correlation_id"] == "TEST-ACK"
        return {
            "lead_id": 1,
            "order_id": 1,
            "gateway_to_db_lag_seconds": 1,
            "attempts": 1,
        }

    monkeypatch.setattr(worker, "process_lead_received_message_with_retry", fake_process_with_retry)

    body = b'{\n        "correlation_id": "TEST-ACK",\n        "raw_payload_id": 1,\n        "gateway": "lous",\n        "transaction_id": "TEST-ACK",\n        "event": "order.approved",\n        "customer": {"email": "test@example.com"}\n    }'.encode("utf-8")

    worker._consume_lead_received(channel, FakeMethod(), None, body)

    assert channel.acked == ["fake-delivery-tag"]
    assert channel.nacked == []


def test_consumer_da_ack_quando_envia_falha_para_dlq(monkeypatch):
    channel = FakeRabbitChannel()
    sent_to_dlq = []

    def fake_process_with_retry(message):
        raise RuntimeError("consumer failed")

    def fake_send_to_dlq(**kwargs):
        sent_to_dlq.append(kwargs)

    monkeypatch.setattr(worker, "process_lead_received_message_with_retry", fake_process_with_retry)
    monkeypatch.setattr(worker, "_send_lead_worker_failure_to_dlq", fake_send_to_dlq)

    body = b'{\n        "correlation_id": "TEST-DLQ-ACK",\n        "raw_payload_id": 1,\n        "gateway": "lous",\n        "transaction_id": "TEST-DLQ-ACK",\n        "event": "order.approved"\n    }'.encode("utf-8")

    worker._consume_lead_received(channel, FakeMethod(), None, body)

    assert len(sent_to_dlq) == 1
    assert sent_to_dlq[0]["payload"]["correlation_id"] == "TEST-DLQ-ACK"
    assert channel.acked == ["fake-delivery-tag"]
    assert channel.nacked == []


def test_consumer_da_nack_sem_requeue_quando_dlq_tambem_falha(monkeypatch):
    channel = FakeRabbitChannel()

    def fake_process_with_retry(message):
        raise RuntimeError("consumer failed")

    def fake_send_to_dlq(**kwargs):
        raise RuntimeError("dlq failed")

    monkeypatch.setattr(worker, "process_lead_received_message_with_retry", fake_process_with_retry)
    monkeypatch.setattr(worker, "_send_lead_worker_failure_to_dlq", fake_send_to_dlq)

    body = b'{\n        "correlation_id": "TEST-DLQ-FAILED",\n        "raw_payload_id": 1,\n        "gateway": "lous",\n        "transaction_id": "TEST-DLQ-FAILED",\n        "event": "order.approved"\n    }'.encode("utf-8")

    worker._consume_lead_received(channel, FakeMethod(), None, body)

    assert channel.acked == []
    assert channel.nacked == [
        {
            "delivery_tag": "fake-delivery-tag",
            "requeue": False,
        }
    ]
