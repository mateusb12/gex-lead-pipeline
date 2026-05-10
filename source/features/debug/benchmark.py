import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from source.features.webhooks.service import receive_webhook
from source.shared.db import get_engine
from source.shared.tables import raw_payloads

ASSETS_DIR = Path("assets")
WEBHOOK_PAYLOADS_PATH = ASSETS_DIR / "webhook_payloads.json"
BENCHMARK_HEADER = "X-Debug-Benchmark"


def replay_benchmark_payloads(
    *,
    limit: int | None = None,
    dry_run: bool = False,
    cleanup_previous: bool = True,
) -> dict[str, Any]:
    if not WEBHOOK_PAYLOADS_PATH.exists():
        return {
            "status": "assets_not_found",
            "message": "Place webhook_payloads.json in assets/ before running the benchmark replay.",
            "expected_path": str(WEBHOOK_PAYLOADS_PATH),
        }

    payloads = _load_webhook_payloads(WEBHOOK_PAYLOADS_PATH)

    if limit is not None:
        payloads = payloads[:limit]

    deleted_previous_rows = 0

    if cleanup_previous and not dry_run:
        deleted_previous_rows = delete_previous_benchmark_raw_payloads()

    statuses: Counter[str] = Counter()
    gateways: Counter[str] = Counter()
    by_gateway_status: dict[str, Counter[str]] = defaultdict(Counter)
    errors: list[dict[str, Any]] = []

    for index, item in enumerate(payloads, start=1):
        try:
            normalized = _normalize_benchmark_item(item)
            gateway = normalized["gateway"]
            headers = _with_benchmark_header(normalized["headers"])
            body = normalized["body"]

            gateways[gateway] += 1

            if dry_run:
                status = "dry_run"
            else:
                response = receive_webhook(
                    gateway=gateway,
                    headers=headers,
                    body=body,
                )
                status = str(response.get("status", "unknown"))

            statuses[status] += 1
            by_gateway_status[gateway][status] += 1

        except Exception as exc:  # noqa: BLE001
            statuses["benchmark_error"] += 1
            errors.append(
                {
                    "index": index,
                    "error": type(exc).__name__,
                    "message": str(exc),
                }
            )

    return {
        "status": "ok",
        "dry_run": dry_run,
        "cleanup_previous": cleanup_previous,
        "deleted_previous_rows": deleted_previous_rows,
        "source_file": str(WEBHOOK_PAYLOADS_PATH),
        "total_loaded": len(payloads),
        "gateways": dict(gateways),
        "statuses": dict(statuses),
        "by_gateway_status": {
            gateway: dict(counter)
            for gateway, counter in by_gateway_status.items()
        },
        "errors": errors[:20],
        "errors_truncated": max(len(errors) - 20, 0),
    }


def delete_previous_benchmark_raw_payloads() -> int:
    statement = raw_payloads.delete().where(
        raw_payloads.c.headers[BENCHMARK_HEADER].as_string() == "true"
    )

    with get_engine().begin() as connection:
        result = connection.execute(statement)

    return int(result.rowcount or 0)


def _with_benchmark_header(headers: dict[str, Any]) -> dict[str, Any]:
    return {
        **headers,
        BENCHMARK_HEADER: "true",
    }


def _load_webhook_payloads(path: Path) -> list[Any]:
    data = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("webhooks", "payloads", "items", "data"):
            value = data.get(key)

            if isinstance(value, list):
                return value

    raise ValueError("webhook_payloads.json must be a list or contain a list under webhooks/payloads/items/data")


def _normalize_benchmark_item(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ValueError("benchmark item must be a JSON object")

    headers = item.get("headers") or {}

    if not isinstance(headers, dict):
        headers = {}

    body = (
        item.get("body")
        or item.get("payload")
        or item.get("body_original")
        or _body_without_wrapper_keys(item)
    )

    if not isinstance(body, dict):
        raise ValueError("benchmark item body must be a JSON object")

    gateway = item.get("gateway") or _infer_gateway(headers=headers, body=body)

    if not isinstance(gateway, str):
        raise ValueError("could not infer gateway")

    gateway = gateway.lower().strip()

    if gateway not in {"lous", "grummer"}:
        raise ValueError(f"unsupported gateway in benchmark item: {gateway}")

    has_encrypted_header = "X-GR-Encrypted" in headers or "x-gr-encrypted" in headers

    if gateway == "grummer" and not has_encrypted_header:
        headers = {**headers, "X-GR-Encrypted": "true"}

    return {
        "gateway": gateway,
        "headers": headers,
        "body": body,
    }


def _body_without_wrapper_keys(item: dict[str, Any]) -> dict[str, Any]:
    wrapper_keys = {
        "gateway",
        "headers",
        "received_at",
        "receivedAt",
        "source",
    }

    return {
        key: value
        for key, value in item.items()
        if key not in wrapper_keys
    }


def _infer_gateway(*, headers: dict[str, Any], body: dict[str, Any]) -> str:
    encrypted_header = headers.get("X-GR-Encrypted") or headers.get("x-gr-encrypted")

    if encrypted_header is not None:
        return "grummer"

    if "iv" in body and "ciphertext" in body:
        return "grummer"

    return "lous"
