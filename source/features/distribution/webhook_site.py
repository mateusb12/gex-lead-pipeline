import requests

WEBHOOK_SITE_TOKEN_URL = "https://webhook.site/token"
WEBHOOK_SITE_BASE_URL = "https://webhook.site"
REQUEST_TIMEOUT_SECONDS = 10


def create_webhook_site_url() -> str:
    response = requests.post(
        WEBHOOK_SITE_TOKEN_URL,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    data = response.json()
    token_uuid = data.get("uuid")

    if not token_uuid:
        raise RuntimeError("Webhook.site token response did not include uuid")

    return f"{WEBHOOK_SITE_BASE_URL}/{token_uuid}"
