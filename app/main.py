from fastapi import FastAPI
from app.config import settings
from app.routers.health import router as health_router
from app.routers.pull import router as pull_router
from app.webhook import telegram_webhook, telegram_webhook_by_key

import asyncio
import time
import app.state as state

from app.queue.sqlite import SQLiteQueue
from app.worker import worker_loop
from app import state


app = FastAPI(title="Telegram Webhook Gateway")

app.include_router(health_router)
app.include_router(pull_router)

if "{bot_key}" in settings.TELEGRAM_WEBHOOK_PATH:
    app.add_api_route(
        settings.TELEGRAM_WEBHOOK_PATH,
        telegram_webhook_by_key,
        methods=["POST"],
    )
else:
    app.add_api_route(
        settings.TELEGRAM_WEBHOOK_PATH,
        telegram_webhook,
        methods=["POST"],
    )

    webhook_path_by_key = f"{settings.TELEGRAM_WEBHOOK_PATH.rstrip('/')}/{{bot_key}}"
    app.add_api_route(
        webhook_path_by_key,
        telegram_webhook_by_key,
        methods=["POST"],
    )


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "telegram-webhook-gateway",
        "public_mode": settings.PUBLIC_MODE,
    }


@app.on_event("startup")
async def startup():
    if not settings.PULL_API_TOKEN:
        raise RuntimeError("PULL_API_TOKEN must be configured for pull API")

    if settings.QUEUE_BACKEND == "sqlite":
        state.queue = SQLiteQueue(settings.SQLITE_PATH)
        await state.queue.init()
        asyncio.create_task(worker_loop())  

@app.get("/stats")
async def stats():
    queued = 0
    dead_count = 0

    if state.queue is not None:
        queued = await state.queue.count()
        dead_count = await state.queue.count_pull_dead()

    uptime = int(time.time() - state.started_at)

    return {
        "queued": queued,
        "dead_count": dead_count,
        "uptime_sec": uptime,
    }
