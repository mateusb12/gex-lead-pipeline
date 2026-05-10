from fastapi import FastAPI

from source.features.webhooks.router import router as webhooks_router

app = FastAPI(title="GEX Lead Pipeline", version="0.1.0")

app.include_router(webhooks_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}
