from fastapi import APIRouter, HTTPException, Request

from source.features.webhooks.service import receive_webhook as receive_webhook_service

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/{gateway}")
async def receive_webhook(gateway: str, request: Request):
    if gateway not in {"lous", "grummer"}:
        raise HTTPException(status_code=404, detail="Unsupported gateway")

    body = await request.json()

    return receive_webhook_service(gateway=gateway, headers=dict(request.headers), body=body)
