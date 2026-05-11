from fastapi import APIRouter, Query

from source.features.debug.benchmark import replay_benchmark_payloads
from source.features.debug.service import clear_debug_database, get_raw_payloads

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/raw-payloads")
def list_raw_payloads(limit: int = Query(default=10, ge=1, le=100)):
    return get_raw_payloads(limit=limit)


@router.post("/benchmark/replay")
def replay_benchmark(
    limit: int | None = Query(default=None, ge=1, le=1000),
    dry_run: bool = False,
    cleanup_previous: bool = True,
):
    return replay_benchmark_payloads(
        limit=limit,
        dry_run=dry_run,
        cleanup_previous=cleanup_previous,
    )


@router.delete("/database")
def clear_database(confirm: bool = Query(default=False)):
    return clear_debug_database(confirm=confirm)
