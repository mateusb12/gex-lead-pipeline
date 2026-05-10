from fastapi.testclient import TestClient

from source.main import app


client = TestClient(app)


def test_health_check():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_webhook_lous_stub():
    response = client.post("/webhooks/lous", json={"hello": "world"})

    assert response.status_code == 200
    assert response.json()["status"] == "received"
    assert response.json()["gateway"] == "lous"
