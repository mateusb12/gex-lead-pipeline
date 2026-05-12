import pytest

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
