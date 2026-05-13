from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from source.features.debug.router import router as debug_router
from source.features.webhooks.decryption import validate_grummer_secret_config
from source.features.webhooks.router import router as webhooks_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    validate_grummer_secret_config()
    yield


app = FastAPI(title="GEX Lead Pipeline", version="0.1.0", lifespan=lifespan)

app.include_router(webhooks_router)
app.include_router(debug_router)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
