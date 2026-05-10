from fastapi import FastAPI

from source.features.debug.router import router as debug_router
from source.features.webhooks.router import router as webhooks_router

app = FastAPI(title="GEX Lead Pipeline", version="0.1.0")

app.include_router(webhooks_router)
app.include_router(debug_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
