from uuid import UUID

from source.features.webhooks import service


def test_receive_webhook_persists_raw_payload(monkeypatch):
    captured = {}

    def fake_insert_raw_payload(**kwargs):
        captured.update(kwargs)
        return 456

    monkeypatch.setattr(service, "insert_raw_payload", fake_insert_raw_payload)

    response = service.receive_webhook(
        gateway="lous", headers={"content-type": "application/json"}, body={"hello": "world"}
    )

    UUID(response["correlation_id"])

    assert response["status"] == "received"
    assert response["gateway"] == "lous"
    assert response["raw_payload_id"] == 456
    assert response["stub"] is True
    assert response["body_keys"] == ["hello"]

    assert captured["correlation_id"] == response["correlation_id"]
    assert captured["gateway"] == "lous"
    assert captured["headers"] == {"content-type": "application/json"}
    assert captured["body_original"] == {"hello": "world"}
