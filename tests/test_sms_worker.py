import pytest
from types import SimpleNamespace

from source.features.distribution import sms_worker


SMS_MESSAGE = {
    "correlation_id": "test-correlation-id",
    "gateway": "lous",
    "transaction_id": "ORD-SMS-001",
    "event": "order.approved",
    "lead_id": 10,
    "order_id": 20,
    "channel": "SMS",
    "customer": {
        "email": "sms@example.com",
        "phone": "+18005551234",
    },
    "product": {
        "name": "Fit Burn",
    },
}


class FakeSmsPostResponse:
    status_code = 202

    def __init__(self):
        self.raise_for_status_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True


@pytest.fixture(autouse=True)
def reset_generated_sms_url(monkeypatch):
    monkeypatch.setattr(sms_worker, "_generated_dev_sms_webhook_url", None)


def test_get_sms_webhook_url_usa_url_configurada_sem_chamar_webhook_site(monkeypatch):
    def fake_create_webhook_site_url():
        raise AssertionError("webhook.site should not be called")

    monkeypatch.setattr(sms_worker.settings, "sms_webhook_url", "https://example.com/sms")
    monkeypatch.setattr(sms_worker.settings, "app_env", "dev")
    monkeypatch.setattr(sms_worker, "create_webhook_site_url", fake_create_webhook_site_url)

    assert sms_worker._get_sms_webhook_url() == "https://example.com/sms"


def test_get_sms_webhook_url_gera_e_reusa_url_em_dev(monkeypatch):
    calls = []

    def fake_create_webhook_site_url():
        calls.append(True)
        return "https://webhook.site/generated-token"

    monkeypatch.setattr(sms_worker.settings, "sms_webhook_url", "")
    monkeypatch.setattr(sms_worker.settings, "app_env", "dev")
    monkeypatch.setattr(sms_worker, "create_webhook_site_url", fake_create_webhook_site_url)
    monkeypatch.setattr(sms_worker, "log_json", lambda *args, **kwargs: None)

    assert sms_worker._get_sms_webhook_url() == "https://webhook.site/generated-token"
    assert sms_worker._get_sms_webhook_url() == "https://webhook.site/generated-token"
    assert calls == [True]


def test_get_sms_webhook_url_falha_em_production_sem_url(monkeypatch):
    monkeypatch.setattr(sms_worker.settings, "sms_webhook_url", "")
    monkeypatch.setattr(sms_worker.settings, "app_env", "production")

    with pytest.raises(RuntimeError, match="SMS webhook URL is not configured"):
        sms_worker._get_sms_webhook_url()


def test_main_falha_em_production_sem_sms_webhook_url_e_nao_chama_start_consumer(monkeypatch):
    start_consumer_calls = []

    monkeypatch.setattr(sms_worker.settings, "sms_webhook_url", "")
    monkeypatch.setattr(sms_worker.settings, "app_env", "production")
    monkeypatch.setattr(sms_worker, "start_consumer", lambda **kwargs: start_consumer_calls.append(kwargs))

    with pytest.raises(RuntimeError, match="SMS webhook URL is not configured"):
        sms_worker.main()

    assert start_consumer_calls == []


def test_main_em_dev_sem_sms_webhook_url_gera_url_dinamica_e_chama_start_consumer(monkeypatch):
    start_consumer_calls = []
    create_webhook_calls = []

    def fake_create_webhook_site_url():
        create_webhook_calls.append(True)
        return "https://webhook.site/generated-token"

    monkeypatch.setattr(sms_worker.settings, "sms_webhook_url", "")
    monkeypatch.setattr(sms_worker.settings, "app_env", "dev")
    monkeypatch.setattr(sms_worker, "create_webhook_site_url", fake_create_webhook_site_url)
    monkeypatch.setattr(sms_worker, "start_consumer", lambda **kwargs: start_consumer_calls.append(kwargs))
    monkeypatch.setattr(sms_worker, "log_json", lambda *args, **kwargs: None)

    sms_worker.main()

    assert create_webhook_calls == [True]
    assert start_consumer_calls == [
        {
            "queue_name": sms_worker.DIST_SMS_QUEUE,
            "on_message_callback": sms_worker._consume_sms_from_queue,
            "extra_queues": (sms_worker.DIST_DEAD_SMS_QUEUE,),
        }
    ]


def test_main_com_sms_webhook_url_configurado_chama_start_consumer_sem_gerar_url_dinamica(monkeypatch):
    start_consumer_calls = []
    create_webhook_calls = []

    monkeypatch.setattr(sms_worker.settings, "sms_webhook_url", "https://example.com/sms")
    monkeypatch.setattr(sms_worker.settings, "app_env", "production")
    monkeypatch.setattr(sms_worker, "create_webhook_site_url", lambda: create_webhook_calls.append(True))
    monkeypatch.setattr(sms_worker, "start_consumer", lambda **kwargs: start_consumer_calls.append(kwargs))

    sms_worker.main()

    assert create_webhook_calls == []
    assert start_consumer_calls == [
        {
            "queue_name": sms_worker.DIST_SMS_QUEUE,
            "on_message_callback": sms_worker._consume_sms_from_queue,
            "extra_queues": (sms_worker.DIST_DEAD_SMS_QUEUE,),
        }
    ]


def test_post_sms_payload_to_webhook_site_usa_url_resolvida_e_retorna_status(monkeypatch):
    calls = []
    response = FakeSmsPostResponse()

    def fake_post(*args, **kwargs):
        calls.append(
            {
                "args": args,
                "kwargs": kwargs,
            }
        )
        return response

    monkeypatch.setattr(sms_worker, "_get_sms_webhook_url", lambda: "https://webhook.site/generated-token")
    monkeypatch.setattr(sms_worker.requests, "post", fake_post)

    result = sms_worker._post_sms_payload_to_webhook_site(SMS_MESSAGE)

    assert result == 202
    assert response.raise_for_status_called is True
    assert calls == [
        {
            "args": ("https://webhook.site/generated-token",),
            "kwargs": {
                "json": {
                    "correlation_id": "test-correlation-id",
                    "gateway": "lous",
                    "transaction_id": "ORD-SMS-001",
                    "event": "order.approved",
                    "lead_id": 10,
                    "order_id": 20,
                    "channel": "SMS",
                    "to": "+18005551234",
                    "message": "Thanks for your order of Fit Burn.",
                },
                "timeout": sms_worker.POST_TIMEOUT_SECONDS,
            },
        }
    ]


def test_deliver_sms_distribution_message_with_retry_tenta_ate_sucesso(monkeypatch):
    attempts = []
    sleeps = []

    def fake_deliver(message):
        attempts.append(message["transaction_id"])
        if len(attempts) < 3:
            raise RuntimeError("provider offline")
        return {"status": "delivered"}

    monkeypatch.setattr(sms_worker, "deliver_sms_distribution_message", fake_deliver)
    monkeypatch.setattr(sms_worker.time, "sleep", lambda delay: sleeps.append(delay))
    monkeypatch.setattr(sms_worker, "log_json", lambda *args, **kwargs: None)

    result = sms_worker.deliver_sms_distribution_message_with_retry(SMS_MESSAGE)

    assert attempts == ["ORD-SMS-001", "ORD-SMS-001", "ORD-SMS-001"]
    assert sleeps == [1, 4]
    assert result == {"status": "delivered", "attempts": 3}


def test_consume_sms_from_queue_envia_para_dlq_apos_falha_total(monkeypatch):
    inserted = []
    published = []
    acknowledgements = []

    class FakeChannel:
        def basic_ack(self, delivery_tag):
            acknowledgements.append(("ack", delivery_tag))

        def basic_nack(self, delivery_tag, requeue):
            acknowledgements.append(("nack", delivery_tag, requeue))

    monkeypatch.setattr(
        sms_worker,
        "deliver_sms_distribution_message_with_retry",
        lambda message: (_ for _ in ()).throw(RuntimeError("sms unavailable")),
    )
    monkeypatch.setattr(sms_worker, "insert_sms_dead_letter_in_db", lambda **kwargs: inserted.append(kwargs))
    monkeypatch.setattr(sms_worker, "publish_json", lambda **kwargs: published.append(kwargs))
    monkeypatch.setattr(sms_worker, "log_json", lambda *args, **kwargs: None)

    sms_worker._consume_sms_from_queue(
        FakeChannel(),
        SimpleNamespace(delivery_tag=123),
        None,
        b'{"correlation_id":"test-correlation-id","gateway":"lous","transaction_id":"ORD-SMS-001","event":"order.approved","order_id":20,"channel":"SMS"}',
    )

    assert acknowledgements == [("ack", 123)]
    assert inserted[0]["payload"]["source"] == "distribution.sms"
    assert inserted[0]["payload"]["reason"] == "sms_delivery_failed"
    assert published == [
        {
            "queue_name": sms_worker.DIST_DEAD_SMS_QUEUE,
            "message": inserted[0]["payload"],
        }
    ]


def test_deliver_sms_distribution_message_marca_sms_como_delivered(monkeypatch):
    marked_orders = []

    monkeypatch.setattr(sms_worker.random, "random", lambda: 1.0)
    monkeypatch.setattr(sms_worker, "_post_sms_payload_to_webhook_site", lambda message: 202)
    monkeypatch.setattr(
        sms_worker,
        "mark_sms_as_delivered_in_db",
        lambda *, order_id: marked_orders.append(order_id) or {
            "status": "delivered",
            "db_to_channel_lag_seconds": 2,
        },
    )
    monkeypatch.setattr(sms_worker, "log_json", lambda *args, **kwargs: None)

    result = sms_worker.deliver_sms_distribution_message(SMS_MESSAGE)

    assert marked_orders == [20]
    assert result == {
        "status": "delivered",
        "db_to_channel_lag_seconds": 2,
        "webhook_status_code": 202,
    }
