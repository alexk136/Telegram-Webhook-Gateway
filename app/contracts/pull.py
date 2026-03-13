from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, validator


class PullRequestContract(BaseModel):
    bot_id: str | None = Field(
        default=None,
        description="Target bot id. Optional when key/default mapping is configured.",
        examples=["123456"],
    )
    key: str | None = Field(
        default=None,
        description="Optional bot key alias resolved via BOT_CONTEXT_BY_KEY.",
        examples=["primary"],
    )
    consumer_id: str = Field(
        default="default-consumer",
        description="Consumer identifier used to lease/ack/nack messages. Defaults to default-consumer.",
        examples=["default-consumer"],
    )
    limit: int = Field(
        default=10,
        gt=0,
        description="Maximum number of messages to lease. Defaults to 10.",
        examples=[10],
    )
    lease_seconds: int = Field(
        default=30,
        gt=0,
        description="Lease duration in seconds for each pulled message. Defaults to 30.",
        examples=[30],
    )

    @validator("consumer_id", pre=True)
    def ensure_non_empty(cls, value: Any) -> str:
        if value is None:
            return "default-consumer"
        text = str(value).strip()
        if not text:
            return "default-consumer"
        return text

    @validator("bot_id", "key", pre=True)
    def normalize_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        return text


class PullMessageContract(BaseModel):
    id: int = Field(..., description="Internal pull_inbox row id.", examples=[101])
    bot_id: str = Field(..., description="Resolved bot id for this update.", examples=["123456"])
    telegram_update_id: int = Field(..., description="Original Telegram update_id.", examples=[987654321])
    payload: dict[str, Any] = Field(..., description="Raw Telegram update payload.")
    lease_until: str = Field(..., description="Lease expiration timestamp in UTC ISO-8601.")


class PullResponseContract(BaseModel):
    messages: list[PullMessageContract] = Field(..., description="Leased messages for this request.")
    count: int = Field(..., description="Number of returned messages.", examples=[1])
    server_time: str = Field(..., description="Gateway server UTC timestamp in ISO-8601.")


def to_utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
