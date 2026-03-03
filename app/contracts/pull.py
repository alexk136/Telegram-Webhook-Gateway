from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field, validator


class PullRequestContract(BaseModel):
    bot_id: str
    consumer_id: str
    limit: int = Field(..., gt=0)
    lease_seconds: int = Field(..., gt=0)

    @validator("bot_id", "consumer_id", pre=True)
    def ensure_non_empty(cls, value: Any) -> str:
        if value is None:
            raise ValueError("must not be empty")
        text = str(value).strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class PullMessageContract(BaseModel):
    id: int
    bot_id: str
    telegram_update_id: int
    payload: dict[str, Any]
    lease_until: str


class PullResponseContract(BaseModel):
    messages: list[PullMessageContract]
    count: int
    server_time: str


def to_utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
