from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator

import app.state as state
from app.config import settings

router = APIRouter(tags=["pull"])


class PullRequest(BaseModel):
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


class PullItem(BaseModel):
    id: int
    bot_id: str
    telegram_update_id: int
    lease_until: str
    payload: dict[str, Any]


class PullResponse(BaseModel):
    items: list[PullItem]
    count: int


def _to_utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


@router.post("/api/pull", response_model=PullResponse)
async def pull_messages(payload: PullRequest):
    if settings.QUEUE_BACKEND != "sqlite" or state.queue is None:
        raise HTTPException(status_code=503, detail="Queue backend is not available")

    if payload.limit > settings.PULL_MAX_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be <= {settings.PULL_MAX_LIMIT}",
        )

    if payload.bot_id not in settings.known_bot_ids:
        raise HTTPException(status_code=404, detail="Unknown bot_id")

    leased = await state.queue.lease_pull(
        consumer_id=payload.consumer_id,
        lease_seconds=payload.lease_seconds,
        limit=payload.limit,
        bot_id=payload.bot_id,
    )

    items = [
        PullItem(
            id=item["id"],
            bot_id=item["bot_id"],
            telegram_update_id=item["telegram_update_id"],
            lease_until=_to_utc_iso(int(item["lease_until"])),
            payload=item["payload_json"],
        )
        for item in leased
    ]
    return PullResponse(items=items, count=len(items))
