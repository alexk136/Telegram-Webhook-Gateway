from fastapi import FastAPI
from app.config import settings
from app.routers.health import router as health_router
from app.routers.pull import router as pull_router
from app.routers.send import router as send_router
from app.pull_cleanup import run_pull_inbox_cleanup_once, utc_iso_or_none
from app.webhook import process_telegram_update, telegram_webhook, telegram_webhook_by_key
from app.bot import bot

import asyncio
import logging
import time
import app.state as state

from app.queue.sqlite import SQLiteQueue
from app.worker import worker_loop


cleanup_task: asyncio.Task | None = None
polling_task: asyncio.Task | None = None
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


@app.on_event("startup")
async def startup():
    global cleanup_task, polling_task
    if not settings.PULL_API_TOKEN:
        raise RuntimeError("PULL_API_TOKEN must be configured for pull API")

    if settings.QUEUE_BACKEND == "sqlite":
        state.queue = SQLiteQueue(settings.SQLITE_PATH)
        await state.queue.init()
        asyncio.create_task(worker_loop())
        cleanup_task = asyncio.create_task(_cleanup_loop())

    if await _should_start_polling():
        polling_task = asyncio.create_task(_polling_loop())


@app.on_event("shutdown")
async def shutdown():
    global cleanup_task, polling_task
    if cleanup_task is not None:
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        cleanup_task = None

    if polling_task is not None:
        polling_task.cancel()
        try:
            await polling_task
        except asyncio.CancelledError:
            pass
        polling_task = None


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


async def _should_start_polling() -> bool:
    mode = settings.TELEGRAM_INGEST_MODE
    if mode == "webhook":
        return False
    if mode == "poll":
        return True

    webhook_info = await bot.get_webhook_info()
    return not bool((webhook_info.url or "").strip())


async def _polling_loop() -> None:
    logger.info("telegram polling fallback started")
    next_offset: int | None = None

    while True:
        try:
            updates = await bot.get_updates(
                offset=next_offset,
                timeout=settings.TELEGRAM_POLL_TIMEOUT_SEC,
            )
            for update in updates:
                next_offset = int(update.update_id) + 1
                try:
                    await process_telegram_update(update)
                except Exception:
                    logger.exception(
                        "telegram polling update processing failed for update_id=%s",
                        update.update_id,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("telegram polling iteration failed")
            await asyncio.sleep(settings.TELEGRAM_POLL_ERROR_DELAY_SEC)

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
