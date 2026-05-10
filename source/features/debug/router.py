from fastapi import APIRouter, Query

from source.features.debug.service import get_raw_payloads

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/raw-payloads")
def list_raw_payloads(limit: int = Query(default=10, ge=1, le=100)):
    return get_raw_payloads(limit=limit)
