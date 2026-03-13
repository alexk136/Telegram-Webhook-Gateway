from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, validator

from app.config import settings
from app.routers.pull import require_pull_api_auth


router = APIRouter(tags=["send"], dependencies=[Depends(require_pull_api_auth)])


class SendRequest(BaseModel):
    text: str
    chat_id: int | None = None
    key: str | None = None
    disable_notification: bool | None = None
    parse_mode: str | None = None

    @validator("text", pre=True)
    def validate_text(cls, value: Any) -> str:
        if value is None:
            raise ValueError("text is required")
        text = str(value).strip()
        if not text:
            raise ValueError("text must not be empty")
        return text

    @validator("key", pre=True)
    def normalize_key(cls, value: Any) -> str | None:
        if value is None:
            return None
        key = str(value).strip()
        if not key:
            return None
        return key

    @validator("chat_id")
    def validate_chat_id(cls, value: int | None) -> int | None:
        if value == 0:
            raise ValueError("chat_id must not be 0")
        return value


class SendResponse(BaseModel):
    ok: bool
    telegram_ok: bool
    key_used: str | None
    chat_id: int
    message_id: int
    bot_id: str


@router.post("/api/send", response_model=SendResponse)
async def send_message(payload: SendRequest):
    key = payload.key
    if key is not None and key not in settings.BOT_TOKEN_BY_KEY:
        raise HTTPException(status_code=404, detail="Unknown key")

    chat_id = payload.chat_id
    if chat_id is None:
        chat_id = settings.resolve_default_chat_id(bot_key=key)
    if chat_id is None:
        raise HTTPException(status_code=400, detail="chat_id is required when no default is configured")

    bot_token = settings.resolve_bot_token(bot_key=key)
    bot_id = bot_token.split(":", 1)[0].strip()
    if not bot_id:
        raise HTTPException(status_code=500, detail="Invalid bot token")

    telegram_payload: dict[str, Any] = {
        "chat_id": chat_id,
        "text": payload.text,
    }
    if payload.disable_notification is not None:
        telegram_payload["disable_notification"] = payload.disable_notification
    if payload.parse_mode is not None:
        telegram_payload["parse_mode"] = payload.parse_mode

    telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=settings.FORWARD_TIMEOUT_SEC) as client:
            response = await client.post(telegram_url, json=telegram_payload)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Telegram request failed: {exc}")

    if response.status_code >= 400:
        detail = response.text.strip() or "Telegram API error"
        raise HTTPException(status_code=502, detail=detail)

    try:
        body = response.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Telegram API returned invalid JSON")

    if not isinstance(body, dict) or not body.get("ok"):
        raise HTTPException(status_code=502, detail="Telegram API returned unsuccessful response")

    result = body.get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=502, detail="Telegram API result is missing")

    message_id = result.get("message_id")
    if not isinstance(message_id, int):
        raise HTTPException(status_code=502, detail="Telegram API response has invalid message_id")

    return SendResponse(
        ok=True,
        telegram_ok=True,
        key_used=key,
        chat_id=int(chat_id),
        message_id=message_id,
        bot_id=bot_id,
    )
