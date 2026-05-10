import asyncio

import httpx

from source.features.debug import router as debug_router
from source.main import app


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


def test_list_raw_payloads(monkeypatch):
    def fake_get_raw_payloads(limit: int = 10):
        return {
            "count": 1,
            "items": [
                {
                    "id": 1,
                    "correlation_id": "test-correlation-id",
                    "gateway": "lous",
                    "received_at": "2026-05-10T17:49:30",
                    "headers": {"content-type": "application/json"},
                    "body_original": {"hello": "world"},
                    "body_decrypted": None,
                    "error_reason": None,
                }
            ],
        }

    monkeypatch.setattr(debug_router, "get_raw_payloads", fake_get_raw_payloads)

    response = asyncio.run(_get("/debug/raw-payloads?limit=5"))

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["items"][0]["gateway"] == "lous"
    assert response.json()["items"][0]["body_original"] == {"hello": "world"}
