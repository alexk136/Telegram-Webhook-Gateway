from __future__ import annotations

from typing import Any

from pydantic import BaseModel, validator


class LocalWebhookPayloadContract(BaseModel):
    bot_id: str
    telegram_update_id: int
    pull_message_id: int | str
    update: dict[str, Any]

    @validator("bot_id", pre=True)
    def validate_bot_id(cls, value: Any) -> str:
        if value is None:
            raise ValueError("bot_id is required")
        text = str(value).strip()
        if not text:
            raise ValueError("bot_id must not be empty")
        return text

    @validator("telegram_update_id", pre=True)
    def validate_telegram_update_id(cls, value: Any) -> int:
        if value is None or isinstance(value, bool):
            raise ValueError("telegram_update_id is required")
        update_id = int(value)
        if update_id < 0:
            raise ValueError("telegram_update_id must be >= 0")
        return update_id

    @validator("pull_message_id", pre=True)
    def validate_pull_message_id(cls, value: Any) -> int | str:
        if value is None:
            raise ValueError("pull_message_id is required")
        if isinstance(value, bool):
            raise ValueError("pull_message_id must not be bool")
        if isinstance(value, int):
            return value
        text = str(value).strip()
        if not text:
            raise ValueError("pull_message_id must not be empty")
        return text

    @validator("update", pre=True)
    def validate_update(cls, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError("update must be a JSON object")
        return value


def build_local_webhook_payload(msg: dict[str, Any]) -> LocalWebhookPayloadContract:
    update = msg.get("payload")
    if not isinstance(update, dict):
        update = {}

    return LocalWebhookPayloadContract(
        bot_id=msg.get("bot_id"),
        telegram_update_id=msg.get("telegram_update_id"),
        pull_message_id=msg.get("id"),
        update=update,
    )


def extract_idempotency_key(payload: dict[str, Any]) -> tuple[str, int]:
    parsed = LocalWebhookPayloadContract(**payload)
    return parsed.bot_id, parsed.telegram_update_id
