import pytest

from source.features.distribution import webhook_site


class FakeWebhookSiteResponse:
    def __init__(self, payload):
        self.payload = payload
        self.raise_for_status_called = False

    def raise_for_status(self):
        self.raise_for_status_called = True

    def json(self):
        return self.payload


def test_create_webhook_site_url_cria_url_com_uuid(monkeypatch):
    response = FakeWebhookSiteResponse({"uuid": "00000000-0000-0000-0000-000000000000"})
    calls = []

    def fake_post(*args, **kwargs):
        calls.append(
            {
                "args": args,
                "kwargs": kwargs,
            }
        )
        return response

    monkeypatch.setattr(webhook_site.requests, "post", fake_post)

    result = webhook_site.create_webhook_site_url()

    assert result == "https://webhook.site/00000000-0000-0000-0000-000000000000"
    assert response.raise_for_status_called is True
    assert calls == [
        {
            "args": (webhook_site.WEBHOOK_SITE_TOKEN_URL,),
            "kwargs": {
                "headers": {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                "timeout": webhook_site.REQUEST_TIMEOUT_SECONDS,
            },
        }
    ]


def test_create_webhook_site_url_falha_quando_resposta_nao_tem_uuid(monkeypatch):
    response = FakeWebhookSiteResponse({})

    monkeypatch.setattr(webhook_site.requests, "post", lambda *args, **kwargs: response)

    with pytest.raises(RuntimeError, match="Webhook.site token response did not include uuid"):
        webhook_site.create_webhook_site_url()
