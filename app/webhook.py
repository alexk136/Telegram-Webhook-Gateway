from fastapi import Request, HTTPException
from aiogram.types import Update
from app.bot import dp, bot
from app.config import settings
import app.state as state


async def telegram_webhook(request: Request):
    if settings.TELEGRAM_SECRET_TOKEN:
        secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret != settings.TELEGRAM_SECRET_TOKEN:
            raise HTTPException(status_code=403, detail="Invalid secret")

    body = await request.body()
    if len(body) > settings.MAX_BODY_SIZE_KB * 1024:
        raise HTTPException(status_code=413, detail="Payload too large")

    update = Update.model_validate_json(body)
    if settings.QUEUE_BACKEND == "sqlite" and state.queue is not None:
        telegram_update_id = int(update.update_id)
        bot_id = settings.BOT_TOKEN.split(":", 1)[0]
        await state.queue.enqueue_pull(
            source_update_id=telegram_update_id,
            bot_id=bot_id,
            telegram_update_id=telegram_update_id,
            payload_json=update.model_dump(),
        )

    await dp.feed_update(bot, update)
    return {"ok": True}
