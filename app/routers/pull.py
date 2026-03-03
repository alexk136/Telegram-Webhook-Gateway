from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Request
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


class AckRejected(BaseModel):
    message_id: int
    reason: str


class AckResponse(BaseModel):
    ok: bool
    acked_ids: list[int]
    already_acked_ids: list[int]
    rejected: list[AckRejected]


class NackResultItem(BaseModel):
    message_id: int
    status: str
    reason: str | None = None


class NackResponse(BaseModel):
    ok: bool
    requested: int
    nacked: int
    skipped: int
    results: list[NackResultItem]


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


@router.post("/api/ack", response_model=AckResponse)
async def ack_messages(request: Request):
    if settings.QUEUE_BACKEND != "sqlite" or state.queue is None:
        raise HTTPException(status_code=503, detail="Queue backend is not available")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    if "consumer_id" not in payload:
        raise HTTPException(status_code=400, detail="consumer_id is required")
    if "message_ids" not in payload:
        raise HTTPException(status_code=400, detail="message_ids is required")

    consumer_id = str(payload["consumer_id"]).strip()
    if not consumer_id:
        raise HTTPException(status_code=400, detail="consumer_id must not be empty")

    message_ids_raw = payload["message_ids"]
    if not isinstance(message_ids_raw, list) or not message_ids_raw:
        raise HTTPException(status_code=400, detail="message_ids must be a non-empty array")

    message_ids: list[int] = []
    for item in message_ids_raw:
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise HTTPException(
                status_code=400,
                detail="message_ids must contain positive integer IDs",
            )
        message_ids.append(item)

    result = await state.queue.ack_pull_batch(
        message_ids=message_ids,
        consumer_id=consumer_id,
    )
    return AckResponse(
        ok=True,
        acked_ids=result["acked_ids"],
        already_acked_ids=result["already_acked_ids"],
        rejected=[AckRejected(**item) for item in result["rejected"]],
    )


@router.post("/api/nack", response_model=NackResponse)
async def nack_messages(request: Request):
    if settings.QUEUE_BACKEND != "sqlite" or state.queue is None:
        raise HTTPException(status_code=503, detail="Queue backend is not available")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Payload must be a JSON object")

    if "consumer_id" not in payload:
        raise HTTPException(status_code=400, detail="consumer_id is required")
    if "message_ids" not in payload:
        raise HTTPException(status_code=400, detail="message_ids is required")

    consumer_id = str(payload["consumer_id"]).strip()
    if not consumer_id:
        raise HTTPException(status_code=400, detail="consumer_id must not be empty")

    message_ids_raw = payload["message_ids"]
    if not isinstance(message_ids_raw, list) or not message_ids_raw:
        raise HTTPException(status_code=400, detail="message_ids must be a non-empty array")

    message_ids: list[int] = []
    for item in message_ids_raw:
        if not isinstance(item, int) or isinstance(item, bool) or item <= 0:
            raise HTTPException(
                status_code=400,
                detail="message_ids must contain positive integer IDs",
            )
        message_ids.append(item)

    error_raw = payload.get("error")
    error: str | None = None
    if error_raw is not None:
        error = str(error_raw).strip()
        if not error:
            error = None

    result = await state.queue.nack_pull_batch(
        message_ids=message_ids,
        consumer_id=consumer_id,
        error=error,
    )
    return NackResponse(
        ok=True,
        requested=result["requested"],
        nacked=result["nacked"],
        skipped=result["skipped"],
        results=[NackResultItem(**item) for item in result["results"]],
    )
