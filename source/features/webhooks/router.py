from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/{gateway}")
async def receive_webhook(gateway: str, request: Request):
    if gateway not in {"lous", "grummer"}:
        raise HTTPException(status_code=404, detail="Unsupported gateway")

    body = await request.json()
    correlation_id = str(uuid4())

    return {
        "status": "received",
        "gateway": gateway,
        "correlation_id": correlation_id,
        "stub": True,
        "body_keys": list(body.keys()) if isinstance(body, dict) else [],
    }
