from fastapi.testclient import TestClient

from source.features.webhooks import router as webhooks_router
from source.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_lous_stub(monkeypatch):
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

    response = client.post("/webhooks/lous", json={"hello": "world"})

    assert response.status_code == 200
    assert response.json() == {
        "status": "validated",
        "pipeline": "lead.received",
        "gateway": "lous",
        "correlation_id": "test-correlation-id",
        "raw_payload_id": 123,
        "should_publish_to_lead_queue": True,
    }
