import asyncio

import httpx

from source.features.webhooks import router as webhooks_router
from source.main import app


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


async def _post(path: str, *, json: dict) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.post(path, json=json)


def test_health_check_retorna_status_ok():
    response = asyncio.run(_get("/health"))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_endpoint_webhook_lous_retorna_resposta_do_service(monkeypatch):
    def fake_receive_webhook_service(*, gateway, headers, body):
        return {
            "status": "validated",
            "pipeline": "lead.received",
            "gateway": gateway,
            "correlation_id": "test-correlation-id",
            "raw_payload_id": 123,
            "should_publish_to_lead_queue": True,
        }

    monkeypatch.setattr(webhooks_router, "receive_webhook_service", fake_receive_webhook_service)

    response = asyncio.run(_post("/webhooks/lous", json={"hello": "world"}))

    assert response.status_code == 200
    assert response.json() == {
        "status": "validated",
        "pipeline": "lead.received",
        "gateway": "lous",
        "correlation_id": "test-correlation-id",
        "raw_payload_id": 123,
        "should_publish_to_lead_queue": True,
    }
