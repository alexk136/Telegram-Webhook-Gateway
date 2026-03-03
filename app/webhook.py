from fastapi import Request, HTTPException
from aiogram.types import Update
from app.bot import dp, bot
from app.config import settings
import app.state as state


def _resolve_bot_id(bot_key: str | None) -> str:
    if bot_key:
        resolved = settings.BOT_CONTEXT_BY_KEY.get(bot_key)
        if not resolved:
            raise HTTPException(status_code=400, detail="Unknown bot context")
        return resolved

    token_prefix = settings.BOT_TOKEN.split(":", 1)[0].strip()
    if token_prefix:
        return token_prefix
    raise HTTPException(
        status_code=500,
        detail="Cannot resolve bot context for webhook ingest",
    )


async def _telegram_webhook_impl(request: Request, bot_key: str | None):
    if settings.TELEGRAM_SECRET_TOKEN:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != settings.TELEGRAM_SECRET_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid secret")

    body = await request.body()
    if len(body) > settings.MAX_BODY_SIZE_KB * 1024:
        raise HTTPException(status_code=413, detail="Payload too large")

    update = Update.model_validate_json(body)
    bot_id = _resolve_bot_id(bot_key)

    if settings.QUEUE_BACKEND == "sqlite" and state.queue is not None:
        telegram_update_id = int(update.update_id)
        await state.queue.enqueue_pull(
            source_update_id=telegram_update_id,
            bot_id=bot_id,
            telegram_update_id=telegram_update_id,
            payload_json=update.model_dump(),
        )

    await dp.feed_update(bot, update)
    return {"ok": True}


async def telegram_webhook(request: Request):
    return await _telegram_webhook_impl(request, bot_key=None)


async def telegram_webhook_by_key(request: Request, bot_key: str):
    return await _telegram_webhook_impl(request, bot_key=bot_key)
