from fastapi import FastAPI
from app.config import settings
from app.routers.health import router as health_router
from app.routers.pull import router as pull_router
from app.routers.send import router as send_router
from app.pull_cleanup import run_pull_inbox_cleanup_once, utc_iso_or_none
from app.webhook import telegram_webhook, telegram_webhook_by_key

import asyncio
import logging
import time
import app.state as state

from app.queue.sqlite import SQLiteQueue
from app.worker import worker_loop


cleanup_task: asyncio.Task | None = None
logger = logging.getLogger("app-main")


app = FastAPI(title="Telegram Webhook Gateway")

app.include_router(health_router)
app.include_router(pull_router)
app.include_router(send_router)

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
    global cleanup_task
    if not settings.PULL_API_TOKEN:
        raise RuntimeError("PULL_API_TOKEN must be configured for pull API")

    if settings.QUEUE_BACKEND == "sqlite":
        state.queue = SQLiteQueue(settings.SQLITE_PATH)
        await state.queue.init()
        asyncio.create_task(worker_loop())
        cleanup_task = asyncio.create_task(_cleanup_loop())


@app.on_event("shutdown")
async def shutdown():
    global cleanup_task
    if cleanup_task is not None:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        cleanup_task = None


async def _cleanup_loop() -> None:
    while True:
        try:
            if state.queue is None:
                await asyncio.sleep(settings.PULL_INBOX_CLEANUP_INTERVAL_SEC)
                continue

            result = await run_pull_inbox_cleanup_once(queue=state.queue)
            state.cleanup_last_run_at = time.time()
            state.cleanup_last_deleted_acked = int(result["deleted_acked"])
            state.cleanup_last_deleted_dead = int(result["deleted_dead"])
        except asyncio.CancelledError:
            raise
        except Exception:
            state.cleanup_errors_total += 1
            logger.exception("pull inbox cleanup iteration failed")
        await asyncio.sleep(settings.PULL_INBOX_CLEANUP_INTERVAL_SEC)

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
        "pull_cleanup": {
            "last_run_at": utc_iso_or_none(state.cleanup_last_run_at),
            "last_deleted_acked": state.cleanup_last_deleted_acked,
            "last_deleted_dead": state.cleanup_last_deleted_dead,
            "errors_total": state.cleanup_errors_total,
        },
    }
