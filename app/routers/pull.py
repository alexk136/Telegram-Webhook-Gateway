import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel

import app.state as state
from app.config import settings
from app.contracts.pull import (
    PullMessageContract,
    PullRequestContract,
    PullResponseContract,
    now_utc_iso,
    to_utc_iso,
)


async def require_pull_api_auth(authorization: str | None = Header(default=None)) -> None:
    expected = settings.PULL_API_TOKEN
    if not expected:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if authorization is None:
        raise HTTPException(status_code=401, detail="Unauthorized")

    parts = authorization.split(" ", 1)
    if len(parts) != 2:
        raise HTTPException(status_code=401, detail="Unauthorized")

    scheme, token = parts
    if scheme != "Bearer":
        raise HTTPException(status_code=401, detail="Unauthorized")

    token = token.strip()
    if not token:
        raise HTTPException(status_code=401, detail="Unauthorized")

    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


router = APIRouter(tags=["pull"], dependencies=[Depends(require_pull_api_auth)])


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


class PullInboxStats(BaseModel):
    bot_id: str | None = None
    new_count: int
    leased_count: int
    acked_count: int
    dead_count: int
    expired_leases: int


class PullStatsResponse(BaseModel):
    pull_inbox: PullInboxStats
    generated_at: str


def _resolve_pull_bot_id(*, bot_id: str | None, key: str | None) -> str:
    normalized_key = key.strip() if key else None
    if normalized_key and normalized_key not in settings.BOT_CONTEXT_BY_KEY:
        raise HTTPException(status_code=404, detail="Unknown key")

    resolved_bot_id = settings.resolve_bot_id(bot_id=bot_id, bot_key=normalized_key)
    if resolved_bot_id not in settings.known_bot_ids:
        raise HTTPException(status_code=404, detail="Unknown bot_id")
    return resolved_bot_id


@router.get("/api/pull/stats", response_model=PullStatsResponse)
async def pull_stats(
    bot_id: str | None = Query(default=None),
    key: str | None = Query(default=None),
):
    if settings.QUEUE_BACKEND != "sqlite" or state.queue is None:
        raise HTTPException(status_code=503, detail="Queue backend is not available")

    normalized_bot_id = _resolve_pull_bot_id(bot_id=bot_id, key=key)

    stats = await state.queue.pull_inbox_stats(bot_id=normalized_bot_id)
    pull_inbox = PullInboxStats(
        bot_id=normalized_bot_id,
        new_count=stats["new_count"],
        leased_count=stats["leased_count"],
        acked_count=stats["acked_count"],
        dead_count=stats["dead_count"],
        expired_leases=stats["expired_leases"],
    )
    return PullStatsResponse(
        pull_inbox=pull_inbox,
        generated_at=now_utc_iso(),
    )


@router.post("/api/pull", response_model=PullResponseContract)
async def pull_messages(payload: PullRequestContract):
    if settings.QUEUE_BACKEND != "sqlite" or state.queue is None:
        raise HTTPException(status_code=503, detail="Queue backend is not available")

    if payload.limit > settings.PULL_MAX_LIMIT:
        raise HTTPException(
            status_code=422,
            detail=f"limit must be <= {settings.PULL_MAX_LIMIT}",
        )

    normalized_bot_id = _resolve_pull_bot_id(bot_id=payload.bot_id, key=payload.key)

    leased = await state.queue.lease_pull(
        consumer_id=payload.consumer_id,
        lease_seconds=payload.lease_seconds,
        limit=payload.limit,
        bot_id=normalized_bot_id,
    )

    messages = [
        PullMessageContract(
            id=item["id"],
            bot_id=item["bot_id"],
            telegram_update_id=item["telegram_update_id"],
            lease_until=to_utc_iso(int(item["lease_until"])),
            payload=item["payload_json"],
        )
        for item in leased
    ]
    return PullResponseContract(
        messages=messages,
        count=len(messages),
        server_time=now_utc_iso(),
    )


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
        max_pull_retries=settings.MAX_PULL_RETRIES,
    )
    return NackResponse(
        ok=True,
        requested=result["requested"],
        nacked=result["nacked"],
        skipped=result["skipped"],
        results=[NackResultItem(**item) for item in result["results"]],
    )
