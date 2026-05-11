import asyncio

import httpx

from source.features.debug import router as debug_router
from source.main import app


async def _get(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path)


async def _delete(path: str) -> httpx.Response:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.delete(path)


def test_listar_payloads_brutos_retorna_itens_salvos(monkeypatch):
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


def test_limpar_banco_debug_exige_confirmacao(monkeypatch):
    def fake_clear_debug_database(*, confirm: bool = False):
        return {
            "status": "confirmation_required",
            "confirm": confirm,
        }

    monkeypatch.setattr(debug_router, "clear_debug_database", fake_clear_debug_database)

    response = asyncio.run(_delete("/debug/database"))

    assert response.status_code == 200
    assert response.json() == {
        "status": "confirmation_required",
        "confirm": False,
    }


def test_limpar_banco_debug_com_confirmacao(monkeypatch):
    def fake_clear_debug_database(*, confirm: bool = False):
        return {
            "status": "ok",
            "confirm": confirm,
            "total_deleted": 10,
            "deleted_by_table": {
                "raw_payloads": 5,
                "lead_dead_letter": 5,
            },
        }

    monkeypatch.setattr(debug_router, "clear_debug_database", fake_clear_debug_database)

    response = asyncio.run(_delete("/debug/database?confirm=true"))

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["confirm"] is True
    assert response.json()["total_deleted"] == 10
